"""IntelSnapshot schema — normalized intelligence payload from IntelliClaw.

All analysts (sentiment, news, onchain, fundamental) consume IntelSnapshot
as their primary upstream data contract.  Raw IntelliClaw JSON is deserialised
into these dataclasses via IntelSnapshot.from_dict().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

# ---------------------------------------------------------------------------
# Primitive labels
# ---------------------------------------------------------------------------

SentimentLabel = Literal["bullish", "bearish", "mixed", "neutral"]
ImportanceLabel = Literal["low", "medium", "high", "critical"]
RegimeLabel = Literal["risk-on", "risk-off", "neutral", "unknown"]


# ---------------------------------------------------------------------------
# Sub-schemas
# ---------------------------------------------------------------------------

@dataclass
class IntelHeadline:
    """A single scored headline from any news / social source."""

    source: str                    # e.g. "Reuters", "CoinDesk", "X"
    title: str
    url: str
    published_at: str              # ISO-8601 UTC string
    sentiment: SentimentLabel
    importance: ImportanceLabel
    summary: Optional[str] = None  # IntelliClaw 1-sentence summary if available
    tags: List[str] = field(default_factory=list)  # e.g. ["regulation", "ETF"]

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "IntelHeadline":
        return cls(
            source=d["source"],
            title=d["title"],
            url=d["url"],
            published_at=d["published_at"],
            sentiment=d["sentiment"],
            importance=d.get("importance", "medium"),
            summary=d.get("summary"),
            tags=d.get("tags", []),
        )


@dataclass
class IntelOnChain:
    """Aggregated on-chain metrics for the snapshot window."""

    net_flows_usd: float                    # positive = net inflow to exchanges
    whale_tx_count: int                     # txs > $1 M in window
    exchange_reserves_change_pct: float     # % change in CEX reserve
    active_addresses_change_pct: float = 0.0
    miner_outflow_usd: float = 0.0
    funding_rate: Optional[float] = None    # perpetuals funding rate if applicable
    open_interest_change_pct: Optional[float] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "IntelOnChain":
        return cls(
            net_flows_usd=d["net_flows_usd"],
            whale_tx_count=d["whale_tx_count"],
            exchange_reserves_change_pct=d["exchange_reserves_change_pct"],
            active_addresses_change_pct=d.get("active_addresses_change_pct", 0.0),
            miner_outflow_usd=d.get("miner_outflow_usd", 0.0),
            funding_rate=d.get("funding_rate"),
            open_interest_change_pct=d.get("open_interest_change_pct"),
        )


@dataclass
class IntelFundamental:
    """Macro / fundamental signals attached to the snapshot."""

    regime: RegimeLabel = "unknown"
    fear_greed_index: Optional[int] = None   # 0-100
    dominance_btc_pct: Optional[float] = None
    macro_notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "IntelFundamental":
        return cls(
            regime=d.get("regime", "unknown"),
            fear_greed_index=d.get("fear_greed_index"),
            dominance_btc_pct=d.get("dominance_btc_pct"),
            macro_notes=d.get("macro_notes", []),
        )


@dataclass
class IntelAlert:
    """A cross-source alert fired by IntelliClaw's alert engine."""

    alert_id: str
    severity: ImportanceLabel
    message: str
    source: str
    fired_at: str                  # ISO-8601 UTC
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "IntelAlert":
        return cls(
            alert_id=d["alert_id"],
            severity=d.get("severity", "medium"),
            message=d["message"],
            source=d.get("source", "intelliclaw"),
            fired_at=d["fired_at"],
            tags=d.get("tags", []),
        )


# ---------------------------------------------------------------------------
# Top-level snapshot
# ---------------------------------------------------------------------------

