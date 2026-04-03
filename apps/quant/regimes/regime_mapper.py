"""
apps/quant/regimes/regime_mapper.py

Quant-Zero regime label → canonical MarketRegime enum mapping.

Design principle:
  Quant-Zero produces fine-grained HL-specific regime labels.
  This module maps them to the MarketRegime enum defined in
  proto/common.proto and used throughout the trading firm's
  agent pipeline, SAE policy, and DecisionTrace.

  The MarketRegime enum is an OPERATIONAL enum (risk-first),
  not a descriptive one. High-volatility regimes override
  directional labels because risk control dominates direction.

  Both labels are preserved in ObservationPack so that:
    - Agents reason with richer context (qz_regime).
    - SAE and FundManager operate on the canonical enum (market_regime).
    - Jobs/ablations can analyze by fine-grained regime retroactively.

Proto enum reference (common.proto):
  REGIME_UNSPECIFIED = 0
  TREND_UP           = 1
  TREND_DOWN         = 2
  RANGE              = 3
  EVENT_RISK         = 4
  HIGH_VOL           = 5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Quant-Zero fine-grained regime labels (HL perp specific)
# ---------------------------------------------------------------------------

class QZRegime(str, Enum):
    """
    Fine-grained regime labels produced by qz_regime_classifier.py.
    Persist in ObservationPack.qz_regime for analysis and backtests.
    Do NOT use directly in SAE policy or FundManager logic.
    """
    TREND_UP_LOW_VOL       = "trend_up_low_vol"
    TREND_UP_HIGH_VOL      = "trend_up_high_vol"
    TREND_DOWN_LOW_VOL     = "trend_down_low_vol"
    TREND_DOWN_HIGH_VOL    = "trend_down_high_vol"
    RANGE_LOW_VOL          = "range_low_vol"
    RANGE_HIGH_VOL         = "range_high_vol"
    EVENT_BREAKOUT         = "event_breakout"
    LIQ_CASCADE            = "liquidation_cascade_risk"
    FUNDING_CROWDED_LONG   = "funding_crowded_long"
    FUNDING_CROWDED_SHORT  = "funding_crowded_short"
    UNKNOWN                = "unknown"


# ---------------------------------------------------------------------------
# Canonical MarketRegime (mirrors proto/common.proto)
# ---------------------------------------------------------------------------

class MarketRegime(str, Enum):
    """
    Canonical operational regime used by agents, SAE, FundManager.
    Must stay in sync with MarketRegime enum in proto/common.proto.
    """
    UNSPECIFIED = "REGIME_UNSPECIFIED"
    TREND_UP    = "TREND_UP"
    TREND_DOWN  = "TREND_DOWN"
    RANGE       = "RANGE"
    EVENT_RISK  = "EVENT_RISK"
    HIGH_VOL    = "HIGH_VOL"


# ---------------------------------------------------------------------------
# Mapping table — documented rationale for each entry
# ---------------------------------------------------------------------------

_QZ_TO_MARKET_REGIME: dict[QZRegime, MarketRegime] = {
    # Directional trend, low volatility → preserve direction
    QZRegime.TREND_UP_LOW_VOL: MarketRegime.TREND_UP,
    QZRegime.TREND_DOWN_LOW_VOL: MarketRegime.TREND_DOWN,

    # Directional trend, HIGH volatility → risk control dominates
    # Rationale: execution risk, liquidation proximity, and leverage carry
    # costs are all amplified in high-vol perp environments. The system
    # should compress size and tighten stops rather than lean into direction.
    QZRegime.TREND_UP_HIGH_VOL: MarketRegime.HIGH_VOL,
    QZRegime.TREND_DOWN_HIGH_VOL: MarketRegime.HIGH_VOL,

    # Range regimes
    QZRegime.RANGE_LOW_VOL: MarketRegime.RANGE,
    QZRegime.RANGE_HIGH_VOL: MarketRegime.HIGH_VOL,  # range but dangerous

    # Event / structural risk
    QZRegime.EVENT_BREAKOUT: MarketRegime.EVENT_RISK,
    QZRegime.LIQ_CASCADE: MarketRegime.EVENT_RISK,

    # Funding-crowded regimes
    # Rationale: extreme funding crowding is a structural risk event, not just
    # a carry cost. Mark-to-market blow-offs can happen rapidly when funding
    # attracts too much leverage on one side. Treat as EVENT_RISK.
    QZRegime.FUNDING_CROWDED_LONG: MarketRegime.EVENT_RISK,
    QZRegime.FUNDING_CROWDED_SHORT: MarketRegime.EVENT_RISK,

    # Unknown / unclassified → safe fallback
    QZRegime.UNKNOWN: MarketRegime.UNSPECIFIED,
}


# ---------------------------------------------------------------------------
# Mapping result
# ---------------------------------------------------------------------------

@dataclass
class RegimeMappingResult:
    """
    Full regime classification result.
    Written into ObservationPack and DecisionTrace.
    """
    qz_regime: QZRegime
    market_regime: MarketRegime
    regime_confidence: float        # [0,1] from classifier
    high_vol_override: bool         # True if direction was overridden to HIGH_VOL
    funding_crowded: bool           # True if funding threshold was exceeded

    def to_dict(self) -> dict:
        return {
            "qz_regime": self.qz_regime.value,
            "market_regime": self.market_regime.value,
            "regime_confidence": self.regime_confidence,
            "high_vol_override": self.high_vol_override,
            "funding_crowded": self.funding_crowded,
        }


# ---------------------------------------------------------------------------
# Mapper
# ---------------------------------------------------------------------------

class RegimeMapper:
    """
    Maps QZRegime fine-grained labels to MarketRegime operational enum.

    Used by:
      - apps/agents/observer/observer_agent.py
      - apps/quant/regimes/qz_regime_classifier.py (calls map() on its output)
      - apps/jobs/backtest_runner.py (regime-conditioned performance slicing)
    """

    def map(
        self,
        qz_regime: QZRegime,
        regime_confidence: float = 1.0,
    ) -> RegimeMappingResult:
        """
        Map a QZRegime to MarketRegime with override flags.

        Args:
            qz_regime: Fine-grained regime from classifier.
            regime_confidence: Classifier confidence score [0,1].

        Returns:
            RegimeMappingResult with canonical market_regime and audit flags.
        """
        qz = qz_regime if isinstance(qz_regime, QZRegime) else QZRegime(qz_regime)
        market = _QZ_TO_MARKET_REGIME.get(qz, MarketRegime.UNSPECIFIED)

        high_vol_override = (
            qz in {QZRegime.TREND_UP_HIGH_VOL, QZRegime.TREND_DOWN_HIGH_VOL, QZRegime.RANGE_HIGH_VOL}
        )
        funding_crowded = qz in {QZRegime.FUNDING_CROWDED_LONG, QZRegime.FUNDING_CROWDED_SHORT}

        result = RegimeMappingResult(
            qz_regime=qz,
            market_regime=market,
            regime_confidence=round(max(0.0, min(1.0, regime_confidence)), 4),
            high_vol_override=high_vol_override,
            funding_crowded=funding_crowded,
        )

        logger.debug(
            "regime_mapper: qz=%s → market=%s conf=%.3f override=%s funding=%s",
            qz.value, market.value, regime_confidence,
            high_vol_override, funding_crowded,
        )

        return result

    def map_from_string(
        self,
        qz_label: str,
        regime_confidence: float = 1.0,
    ) -> RegimeMappingResult:
        """
        Convenience method for string-labeled inputs (e.g. from JSON).
        Falls back to QZRegime.UNKNOWN on unrecognized labels.
        """
        try:
            qz = QZRegime(qz_label)
        except ValueError:
            logger.warning("regime_mapper: unknown QZ label '%s' — defaulting to UNKNOWN", qz_label)
            qz = QZRegime.UNKNOWN
        return self.map(qz, regime_confidence)

    @staticmethod
    def all_mappings() -> dict:
        """Return the full mapping table for documentation and test validation."""
        return {k.value: v.value for k, v in _QZ_TO_MARKET_REGIME.items()}


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_mapper = RegimeMapper()


def map_regime(qz_regime: QZRegime, confidence: float = 1.0) -> RegimeMappingResult:
    """Module-level convenience wrapper."""
    return _default_mapper.map(qz_regime, confidence)


def map_regime_from_string(label: str, confidence: float = 1.0) -> RegimeMappingResult:
    """Module-level convenience wrapper for string labels."""
    return _default_mapper.map_from_string(label, confidence)
