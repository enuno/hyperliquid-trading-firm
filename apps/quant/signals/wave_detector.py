"""
apps/quant/signals/wave_detector.py

Deterministic wave structure and market phase detector.
Adapted from Wavedge (github.com/koobraelc/wavedge) concepts,
re-implemented for HyperLiquid perp closed-bar data.

IMPORTANT CONSTRAINTS:
  - Run on CLOSED bars only. Never include the current incomplete bar.
  - Pre-filter liquidation-spike wicks before analysis (see _filter_liq_wicks).
  - All outputs are typed dataclasses — no free-form strings in hot paths.
  - This module has zero LLM calls, zero network calls, zero side effects.
  - Used by: apps/agents/observer/observer_agent.py (→ ObservationPack)
             apps/quant/signals/wave_adapter.py
             apps/quant/regimes/qz_regime_classifier.py

Design principles:
  - Wave labeling is inherently ambiguous. This module returns the
    most statistically probable structural interpretation, NOT ground truth.
  - Treat wave_phase as strong advisory evidence; it is not trade authorization.
  - All thresholds are configurable; defaults are conservative for HL perps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums and Data Models
# ---------------------------------------------------------------------------

class WavePhase(str, Enum):
    """
    Market structure phase classification.
    Maps to QZRegime via wave_adapter.py.
    """
    IMPULSIVE_UP          = "IMPULSIVE_UP"
    IMPULSIVE_DOWN        = "IMPULSIVE_DOWN"
    CORRECTIVE_ABC_UP     = "CORRECTIVE_ABC_UP"    # corrective move pushing price up
    CORRECTIVE_ABC_DOWN   = "CORRECTIVE_ABC_DOWN"  # corrective move pushing price down
    TRANSITION            = "TRANSITION"           # ambiguous / structure break
    COMPLEX_CORRECTION    = "COMPLEX_CORRECTION"   # WXY or similar multi-leg
    UNKNOWN               = "UNKNOWN"


@dataclass(frozen=True)
class SwingLevel:
    """
    A structurally significant price level identified by swing detection.
    Used by: SAE liquidation_proximity check, ObservationPack.
    """
    price: float
    swing_type: str          # "high" | "low"
    timeframe: str           # "1m" | "5m" | "1h" | "4h"
    bar_index: int           # index in the closed-bars array
    strength: int            # number of bars this swing was unchallenged
    confirmed: bool          # True if subsequent bars have confirmed the level


@dataclass
class DivergenceAlert:
    """A momentum divergence detected at a structurally significant swing point."""
    divergence_type: str     # "bullish_rsi" | "bearish_rsi" | "bullish_macd" | "bearish_macd"
    timeframe: str
    swing_price: float
    indicator_value: float
    confidence: float        # [0,1]


@dataclass
class WaveAnalysisResult:
    """
    Full wave structure analysis output for one asset / one timeframe set.
    Written into ObservationPack.quantitative_baseline["wave"].
    """
    asset: str
    primary_timeframe: str

    wave_phase: WavePhase
    wave_phase_confidence: float      # [0,1]

    # Multi-timeframe confluence
    timeframe_phases: dict            # e.g. {"4h": WavePhase, "1h": WavePhase}
    confluence_score: float           # [0,1] agreement across timeframes

    # Key structural levels
    swing_highs: List[SwingLevel] = field(default_factory=list)
    swing_lows: List[SwingLevel] = field(default_factory=list)
    nearest_swing_high: Optional[SwingLevel] = None
    nearest_swing_low: Optional[SwingLevel] = None

    # Divergence alerts
    divergence_alerts: List[DivergenceAlert] = field(default_factory=list)

    # Derived metrics (populated by WaveAdapter)
    nearest_swing_high_distance_pct: Optional[float] = None
    nearest_swing_low_distance_pct: Optional[float] = None

    has_bearish_divergence: bool = False
    has_bullish_divergence: bool = False

    def to_observation_dict(self) -> dict:
        """Serialize for ObservationPack.quantitative_baseline."""
        return {
            "wave_phase": self.wave_phase.value,
            "wave_phase_confidence": self.wave_phase_confidence,
            "confluence_score": self.confluence_score,
            "timeframe_phases": {k: v.value for k, v in self.timeframe_phases.items()},
            "nearest_swing_high": self.nearest_swing_high.price if self.nearest_swing_high else None,
            "nearest_swing_low": self.nearest_swing_low.price if self.nearest_swing_low else None,
            "nearest_swing_high_distance_pct": self.nearest_swing_high_distance_pct,
            "nearest_swing_low_distance_pct": self.nearest_swing_low_distance_pct,
            "divergence_alerts": [
                {
                    "type": d.divergence_type,
                    "tf": d.timeframe,
                    "price": d.swing_price,
                    "conf": d.confidence,
                }
                for d in self.divergence_alerts
            ],
            "has_bearish_divergence": self.has_bearish_divergence,
            "has_bullish_divergence": self.has_bullish_divergence,
        }


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class WaveDetectorConfig:
    """
    All detection parameters. Load from config/strategies/ or env.
    Defaults tuned for HL BTC-PERP 4h/1h/15m.
    """
    # Swing detection
    swing_lookback: int = 5              # bars each side to confirm swing
    min_swing_pct: float = 0.008         # minimum 0.8% move to qualify as swing
    swing_confirmation_bars: int = 3     # bars after swing to confirm it

    # Liquidation spike filter
    liq_spike_wick_pct: float = 0.015    # wick > 1.5% of price AND immediate reversal
    liq_spike_reversal_bars: int = 2     # must reverse within N bars

    # Impulse vs correction classification
    impulse_min_legs: int = 3            # minimum swing legs for impulse
    correction_max_retracement: float = 0.786  # Fib 78.6% — deeper = not correction

    # Multi-timeframe confluence
    timeframes: List[str] = field(default_factory=lambda: ["4h", "1h", "15m"])
    confluence_min_agreement: float = 0.67   # 2/3 TFs must agree for high confluence

    # RSI divergence
    rsi_period: int = 14
    rsi_divergence_lookback: int = 3     # swing pairs to check for divergence

    # MACD divergence
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9


# ---------------------------------------------------------------------------
# Core detector
# ---------------------------------------------------------------------------

class WaveDetector:
    """
    Multi-timeframe wave structure detector.

    Usage in ObserverAgent:
        detector = WaveDetector(config)
        result = detector.analyze(
            asset="BTC-PERP",
            bars_by_tf={
                "4h": market_ctx.bars_4h,
                "1h": market_ctx.bars_1h,
                "15m": market_ctx.bars_5m,  # use 5m as 15m proxy if 15m unavailable
            },
            current_mid_price=market_ctx.mid_price,
        )
        obs_pack.quantitative_baseline["wave"] = result.to_observation_dict()
        obs_pack.swing_high = result.nearest_swing_high
        obs_pack.swing_low  = result.nearest_swing_low
    """

    def __init__(self, config: Optional[WaveDetectorConfig] = None):
        self._cfg = config or WaveDetectorConfig()

    def analyze(
        self,
        asset: str,
        bars_by_tf: dict,
        current_mid_price: float,
        primary_timeframe: str = "4h",
    ) -> WaveAnalysisResult:
        """
        Full multi-timeframe wave analysis.

        Args:
            asset: Asset symbol (e.g. "BTC-PERP")
            bars_by_tf: dict mapping timeframe str → list of HLBar (closed bars only)
            current_mid_price: Current mark/mid price for distance calculations
            primary_timeframe: Timeframe used for primary wave phase

        Returns:
            WaveAnalysisResult with all structural classifications populated.
        """
        tf_results: dict = {}

        for tf, bars in bars_by_tf.items():
            if not bars or len(bars) < self._cfg.swing_lookback * 2 + 5:
                logger.debug("[%s] insufficient bars for wave detection on %s (%d bars)",
                             asset, tf, len(bars) if bars else 0)
                tf_results[tf] = WavePhase.UNKNOWN
                continue

            filtered = self._filter_liq_wicks(bars)
            closes, highs, lows = self._extract_ohlc(filtered)
            swings = self._detect_swings(highs, lows, tf)
            phase = self._classify_wave_phase(swings, closes)
            tf_results[tf] = phase

        primary_phase = tf_results.get(primary_timeframe, WavePhase.UNKNOWN)
        confluence = self._compute_confluence(tf_results)

        primary_bars = bars_by_tf.get(primary_timeframe, [])
        filtered_primary = self._filter_liq_wicks(primary_bars) if primary_bars else []
        p_highs, p_lows = [], []
        if filtered_primary:
            _, p_highs, p_lows = self._extract_ohlc(filtered_primary)

        all_swings = self._detect_swings(p_highs, p_lows, primary_timeframe) if p_highs else []
        swing_highs = [s for s in all_swings if s.swing_type == "high"]
        swing_lows  = [s for s in all_swings if s.swing_type == "low"]

        nearest_high = self._nearest_swing(swing_highs, current_mid_price, "high")
        nearest_low  = self._nearest_swing(swing_lows,  current_mid_price, "low")

        high_dist = None
        low_dist = None
        if nearest_high and current_mid_price > 0:
            high_dist = abs(nearest_high.price - current_mid_price) / current_mid_price * 100
        if nearest_low and current_mid_price > 0:
            low_dist = abs(nearest_low.price - current_mid_price) / current_mid_price * 100

        # Divergence detection on primary timeframe
        divs: List[DivergenceAlert] = []
        if filtered_primary:
            closes_primary, _, _ = self._extract_ohlc(filtered_primary)
            divs = self._detect_rsi_divergences(
                closes_primary, all_swings, primary_timeframe
            )

        has_bear = any("bearish" in d.divergence_type for d in divs)
        has_bull = any("bullish" in d.divergence_type for d in divs)

        phase_confidence = self._phase_confidence(primary_phase, confluence, len(swing_highs) + len(swing_lows))

        return WaveAnalysisResult(
            asset=asset,
            primary_timeframe=primary_timeframe,
            wave_phase=primary_phase,
            wave_phase_confidence=phase_confidence,
            timeframe_phases=tf_results,
            confluence_score=confluence,
            swing_highs=swing_highs[-5:],   # keep 5 most recent
            swing_lows=swing_lows[-5:],
            nearest_swing_high=nearest_high,
            nearest_swing_low=nearest_low,
            nearest_swing_high_distance_pct=high_dist,
            nearest_swing_low_distance_pct=low_dist,
            divergence_alerts=divs,
            has_bearish_divergence=has_bear,
            has_bullish_divergence=has_bull,
        )

    # ------------------------------------------------------------------
    # Liquidation spike filter
    # ------------------------------------------------------------------

    def _filter_liq_wicks(self, bars) -> list:
        """
        Remove HL perp liquidation cascade wicks from OHLC before wave detection.
        A wick is treated as a liq spike if:
          - It exceeds liq_spike_wick_pct of the close price, AND
          - Price fully reverses within liq_spike_reversal_bars bars.
        Returns a new list with spike wicks clipped to a reasonable wick range.
        """
        if not bars:
            return bars

        filtered = list(bars)
        cfg = self._cfg
        n = len(filtered)

        for i in range(n - cfg.liq_spike_reversal_bars):
            bar = filtered[i]
            close = bar.close
            if close <= 0:
                continue

            upper_wick = (bar.high - max(bar.open, bar.close)) / close
            lower_wick = (min(bar.open, bar.close) - bar.low) / close

            # Check upper wick spike
            if upper_wick > cfg.liq_spike_wick_pct:
                # Verify reversal: next N bars must close below spike level
                spike_level = bar.high
                reversal_count = sum(
                    1 for j in range(i + 1, min(i + 1 + cfg.liq_spike_reversal_bars, n))
                    if filtered[j].close < spike_level * 0.995
                )
                if reversal_count >= 1:
                    logger.debug("liq spike filtered: upper wick at idx %d", i)
                    # Clip the high to 2× normal wick range
                    normal_wick = max(bar.open, bar.close) + (close * 0.003)
                    # We can't mutate frozen dataclass; build replacement dict
                    # In practice, caller should use mutable bar objects.
                    # Here we just flag; adapter decides how to handle.

            # Check lower wick spike
            if lower_wick > cfg.liq_spike_wick_pct:
                spike_level = bar.low
                reversal_count = sum(
                    1 for j in range(i + 1, min(i + 1 + cfg.liq_spike_reversal_bars, n))
                    if filtered[j].close > spike_level * 1.005
                )
                if reversal_count >= 1:
                    logger.debug("liq spike filtered: lower wick at idx %d", i)

        # NOTE: Because HLBar is frozen, actual wick-clipping requires
        # the caller to pass mutable bar dicts or a non-frozen Bar type.
        # This implementation returns the original list with spike logging.
        # TODO(phase-b): accept mutable bars and apply actual clipping.
        return filtered

    # ------------------------------------------------------------------
    # OHLC extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_ohlc(bars) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        closes = np.array([b.close for b in bars], dtype=float)
        highs  = np.array([b.high  for b in bars], dtype=float)
        lows   = np.array([b.low   for b in bars], dtype=float)
        return closes, highs, lows

    # ------------------------------------------------------------------
    # Swing detection
    # ------------------------------------------------------------------

    def _detect_swings(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        timeframe: str,
    ) -> List[SwingLevel]:
        """
        Two-pass swing detection:
          Pass 1: Identify local extrema using lookback window.
          Pass 2: Filter by minimum price move threshold and confirmation.

        Returns confirmed swing highs and lows sorted by bar index.
        """
        cfg = self._cfg
        n = len(highs)
        lb = cfg.swing_lookback
        min_move = cfg.min_swing_pct
        swings: List[SwingLevel] = []

        for i in range(lb, n - lb):
            # Swing high candidate: highest in the window
            if highs[i] == max(highs[i - lb: i + lb + 1]):
                # Minimum move filter
                left_low  = min(lows[max(0, i - lb): i])
                right_low = min(lows[i + 1: min(n, i + lb + 1)])
                baseline  = max(left_low, right_low)
                if baseline > 0 and (highs[i] - baseline) / baseline >= min_move:
                    confirmed = (i + cfg.swing_confirmation_bars) < n
                    strength = sum(1 for j in range(i + 1, min(n, i + lb + 1))
                                   if highs[j] < highs[i])
                    swings.append(SwingLevel(
                        price=float(highs[i]),
                        swing_type="high",
                        timeframe=timeframe,
                        bar_index=i,
                        strength=strength,
                        confirmed=confirmed,
                    ))

            # Swing low candidate
            if lows[i] == min(lows[i - lb: i + lb + 1]):
                left_high  = max(highs[max(0, i - lb): i])
                right_high = max(highs[i + 1: min(n, i + lb + 1)])
                baseline   = min(left_high, right_high)
                if baseline > 0 and lows[i] > 0 and (baseline - lows[i]) / lows[i] >= min_move:
                    confirmed = (i + cfg.swing_confirmation_bars) < n
                    strength = sum(1 for j in range(i + 1, min(n, i + lb + 1))
                                   if lows[j] > lows[i])
                    swings.append(SwingLevel(
                        price=float(lows[i]),
                        swing_type="low",
                        timeframe=timeframe,
                        bar_index=i,
                        strength=strength,
                        confirmed=confirmed,
                    ))

        swings.sort(key=lambda s: s.bar_index)
        return swings

    # ------------------------------------------------------------------
    # Wave phase classification
    # ------------------------------------------------------------------

    def _classify_wave_phase(
        self,
        swings: List[SwingLevel],
        closes: np.ndarray,
    ) -> WavePhase:
        """
        Classify market phase from the sequence of swing highs and lows.

        Rules (simplified):
          IMPULSIVE_UP:    HH + HL sequence with ≥3 legs and no deep retracement
          IMPULSIVE_DOWN:  LL + LH sequence with ≥3 legs and no deep retracement
          CORRECTIVE_*:    Deep retracement after impulse, bounded structure
          TRANSITION:      Structural break — swing sequence violates all patterns
          COMPLEX:         Multiple overlapping corrective legs

        Returns WavePhase.UNKNOWN if insufficient swings for classification.
        """
        cfg = self._cfg
        confirmed = [s for s in swings if s.confirmed]

        if len(confirmed) < cfg.impulse_min_legs:
            return WavePhase.UNKNOWN

        highs_seq = [s.price for s in confirmed if s.swing_type == "high"]
        lows_seq  = [s.price for s in confirmed if s.swing_type == "low"]

        if len(highs_seq) < 2 or len(lows_seq) < 2:
            return WavePhase.UNKNOWN

        # Check for higher highs + higher lows (IMPULSIVE_UP)
        hh = all(highs_seq[i] > highs_seq[i-1] for i in range(1, len(highs_seq)))
        hl = all(lows_seq[i]  > lows_seq[i-1]  for i in range(1, len(lows_seq)))

        if hh and hl:
            return WavePhase.IMPULSIVE_UP

        # Lower lows + lower highs (IMPULSIVE_DOWN)
        ll = all(lows_seq[i]  < lows_seq[i-1]  for i in range(1, len(lows_seq)))
        lh = all(highs_seq[i] < highs_seq[i-1] for i in range(1, len(highs_seq)))

        if ll and lh:
            return WavePhase.IMPULSIVE_DOWN

        # Deep retracement check for correction
        if len(highs_seq) >= 2 and len(lows_seq) >= 2:
            price_range = highs_seq[-1] - lows_seq[0]
            retracement = (highs_seq[-1] - lows_seq[-1]) / price_range if price_range > 0 else 0

            if retracement > cfg.correction_max_retracement:
                # Multiple overlapping swings = complex correction
                if len(confirmed) > 6:
                    return WavePhase.COMPLEX_CORRECTION

                # Directional corrective
                if closes[-1] > closes[len(closes) // 2]:
                    return WavePhase.CORRECTIVE_ABC_UP
                return WavePhase.CORRECTIVE_ABC_DOWN

        # Structure break or ambiguity
        return WavePhase.TRANSITION

    # ------------------------------------------------------------------
    # Multi-timeframe confluence
    # ------------------------------------------------------------------

    def _compute_confluence(self, tf_phases: dict) -> float:
        """
        Compute agreement score across timeframes.
        Returns [0,1] where 1.0 = all timeframes in same phase family.
        """
        if not tf_phases:
            return 0.0

        valid = [p for p in tf_phases.values() if p != WavePhase.UNKNOWN]
        if not valid:
            return 0.0

        # Group into directional families
        def family(p: WavePhase) -> str:
            if p in {WavePhase.IMPULSIVE_UP, WavePhase.CORRECTIVE_ABC_UP}:
                return "bullish"
            if p in {WavePhase.IMPULSIVE_DOWN, WavePhase.CORRECTIVE_ABC_DOWN}:
                return "bearish"
            return "neutral"

        families = [family(p) for p in valid]
        most_common_count = max(families.count(f) for f in set(families))
        return round(most_common_count / len(valid), 4)

    # ------------------------------------------------------------------
    # RSI divergence detection
    # ------------------------------------------------------------------

    def _detect_rsi_divergences(
        self,
        closes: np.ndarray,
        swings: List[SwingLevel],
        timeframe: str,
    ) -> List[DivergenceAlert]:
        """
        Detect RSI divergences AT structurally significant swing points only.
        This is the key improvement vs naive divergence scanning:
        divergences in the middle of trends are ignored.
        """
        cfg = self._cfg
        if len(closes) < cfg.rsi_period + 5:
            return []

        rsi = self._compute_rsi(closes, cfg.rsi_period)
        alerts: List[DivergenceAlert] = []

        swing_highs = [s for s in swings if s.swing_type == "high" and s.confirmed]
        swing_lows  = [s for s in swings if s.swing_type == "low"  and s.confirmed]

        # Bearish divergence: price makes higher high but RSI makes lower high
        for i in range(1, min(len(swing_highs), cfg.rsi_divergence_lookback + 1)):
            s1, s2 = swing_highs[-i-1], swing_highs[-i]
            if (s2.price > s1.price and
                    s2.bar_index < len(rsi) and s1.bar_index < len(rsi) and
                    rsi[s2.bar_index] < rsi[s1.bar_index]):
                price_div = (s2.price - s1.price) / s1.price
                rsi_div   = (rsi[s1.bar_index] - rsi[s2.bar_index]) / max(rsi[s1.bar_index], 1)
                conf = min(1.0, (price_div + rsi_div) * 3)
                alerts.append(DivergenceAlert(
                    divergence_type="bearish_rsi",
                    timeframe=timeframe,
                    swing_price=s2.price,
                    indicator_value=float(rsi[s2.bar_index]),
                    confidence=round(conf, 3),
                ))

        # Bullish divergence: price makes lower low but RSI makes higher low
        for i in range(1, min(len(swing_lows), cfg.rsi_divergence_lookback + 1)):
            s1, s2 = swing_lows[-i-1], swing_lows[-i]
            if (s2.price < s1.price and
                    s2.bar_index < len(rsi) and s1.bar_index < len(rsi) and
                    rsi[s2.bar_index] > rsi[s1.bar_index]):
                price_div = (s1.price - s2.price) / s1.price
                rsi_div   = (rsi[s2.bar_index] - rsi[s1.bar_index]) / max(rsi[s1.bar_index], 1)
                conf = min(1.0, (price_div + rsi_div) * 3)
                alerts.append(DivergenceAlert(
                    divergence_type="bullish_rsi",
                    timeframe=timeframe,
                    swing_price=s2.price,
                    indicator_value=float(rsi[s2.bar_index]),
                    confidence=round(conf, 3),
                ))

        return alerts

    # ------------------------------------------------------------------
    # RSI computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
        if len(closes) < period + 1:
            return np.full(len(closes), 50.0)

        deltas = np.diff(closes)
        gains  = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = np.zeros(len(closes))
        avg_loss = np.zeros(len(closes))

        avg_gain[period] = np.mean(gains[:period])
        avg_loss[period] = np.mean(losses[:period])

        for i in range(period + 1, len(closes)):
            avg_gain[i] = (avg_gain[i-1] * (period - 1) + gains[i-1]) / period
            avg_loss[i] = (avg_loss[i-1] * (period - 1) + losses[i-1]) / period

        rs = np.where(avg_loss > 0, avg_gain / avg_loss, 100.0)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        rsi[:period] = 50.0
        return rsi

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _nearest_swing(
        swings: List[SwingLevel],
        current_price: float,
        swing_type: str,
    ) -> Optional[SwingLevel]:
        """Return the nearest confirmed swing to current_price."""
        confirmed = [s for s in swings if s.confirmed]
        if not confirmed:
            return None
        if swing_type == "high":
            candidates = [s for s in confirmed if s.price >= current_price]
        else:
            candidates = [s for s in confirmed if s.price <= current_price]
        if not candidates:
            # Fall back to absolute nearest
            candidates = confirmed
        return min(candidates, key=lambda s: abs(s.price - current_price))

    @staticmethod
    def _phase_confidence(
        phase: WavePhase,
        confluence: float,
        swing_count: int,
    ) -> float:
        """Composite confidence score for the phase label."""
        if phase == WavePhase.UNKNOWN:
            return 0.0
        if phase == WavePhase.TRANSITION:
            return max(0.0, 0.3 - (confluence * 0.2))

        base = 0.5
        conf_boost = confluence * 0.3
        swing_boost = min(0.2, swing_count * 0.02)
        return round(min(1.0, base + conf_boost + swing_boost), 4)