@dataclass
class IntelSnapshot:
    """Fully normalised intelligence snapshot for one asset.

    Produced by IntelliClaw and consumed by ATLAS/TradingAgents analysts.
    """

    # Core identity
    asset: str                          # e.g. "BTC", "ETH"
    as_of: str                          # ISO-8601 UTC — snapshot timestamp
    window_hours: int = 24              # aggregation window in hours

    # Aggregate sentiment
    overall_sentiment: SentimentLabel = "neutral"
    confidence: float = 0.0             # 0.0 – 1.0
    sentiment_score: float = 0.0        # normalised -1.0 to +1.0

    # Narrative
    key_points: List[str] = field(default_factory=list)
    narrative_summary: Optional[str] = None  # IntelliClaw multi-source summary

    # Sub-schemas
    headlines: List[IntelHeadline] = field(default_factory=list)
    onchain: Optional[IntelOnChain] = None
    fundamental: Optional[IntelFundamental] = None
    alerts: List[IntelAlert] = field(default_factory=list)

    # Provenance / governance
    source_count: int = 0               # number of raw sources aggregated
    intel_version: str = "1.0"          # IntelliClaw schema version

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @property
    def has_critical_alerts(self) -> bool:
        return any(a.severity == "critical" for a in self.alerts)

    @property
    def high_importance_headlines(self) -> List[IntelHeadline]:
        return [h for h in self.headlines if h.importance in ("high", "critical")]

    def to_analyst_context(self) -> str:
        """Return a compact text block suitable for injection into LLM prompts."""
        lines = [
            f"Asset: {self.asset}  |  As-of: {self.as_of}  |  Window: {self.window_hours}h",
            f"Overall sentiment: {self.overall_sentiment} (score {self.sentiment_score:+.2f}, confidence {self.confidence:.0%})",
        ]
        if self.narrative_summary:
            lines.append(f"Summary: {self.narrative_summary}")
        if self.key_points:
            lines.append("Key points:")
            lines.extend(f"  - {p}" for p in self.key_points)
        if self.alerts:
            lines.append("Alerts:")
            lines.extend(f"  [{a.severity.upper()}] {a.message}" for a in self.alerts)
        if self.onchain:
            oc = self.onchain
            lines.append(
                f"On-chain: net_flows={oc.net_flows_usd:+,.0f} USD, "
                f"whale_txs={oc.whale_tx_count}, "
                f"reserves_chg={oc.exchange_reserves_change_pct:+.2f}%"
            )
        if self.fundamental and self.fundamental.fear_greed_index is not None:
            lines.append(f"Fear/Greed index: {self.fundamental.fear_greed_index}  |  Regime: {self.fundamental.regime}")
        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Deserialisation
    # -----------------------------------------------------------------------

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "IntelSnapshot":
        """Deserialise raw IntelliClaw API response into an IntelSnapshot."""
        headlines = [IntelHeadline.from_dict(h) for h in d.get("headlines", [])]
        onchain = IntelOnChain.from_dict(d["onchain"]) if d.get("onchain") else None
        fundamental = IntelFundamental.from_dict(d["fundamental"]) if d.get("fundamental") else None

        # alerts may be List[str] (legacy) or List[dict] (v1+)
        raw_alerts = d.get("alerts", [])
        if raw_alerts and isinstance(raw_alerts[0], str):
            # legacy plain-string alerts — wrap into IntelAlert
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            alerts = [
                IntelAlert(alert_id=str(i), severity="medium", message=a,
                           source="intelliclaw", fired_at=now)
                for i, a in enumerate(raw_alerts)
            ]
        else:
            alerts = [IntelAlert.from_dict(a) for a in raw_alerts]

        return cls(
            asset=d["asset"],
            as_of=d["as_of"],
            window_hours=d.get("window_hours", 24),
            overall_sentiment=d.get("overall_sentiment", "neutral"),
            confidence=float(d.get("confidence", 0.0)),
            sentiment_score=float(d.get("sentiment_score", 0.0)),
            key_points=d.get("key_points", []),
            narrative_summary=d.get("narrative_summary"),
            headlines=headlines,
            onchain=onchain,
            fundamental=fundamental,
            alerts=alerts,
            source_count=d.get("source_count", 0),
            intel_version=d.get("intel_version", "1.0"),
        )
