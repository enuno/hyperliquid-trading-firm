# apps/agents/src/types/intel.py

from dataclasses import dataclass
from typing import List, Literal, Optional

SentimentLabel = Literal["bullish", "bearish", "mixed", "neutral"]

@dataclass
class IntelHeadline:
    source: str
    title: str
    url: str
    published_at: str
    sentiment: SentimentLabel
    importance: Literal["low", "medium", "high"]

@dataclass
class IntelOnChain:
    net_flows_usd: float
    whale_tx_count: int
    exchange_reserves_change_pct: float

@dataclass
class IntelSnapshot:
    asset: str
    as_of: str
    overall_sentiment: SentimentLabel
    confidence: float
    key_points: List[str]
    headlines: List[IntelHeadline]
    onchain: Optional[IntelOnChain]
    alerts: List[str]
