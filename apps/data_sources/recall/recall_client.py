"""
apps/data_sources/recall/recall_client.py

Recall Network platform fetcher and schema normalizer.
Fetches agent performance records, competition metadata, and
portfolio snapshots from the Recall Network API and normalizes
them into typed dataclasses suitable for downstream consumption
by MarketIntelligenceSifter, ObserverAgent, and ResearchPackage
generation.

Architecture constraints:
  - Zero network calls in __init__ — all I/O is explicit via methods.
  - All public methods return typed dataclasses — no raw dicts leak out.
  - This module has zero LLM calls, zero side effects, no persistence.
  - Callers are responsible for retry logic and caching.
  - API key loaded from environment; never from arguments or hardcoded.

Recall Network API reference:
  https://docs.recall.network/
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RECALL_API_BASE = "https://api.recall.network/v1/"
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_PAGE_SIZE = 50


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CompetitionStatus(str, Enum):
    ACTIVE    = "active"
    COMPLETED = "completed"
    UPCOMING  = "upcoming"
    UNKNOWN   = "unknown"


class AgentTradingStyle(str, Enum):
    MOMENTUM      = "momentum"
    MEAN_REVERSION = "mean_reversion"
    ARBITRAGE     = "arbitrage"
    MARKET_MAKING = "market_making"
    MULTI_FACTOR  = "multi_factor"
    UNKNOWN       = "unknown"


# ---------------------------------------------------------------------------
# Normalized schema dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RecallAgentRecord:
    """
    Normalized record for a single Recall Network agent.
    Used by: MarketIntelligenceSifter, ResearchPackage strategy hypothesis
    """
    agent_id: str
    agent_name: str
    trading_style: AgentTradingStyle

    # Performance metrics (all from OOS competition periods)
    total_return_pct: float
    sharpe_ratio: Optional[float]
    max_drawdown_pct: Optional[float]
    win_rate: Optional[float]
    profit_factor: Optional[float]

    # Context
    competition_id: str
    competition_name: str
    competition_status: CompetitionStatus
    rank: Optional[int]
    total_participants: Optional[int]

    # Assets traded (normalized to uppercase ticker)
    traded_assets: list[str] = field(default_factory=list)

    # Metadata
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source_url: Optional[str] = None


@dataclass(frozen=True)
class RecallCompetition:
    """
    Normalized record for a Recall Network competition.
    """
    competition_id: str
    name: str
    status: CompetitionStatus
    start_at: Optional[datetime]
    end_at: Optional[datetime]
    participant_count: int
    description: Optional[str]

    # Top performers (list of agent_ids)
    top_agent_ids: list[str] = field(default_factory=list)

    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass(frozen=True)
class RecallPortfolioSnapshot:
    """
    Point-in-time portfolio snapshot for a specific agent in a competition.
    """
    agent_id: str
    competition_id: str
    snapshot_at: datetime

    # Positions: list of {asset, size_usd, direction, unrealized_pnl_usd}
    positions: list[dict] = field(default_factory=list)

    # Aggregate metrics at snapshot time
    total_value_usd: float = 0.0
    unrealized_pnl_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    leverage: Optional[float] = None

    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class RecallFetchResult:
    """
    Wrapper for all data fetched in a single RecallClient session.
    Written into MarketIntelligenceSifter input queue.
    """
    competitions: list[RecallCompetition] = field(default_factory=list)
    agents: list[RecallAgentRecord] = field(default_factory=list)
    snapshots: list[RecallPortfolioSnapshot] = field(default_factory=list)

    fetch_errors: list[str] = field(default_factory=list)
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def has_errors(self) -> bool:
        return len(self.fetch_errors) > 0

    @property
    def top_agents_by_sharpe(self) -> list[RecallAgentRecord]:
        """Return agents sorted by Sharpe ratio descending, None last."""
        return sorted(
            [a for a in self.agents if a.sharpe_ratio is not None],
            key=lambda a: a.sharpe_ratio,
            reverse=True,
        )

    @property
    def traded_asset_universe(self) -> set[str]:
        """All unique assets traded across all fetched agents."""
        universe: set[str] = set()
        for agent in self.agents:
            universe.update(agent.traded_assets)
        return universe


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class RecallClient:
    """
    Fetches and normalizes data from the Recall Network API.

    Usage:
        client = RecallClient()  # reads RECALL_API_KEY from env
        result = client.fetch_all(max_competitions=5, max_agents_per_competition=20)

        # Feed to MarketIntelligenceSifter
        for agent in result.top_agents_by_sharpe:
            sifter.ingest_recall_agent(agent)

    All methods are synchronous. For async callers, wrap with asyncio.run_in_executor.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = RECALL_API_BASE,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        self._api_key = api_key or os.environ.get("RECALL_API_KEY", "")
        self._base_url = base_url
        self._timeout = timeout

        if not self._api_key:
            logger.warning(
                "RecallClient: RECALL_API_KEY not set — "
                "authenticated endpoints will fail with 401."
            )

        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": "hyperliquid-trading-firm/1.0",
        })
        if self._api_key:
            self._session.headers["Authorization"] = f"Bearer {self._api_key}"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_all(
        self,
        max_competitions: int = 10,
        max_agents_per_competition: int = DEFAULT_PAGE_SIZE,
        include_snapshots: bool = False,
        status_filter: Optional[CompetitionStatus] = None,
    ) -> RecallFetchResult:
        """
        Main entry point. Fetches competitions, then agents for each,
        optionally including portfolio snapshots for top performers.

        Args:
            max_competitions: Maximum number of competitions to fetch.
            max_agents_per_competition: Max leaderboard entries per competition.
            include_snapshots: If True, fetch portfolio snapshots for top 5
                               agents per competition (adds latency).
            status_filter: If set, only fetch competitions of this status.

        Returns:
            RecallFetchResult with all normalized data.
        """
        result = RecallFetchResult()

        # 1. Fetch competitions
        competitions = self._fetch_competitions(
            limit=max_competitions,
            status_filter=status_filter,
        )
        result.competitions.extend(competitions)
        logger.info(
            "RecallClient: fetched %d competitions", len(competitions)
        )

        # 2. For each competition, fetch leaderboard
        for comp in competitions:
            agents, errors = self._fetch_leaderboard(
                competition_id=comp.competition_id,
                limit=max_agents_per_competition,
                competition=comp,
            )
            result.agents.extend(agents)
            result.fetch_errors.extend(errors)

            # 3. Optionally fetch snapshots for top 5 agents
            if include_snapshots:
                top_ids = comp.top_agent_ids[:5]
                for agent_id in top_ids:
                    snapshot, err = self._fetch_portfolio_snapshot(
                        agent_id=agent_id,
                        competition_id=comp.competition_id,
                    )
                    if snapshot:
                        result.snapshots.append(snapshot)
                    if err:
                        result.fetch_errors.append(err)

        logger.info(
            "RecallClient: fetch_all complete — "
            "%d agents, %d snapshots, %d errors",
            len(result.agents),
            len(result.snapshots),
            len(result.fetch_errors),
        )
        return result

    def fetch_competition(self, competition_id: str) -> Optional[RecallCompetition]:
        """Fetch a single competition by ID."""
        try:
            data = self._get(f"competitions/{competition_id}")
            return self._normalize_competition(data)
        except Exception as exc:
            logger.error(
                "RecallClient: failed to fetch competition %s: %s",
                competition_id, exc
            )
            return None

    def fetch_agent(
        self,
        agent_id: str,
        competition_id: str,
    ) -> Optional[RecallAgentRecord]:
        """Fetch a single agent's record within a competition."""
        try:
            data = self._get(
                f"competitions/{competition_id}/agents/{agent_id}"
            )
            return self._normalize_agent(data, competition_id=competition_id)
        except Exception as exc:
            logger.error(
                "RecallClient: failed to fetch agent %s in competition %s: %s",
                agent_id, competition_id, exc
            )
            return None

    # ------------------------------------------------------------------
    # Private fetch helpers
    # ------------------------------------------------------------------

    def _fetch_competitions(
        self,
        limit: int,
        status_filter: Optional[CompetitionStatus],
    ) -> list[RecallCompetition]:
        """Paginate competitions endpoint and normalize."""
        params: dict[str, Any] = {"limit": min(limit, DEFAULT_PAGE_SIZE)}
        if status_filter:
            params["status"] = status_filter.value

        try:
            raw = self._get("competitions", params=params)
            items = raw if isinstance(raw, list) else raw.get("data", raw.get("competitions", []))
            return [self._normalize_competition(item) for item in items[:limit]]
        except Exception as exc:
            logger.error("RecallClient: _fetch_competitions error: %s", exc)
            return []

    def _fetch_leaderboard(
        self,
        competition_id: str,
        limit: int,
        competition: RecallCompetition,
    ) -> tuple[list[RecallAgentRecord], list[str]]:
        """Fetch leaderboard for a competition, return (agents, errors)."""
        agents: list[RecallAgentRecord] = []
        errors: list[str] = []

        try:
            raw = self._get(
                f"competitions/{competition_id}/leaderboard",
                params={"limit": limit},
            )
            items = raw if isinstance(raw, list) else raw.get("data", raw.get("agents", []))
            for item in items[:limit]:
                try:
                    agent = self._normalize_agent(
                        item,
                        competition_id=competition_id,
                        competition=competition,
                    )
                    agents.append(agent)
                except Exception as exc:
                    err = (
                        f"normalize_agent failed for competition "
                        f"{competition_id}: {exc}"
                    )
                    errors.append(err)
                    logger.debug(err)
        except Exception as exc:
            err = f"_fetch_leaderboard failed for {competition_id}: {exc}"
            errors.append(err)
            logger.error(err)

        return agents, errors

    def _fetch_portfolio_snapshot(
        self,
        agent_id: str,
        competition_id: str,
    ) -> tuple[Optional[RecallPortfolioSnapshot], Optional[str]]:
        """Fetch latest portfolio snapshot for agent. Returns (snapshot, error)."""
        try:
            raw = self._get(
                f"competitions/{competition_id}/agents/{agent_id}/portfolio"
            )
            return self._normalize_snapshot(raw, agent_id, competition_id), None
        except Exception as exc:
            err = (
                f"_fetch_portfolio_snapshot failed for "
                f"agent={agent_id} comp={competition_id}: {exc}"
            )
            logger.error(err)
            return None, err

    # ------------------------------------------------------------------
    # Normalizers — raw API dict → typed dataclass
    # ------------------------------------------------------------------

    def _normalize_competition(self, raw: dict) -> RecallCompetition:
        """
        Normalize a raw competition dict from the Recall API.
        Field names are best-effort; adjust as API schema evolves.
        """
        status_str = raw.get("status", "unknown").lower()
        try:
            status = CompetitionStatus(status_str)
        except ValueError:
            status = CompetitionStatus.UNKNOWN

        return RecallCompetition(
            competition_id=str(raw.get("id") or raw.get("competitionId", "")),
            name=str(raw.get("name") or raw.get("title", "Unknown")),
            status=status,
            start_at=self._parse_dt(raw.get("startAt") or raw.get("start_at")),
            end_at=self._parse_dt(raw.get("endAt") or raw.get("end_at")),
            participant_count=int(raw.get("participantCount") or raw.get("participant_count", 0)),
            description=raw.get("description"),
            top_agent_ids=[
                str(a) for a in (raw.get("topAgents") or raw.get("top_agents", []))
            ],
        )

    def _normalize_agent(
        self,
        raw: dict,
        competition_id: str,
        competition: Optional[RecallCompetition] = None,
    ) -> RecallAgentRecord:
        """
        Normalize a raw agent/leaderboard entry from the Recall API.
        """
        style_str = (
            raw.get("tradingStyle")
            or raw.get("trading_style")
            or raw.get("strategy_type")
            or "unknown"
        ).lower().replace("-", "_").replace(" ", "_")
        try:
            trading_style = AgentTradingStyle(style_str)
        except ValueError:
            trading_style = AgentTradingStyle.UNKNOWN

        # Normalize traded assets to uppercase tickers
        raw_assets = (
            raw.get("tradedAssets")
            or raw.get("traded_assets")
            or raw.get("assets", [])
        )
        traded_assets = [str(a).upper() for a in raw_assets if a]

        comp_id = competition_id
        comp_name = competition.name if competition else raw.get("competitionName", "")
        comp_status = competition.status if competition else CompetitionStatus.UNKNOWN

        return RecallAgentRecord(
            agent_id=str(raw.get("id") or raw.get("agentId") or raw.get("agent_id", "")),
            agent_name=str(raw.get("name") or raw.get("agentName") or raw.get("agent_name", "Unknown")),
            trading_style=trading_style,
            total_return_pct=float(raw.get("totalReturn") or raw.get("total_return") or raw.get("return", 0.0)),
            sharpe_ratio=self._safe_float(raw.get("sharpeRatio") or raw.get("sharpe_ratio")),
            max_drawdown_pct=self._safe_float(raw.get("maxDrawdown") or raw.get("max_drawdown")),
            win_rate=self._safe_float(raw.get("winRate") or raw.get("win_rate")),
            profit_factor=self._safe_float(raw.get("profitFactor") or raw.get("profit_factor")),
            competition_id=comp_id,
            competition_name=comp_name,
            competition_status=comp_status,
            rank=self._safe_int(raw.get("rank")),
            total_participants=self._safe_int(
                raw.get("totalParticipants") or raw.get("total_participants")
            ),
            traded_assets=traded_assets,
            source_url=raw.get("url"),
        )

    def _normalize_snapshot(
        self,
        raw: dict,
        agent_id: str,
        competition_id: str,
    ) -> RecallPortfolioSnapshot:
        """Normalize a raw portfolio snapshot dict."""
        positions_raw = raw.get("positions") or raw.get("holdings", [])
        positions = []
        for pos in positions_raw:
            positions.append({
                "asset":              str(pos.get("asset") or pos.get("symbol", "")).upper(),
                "size_usd":           float(pos.get("sizeUsd") or pos.get("size_usd") or pos.get("value", 0.0)),
                "direction":          str(pos.get("direction") or pos.get("side", "LONG")).upper(),
                "unrealized_pnl_usd": float(pos.get("unrealizedPnl") or pos.get("unrealized_pnl", 0.0)),
            })

        return RecallPortfolioSnapshot(
            agent_id=agent_id,
            competition_id=competition_id,
            snapshot_at=self._parse_dt(
                raw.get("snapshotAt") or raw.get("snapshot_at") or raw.get("timestamp")
            ) or datetime.now(timezone.utc),
            positions=positions,
            total_value_usd=float(raw.get("totalValueUsd") or raw.get("total_value_usd", 0.0)),
            unrealized_pnl_usd=float(raw.get("unrealizedPnlUsd") or raw.get("unrealized_pnl_usd", 0.0)),
            realized_pnl_usd=float(raw.get("realizedPnlUsd") or raw.get("realized_pnl_usd", 0.0)),
            leverage=self._safe_float(raw.get("leverage")),
        )

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        """
        Issue a GET request to the Recall API.
        Raises requests.HTTPError on non-2xx responses.
        Callers are responsible for retry / backoff.
        """
        url = urljoin(self._base_url, path)
        resp = self._session.get(url, params=params, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Type coercion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        """Parse ISO 8601 string or Unix timestamp to UTC datetime."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value, tz=timezone.utc)
            except (OSError, OverflowError, ValueError):
                return None
        if isinstance(value, str):
            for fmt in (
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d",
            ):
                try:
                    dt = datetime.strptime(value, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except ValueError:
                    continue
        return None
