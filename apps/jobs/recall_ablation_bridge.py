"""
apps/jobs/recall_ablation_bridge.py

Bridge job: translates Recall agent performance data into backtestable
strategy hypotheses, then feeds them into the ablation_runner pipeline for
OOS validation, regime-segmentation, and Kelly input generation.

Workflow:
  1. Scan recall_portfolio_snapshots for high-performers (Sharpe > 1.5)
  2. Map trading_style → StrategyHypothesis (entry/exit logic templates)
  3. Parameterize with agent's observed performance metrics
  4. Run ablation_runner on 3-year HL historical data
  5. Segment results by QZRegime (TREND_UP, RANGE, HIGH_VOL, etc.)
  6. Compute Kelly inputs from OOS performance
  7. Write validated strategies to strategy_registry.yaml
     and kelly_buckets.db for live injection

Run via:
  poetry run python -m apps.jobs.recall_ablation_bridge

Cron schedule:
  0 2 * * 1  # Weekly on Monday at 2 AM (after weekend Recall updates)

Exit gates:
  - No hypotheses generated → exit 0 (no work)
  - Ablation fails → log + dead letter, exit 1
  - No OOS validation → no registry injection
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import AsyncIterator, Sequence

import aiosqlite
from dataclasses import dataclass

from apps.data_sources.recall.recall_client import (
    RecallAgentRecord,
    RecallClient,
    RecallPortfolioSnapshot,
)
from apps.jobs.ablation_runner import AblationRunner, AblationResult
from apps.jobs.kelly_bucket_writer import KellyBucketWriter
from apps.quant.regimes.regime_mapper import QZRegime, RegimeMapper
from apps.quant.signals.wave_adapter import WaveAdapter
from apps.quant.sizing.kelly_sizing_service import KellySizingService
from apps.research.strategy_hypothesis import StrategyHypothesis
from apps.research.strategy_registry import StrategyRegistry
from proto.common import MarketRegime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RecallAblationConfig:
    """
    Configuration for the bridge job.
    Loaded from config/jobs/recall_ablation_bridge.yaml or env vars.
    """
    recall_api_key: str
    sqlite_db_path: str = "data/recall_ablation.db"
    min_sharpe_threshold: float = 1.5
    max_age_days: int = 7
    max_agents_per_run: int = 5
    hl_historical_data_path: str = "data/hl_bars/"  # parquet files
    min_oos_trades_required: int = 30
    kelly_min_notional_pct: float = 0.005  # 0.5%
    strategy_registry_path: str = "config/strategy_registry.yaml"

    def __post_init__(self):
        self.sqlite_db_path = Path(self.sqlite_db_path).expanduser()
        self.hl_historical_data_path = Path(self.hl_historical_data_path).expanduser()
        self.strategy_registry_path = Path(self.strategy_registry_path).expanduser()


# ---------------------------------------------------------------------------
# Job implementation
# ---------------------------------------------------------------------------

class RecallAblationBridge:
    """
    Main job class. Orchestrates Recall → Hypothesis → Ablation → Registry pipeline.
    """

    def __init__(self, config: RecallAblationConfig):
        self.config = config
        self.recall_client = Recall
