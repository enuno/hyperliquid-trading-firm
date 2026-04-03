"""
apps/quant/sizing/kelly_sizing_service.py

Fractional Kelly position sizing service for HL perp strategies.

CRITICAL ARCHITECTURE RULE:
  win_prob and payoff_ratio MUST come from validated historical
  out-of-sample estimates (apps/jobs/backtest_runner.py output),
  NOT from raw LLM confidence scores.

  Raw LLM confidence (debate_outcome.consensus_strength,
  arbitrator_verdict.arbitrator_confidence) is accepted ONLY as a
  signal_quality multiplier on the final adjusted fraction.

  Kelly output flows into TradeIntent.target_notional_pct as a
  suggestion; FundManager and SAE retain override authority.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Inputs / Outputs
# ---------------------------------------------------------------------------

@dataclass
class KellyInputs:
    """
    All inputs required to compute a Kelly-adjusted position size.

    win_prob:       Historical win rate for this (strategy, asset, regime, direction) bucket.
                    Minimum 30 OOS trades before this is considered valid.
    payoff_ratio:   Historical avg_win / avg_loss for same bucket.
    signal_quality: Composite [0,1] derived from:
                      - debate_outcome.consensus_strength
                      - arbitrator_verdict.arbitrator_confidence
                      - analyst agreement score
                    NOT the raw LLM confidence.
    funding_rate_8h: Current 8-hour funding rate (decimal, e.g. 0.0001 = 0.01%).
    realized_vol_z: Realized vol z-score vs 30d rolling mean.
    liq_distance_pct: Distance to nearest dense liquidation cluster (%).
                      Positive = cluster is below mid (threat to longs).
    sample_count:   Number of OOS trades used to estimate win_prob / payoff_ratio.
                    Sizing is suppressed below MIN_SAMPLE_COUNT.
    """
    win_prob: float
    payoff_ratio: float
    signal_quality: float
    funding_rate_8h: float
    realized_vol_z: float
    liq_distance_pct: float
    sample_count: int = 0
    direction: str = "LONG"  # "LONG" | "SHORT"


@dataclass
class KellyOutput:
    """
    Full audit record of a Kelly sizing computation.
    Written into TradeIntent and DecisionTrace.
    """
    raw_kelly: float
    fractional_kelly: float
    adjusted_fraction: float
    suggested_notional_pct: float
    sizing_valid: bool
    reasons: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "raw_kelly": self.raw_kelly,
            "fractional_kelly": self.fractional_kelly,
            "adjusted_fraction": self.adjusted_fraction,
            "suggested_notional_pct": self.suggested_notional_pct,
            "sizing_valid": self.sizing_valid,
            "reasons": self.reasons,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class KellyConfig:
    """
    Loaded from config/strategies/ or environment.
    All thresholds are conservative by design; override via config files.
    """
    kelly_fraction: float = 0.25          # quarter-Kelly default
    max_notional_pct: float = 0.10        # hard cap regardless of Kelly output
    min_notional_pct: float = 0.005       # floor — if Kelly < this, emit FLAT
    min_sample_count: int = 30            # minimum OOS trades to trust estimates

    # Penalty thresholds
    signal_quality_threshold: float = 0.60   # below → 50% size
    funding_long_reduce_1: float = 0.001     # 0.1% per 8h → 25% reduction
    funding_long_reduce_2: float = 0.002     # 0.2% per 8h → 50% reduction
    high_vol_z_threshold: float = 2.0        # realized vol z > 2 → 50% reduction
    liq_cluster_distance_threshold_pct: float = 1.5   # within 1.5% → 50% reduction


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class KellySizingService:
    """
    Computes a Kelly-adjusted, safety-penalized position size.

    Usage in trader_agent.py:
        sizer = KellySizingService(config)
        kelly_out = sizer.compute(KellyInputs(
            win_prob=historical_stats.win_rate,
            payoff_ratio=historical_stats.payoff_ratio,
            signal_quality=composite_signal_quality(debate_outcome, arbitrator_verdict),
            funding_rate_8h=market_ctx.funding.rate_8h,
            realized_vol_z=compute_vol_zscore(market_ctx.bars_1h),
            liq_distance_pct=nearest_liq_cluster_distance(market_ctx),
            sample_count=historical_stats.sample_count,
            direction=trade_intent.action,
        ))
        trade_intent.target_notional_pct = kelly_out.suggested_notional_pct
        trade_intent.kelly_output = kelly_out.to_dict()
    """

    def __init__(self, config: Optional[KellyConfig] = None):
        self._cfg = config or KellyConfig()

    def compute(self, x: KellyInputs) -> KellyOutput:
        reasons: list[str] = []
        metadata: dict = {}
        cfg = self._cfg

        # ------------------------------------------------------------------
        # 1. Sample count guard — suppress sizing if insufficient OOS history
        # ------------------------------------------------------------------
        if x.sample_count < cfg.min_sample_count:
            logger.warning(
                "kelly: insufficient sample_count=%d (min=%d) — suppressing",
                x.sample_count, cfg.min_sample_count,
            )
            reasons.append(f"insufficient_sample_count:{x.sample_count}")
            return KellyOutput(
                raw_kelly=0.0,
                fractional_kelly=0.0,
                adjusted_fraction=0.0,
                suggested_notional_pct=0.0,
                sizing_valid=False,
                reasons=reasons,
                metadata={"sample_count": x.sample_count},
            )

        # ------------------------------------------------------------------
        # 2. Raw Kelly criterion
        #    f* = (b*p - (1-p)) / b
        #    where b = payoff_ratio, p = win_probability
        # ------------------------------------------------------------------
        b = max(x.payoff_ratio, 0.001)
        p = min(max(x.win_prob, 0.001), 0.999)
        raw_kelly = ((b * p) - (1.0 - p)) / b

        metadata["b"] = b
        metadata["p"] = p
        metadata["raw_kelly"] = raw_kelly

        # ------------------------------------------------------------------
        # 3. Apply Kelly fraction (default quarter-Kelly for safety)
        # ------------------------------------------------------------------
        fractional = max(raw_kelly, 0.0) * cfg.kelly_fraction

        # ------------------------------------------------------------------
        # 4. Penalty adjustments — multiplicative, applied sequentially
        # ------------------------------------------------------------------
        adj = fractional

        if x.signal_quality < cfg.signal_quality_threshold:
            adj *= 0.5
            reasons.append(f"low_signal_quality:{x.signal_quality:.3f}")

        if x.direction == "LONG":
            if x.funding_rate_8h > cfg.funding_long_reduce_2:
                adj *= 0.5
                reasons.append(f"funding_crowded_long_severe:{x.funding_rate_8h:.5f}")
            elif x.funding_rate_8h > cfg.funding_long_reduce_1:
                adj *= 0.75
                reasons.append(f"funding_crowded_long_moderate:{x.funding_rate_8h:.5f}")

        if x.realized_vol_z > cfg.high_vol_z_threshold:
            adj *= 0.5
            reasons.append(f"high_vol_regime:{x.realized_vol_z:.2f}")

        if 0.0 < x.liq_distance_pct < cfg.liq_cluster_distance_threshold_pct:
            adj *= 0.5
            reasons.append(f"near_liq_cluster:{x.liq_distance_pct:.2f}%")

        # ------------------------------------------------------------------
        # 5. Hard cap at max_notional_pct
        # ------------------------------------------------------------------
        adj = min(adj, cfg.max_notional_pct)

        # ------------------------------------------------------------------
        # 6. Floor — if Kelly suggests negligible size, emit FLAT signal
        # ------------------------------------------------------------------
        sizing_valid = adj >= cfg.min_notional_pct
        if not sizing_valid:
            reasons.append(f"below_min_notional_floor:{adj:.5f}")
            adj = 0.0

        logger.debug(
            "kelly: p=%.3f b=%.3f raw=%.4f frac=%.4f adj=%.4f valid=%s reasons=%s",
            p, b, raw_kelly, fractional, adj, sizing_valid, reasons,
        )

        return KellyOutput(
            raw_kelly=round(raw_kelly, 6),
            fractional_kelly=round(fractional, 6),
            adjusted_fraction=round(adj, 6),
            suggested_notional_pct=round(adj, 6),
            sizing_valid=sizing_valid,
            reasons=reasons,
            metadata=metadata,
        )

    def compute_from_consensus(
        self,
        consensus_strength: float,
        arbitrator_confidence: float,
        analyst_agreement: float,
    ) -> float:
        """
        Utility: derive signal_quality from available debate/arbitrator outputs.
        Result is a [0,1] composite for KellyInputs.signal_quality.

        Weights are configurable but default to equal thirds.
        Does NOT compute Kelly directly — pass result into KellyInputs.
        """
        w = [0.40, 0.35, 0.25]
        score = (
            w[0] * max(0.0, min(1.0, consensus_strength))
            + w[1] * max(0.0, min(1.0, arbitrator_confidence))
            + w[2] * max(0.0, min(1.0, analyst_agreement))
        )
        return round(score, 4)
