"""
apps/quant/signals/wave_adapter.py

Bridges WaveDetector output to the trading firm's typed schemas:
  - ObservationPack.quantitative_baseline["wave"]
  - ObservationPack fields: swing_high, swing_low
  - QZRegime mapping (via regime_mapper.py)
  - SAE input enrichment: swing_failure_near_liq flag

Also exposes module-level convenience function analyze_wave() used by
ObserverAgent to avoid boilerplate.

Architecture constraints:
  - This module is read-only with respect to the trading pipeline.
  - It NEVER emits TradeIntent, ExecutionApproval, or SAE decisions.
  - It NEVER modifies ObservationPack directly; it returns typed dicts
    that ObserverAgent merges in.
  - All wave analysis runs on CLOSED bars. Callers must enforce this.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from apps.quant.signals.wave_detector import (
    WaveAnalysisResult,
    WaveDetector,
    WaveDetectorConfig,
    WavePhase,
)
from apps.quant.regimes.regime_mapper import QZRegime, RegimeMappingResult, RegimeMapper

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Wave → QZRegime mapping
# ---------------------------------------------------------------------------

# Mapping from (wave_phase, confluence_high) tuples to QZRegime labels.
# confluence_high = True when confluence_score >= CONFLUENCE_HIGH_THRESHOLD.
CONFLUENCE_HIGH_THRESHOLD = 0.67

_WAVE_PHASE_TO_QZ: dict = {
    # High confluence impulsive = clean trending regime
    (WavePhase.IMPULSIVE_UP,        True):  QZRegime.TREND_UP_LOW_VOL,
    (WavePhase.IMPULSIVE_UP,        False): QZRegime.TREND_UP_HIGH_VOL,
    (WavePhase.IMPULSIVE_DOWN,      True):  QZRegime.TREND_DOWN_LOW_VOL,
    (WavePhase.IMPULSIVE_DOWN,      False): QZRegime.TREND_DOWN_HIGH_VOL,

    # Corrective structures = range-like
    (WavePhase.CORRECTIVE_ABC_UP,   True):  QZRegime.RANGE_LOW_VOL,
    (WavePhase.CORRECTIVE_ABC_UP,   False): QZRegime.RANGE_HIGH_VOL,
    (WavePhase.CORRECTIVE_ABC_DOWN, True):  QZRegime.RANGE_LOW_VOL,
    (WavePhase.CORRECTIVE_ABC_DOWN, False): QZRegime.RANGE_HIGH_VOL,

    # Complex corrections = high vol range / structural risk
    (WavePhase.COMPLEX_CORRECTION,  True):  QZRegime.RANGE_HIGH_VOL,
    (WavePhase.COMPLEX_CORRECTION,  False): QZRegime.RANGE_HIGH_VOL,

    # Structural break = event risk
    (WavePhase.TRANSITION,          True):  QZRegime.EVENT_BREAKOUT,
    (WavePhase.TRANSITION,          False): QZRegime.EVENT_BREAKOUT,

    # Unknown
    (WavePhase.UNKNOWN,             True):  QZRegime.UNKNOWN,
    (WavePhase.UNKNOWN,             False): QZRegime.UNKNOWN,
}


def wave_phase_to_qz_regime(
    phase: WavePhase,
    confluence_score: float,
) -> QZRegime:
    """
    Map WavePhase + confluence score to a QZRegime label.
    Used by qz_regime_classifier.py as one input signal.
    """
    high_conf = confluence_score >= CONFLUENCE_HIGH_THRESHOLD
    qz = _WAVE_PHASE_TO_QZ.get((phase, high_conf))
    if qz is None:
        logger.warning("wave_adapter: unmapped phase=%s conf_high=%s", phase, high_conf)
        qz = QZRegime.UNKNOWN
    return qz


# ---------------------------------------------------------------------------
# SAE enrichment output
# ---------------------------------------------------------------------------

@dataclass
class WaveSAEInputs:
    """
    Derived inputs from wave analysis for SAE policy checks.
    Passed alongside standard SAE inputs; SAE treats these as advisory.

    near_swing_failure:
        True when current price is within swing_failure_distance_pct of
        the nearest confirmed swing low (for longs) or swing high (for shorts).
        A swing failure at this level would signal structural breakdown.
    """
    near_swing_failure: bool
    swing_failure_price: Optional[float]
    swing_failure_distance_pct: Optional[float]
    has_bearish_divergence: bool
    has_bullish_divergence: bool
    wave_confluence_score: float


# ---------------------------------------------------------------------------
# Full adapter output
# ---------------------------------------------------------------------------

@dataclass
class WaveAdapterOutput:
    """
    Unified output from the wave adapter, ready for injection into:
      - ObservationPack.quantitative_baseline["wave"]
      - ObservationPack.swing_high / .swing_low
      - RegimeMappingResult (via qz_regime)
      - WaveSAEInputs (for SAE enrichment)
    """
    wave_result: WaveAnalysisResult
    qz_regime: QZRegime
    regime_mapping: RegimeMappingResult
    sae_inputs: WaveSAEInputs
    observation_dict: dict


# ---------------------------------------------------------------------------
# Main adapter class
# ---------------------------------------------------------------------------

class WaveAdapter:
    """
    Orchestrates WaveDetector → regime mapping → SAE enrichment.

    Usage in ObserverAgent:
        adapter = WaveAdapter()
        output = adapter.analyze(
            asset="BTC-PERP",
            bars_by_tf={"4h": ctx.bars_4h, "1h": ctx.bars_1h},
            current_mid_price=ctx.mid_price,
        )

        # Inject into ObservationPack
        obs_pack.quantitative_baseline["wave"] = output.observation_dict
        obs_pack.swing_high = output.wave_result.nearest_swing_high
        obs_pack.swing_low  = output.wave_result.nearest_swing_low

        # Enrich regime classification
        if output.qz_regime != QZRegime.UNKNOWN:
            # regime classifier can override or blend with wave-derived regime
            pass

        # SAE enrichment
        sae_extras = output.sae_inputs
    """

    SWING_FAILURE_THRESHOLD_PCT = 0.8  # within 0.8% of swing low/high

    def __init__(
        self,
        detector_config: Optional[WaveDetectorConfig] = None,
        regime_mapper: Optional[RegimeMapper] = None,
    ):
        self._detector = WaveDetector(detector_config)
        self._mapper   = regime_mapper or RegimeMapper()

    def analyze(
        self,
        asset: str,
        bars_by_tf: dict,
        current_mid_price: float,
        primary_timeframe: str = "4h",
        direction_for_sae: str = "LONG",  # "LONG" | "SHORT" — pending trade direction
    ) -> WaveAdapterOutput:
        """
        Full wave analysis pipeline.

        Args:
            asset: Asset symbol
            bars_by_tf: Closed bars by timeframe
            current_mid_price: Current mid price
            primary_timeframe: Primary timeframe for wave phase
            direction_for_sae: Intended trade direction for swing failure check

        Returns:
            WaveAdapterOutput with all downstream-typed fields populated.
        """
        # 1. Run wave detection
        wave_result = self._detector.analyze(
            asset=asset,
            bars_by_tf=bars_by_tf,
            current_mid_price=current_mid_price,
            primary_timeframe=primary_timeframe,
        )

        # 2. Map to QZRegime
        qz = wave_phase_to_qz_regime(
            wave_result.wave_phase,
            wave_result.confluence_score,
        )

        # 3. Map QZRegime → canonical MarketRegime
        regime_mapping = self._mapper.map(qz, wave_result.wave_phase_confidence)

        # 4. Build SAE enrichment inputs
        sae_inputs = self._build_sae_inputs(
            wave_result,
            current_mid_price,
            direction_for_sae,
        )

        # 5. Build observation dict for ObservationPack
        obs_dict = wave_result.to_observation_dict()
        obs_dict["qz_regime_from_wave"] = qz.value
        obs_dict["market_regime_from_wave"] = regime_mapping.market_regime.value
        obs_dict["sae_near_swing_failure"] = sae_inputs.near_swing_failure

        return WaveAdapterOutput(
            wave_result=wave_result,
            qz_regime=qz,
            regime_mapping=regime_mapping,
            sae_inputs=sae_inputs,
            observation_dict=obs_dict,
        )

    def _build_sae_inputs(
        self,
        result: WaveAnalysisResult,
        current_price: float,
        direction: str,
    ) -> WaveSAEInputs:
        """
        Derive SAE-relevant flags from wave analysis.
        For longs: proximity to swing low is the failure risk.
        For shorts: proximity to swing high is the failure risk.
        """
        threshold = self.SWING_FAILURE_THRESHOLD_PCT
        near_failure = False
        failure_price: Optional[float] = None
        failure_dist: Optional[float] = None

        if direction == "LONG" and result.nearest_swing_low:
            dist = result.nearest_swing_low_distance_pct
            if dist is not None and dist < threshold:
                near_failure = True
                failure_price = result.nearest_swing_low.price
                failure_dist  = dist

        elif direction == "SHORT" and result.nearest_swing_high:
            dist = result.nearest_swing_high_distance_pct
            if dist is not None and dist < threshold:
                near_failure = True
                failure_price = result.nearest_swing_high.price
                failure_dist  = dist

        return WaveSAEInputs(
            near_swing_failure=near_failure,
            swing_failure_price=failure_price,
            swing_failure_distance_pct=failure_dist,
            has_bearish_divergence=result.has_bearish_divergence,
            has_bullish_divergence=result.has_bullish_divergence,
            wave_confluence_score=result.confluence_score,
        )


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_adapter = WaveAdapter()


def analyze_wave(
    asset: str,
    bars_by_tf: dict,
    current_mid_price: float,
    primary_timeframe: str = "4h",
    direction_for_sae: str = "LONG",
) -> WaveAdapterOutput:
    """
    Module-level convenience wrapper using the default adapter config.
    Suitable for ObserverAgent one-liner usage.
    """
    return _default_adapter.analyze(
        asset=asset,
        bars_by_tf=bars_by_tf,
        current_mid_price=current_mid_price,
        primary_timeframe=primary_timeframe,
        direction_for_sae=direction_for_sae,
    )
