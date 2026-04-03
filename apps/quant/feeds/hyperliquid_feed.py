"""
apps/quant/feeds/hyperliquid_feed.py

HyperLiquid market context feed adapter for the quant layer.
Produces HLMarketContext objects consumed by ObserverAgent
and Quant-Zero signal primitives.

Architecture: snapshot-first (REST bootstrap), event-updated (WS deltas),
reconciliation every RECONCILE_INTERVAL_S seconds.

No LLM calls. No execution logic. Read-only.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx
import websockets

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HLBar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    interval: str  # "1m" | "5m" | "1h" | "4h"


@dataclass(frozen=True)
class HLOrderBookLevel:
    price: float
    size: float


@dataclass
class HLOrderBook:
    ts: datetime
    bids: List[HLOrderBookLevel]
    asks: List[HLOrderBookLevel]
    spread_bps: float
    depth_10bps_usd: float   # notional within ±10bps of mid
    staleness_seconds: int = 0


@dataclass
class HLFunding:
    ts: datetime
    rate_8h: float           # 8-hour equivalent funding rate
    rate_zscore_30d: Optional[float] = None
    staleness_seconds: int = 0


@dataclass
class HLOpenInterest:
    ts: datetime
    oi_usd: float
    oi_delta_1h_pct: Optional[float] = None
    staleness_seconds: int = 0


@dataclass
class HLLiquidationCluster:
    price: float
    side: str                 # "long" | "short"
    notional_usd: float
    distance_pct: float       # signed distance from mid_price


@dataclass
class HLMarketContext:
    """
    Normalized, timestamped market context snapshot for one asset.
    Consumed by:
      - apps/agents/observer/observer_agent.py  → ObservationPack
      - apps/quant/regimes/qz_regime_classifier.py
      - apps/quant/sizing/kelly_sizing_service.py
      - apps/jobs/backtest_runner.py (replay mode)
    """
    asset: str
    as_of: datetime
    mark_price: float
    mid_price: float
    index_price: Optional[float]

    bars_1m: List[HLBar] = field(default_factory=list)
    bars_5m: List[HLBar] = field(default_factory=list)
    bars_1h: List[HLBar] = field(default_factory=list)
    bars_4h: List[HLBar] = field(default_factory=list)

    orderbook: Optional[HLOrderBook] = None
    funding: Optional[HLFunding] = None
    open_interest: Optional[HLOpenInterest] = None
    liquidation_clusters: List[HLLiquidationCluster] = field(default_factory=list)

    source_staleness_seconds: Dict[str, int] = field(default_factory=dict)
    has_data_gap: bool = False
    gap_sources: List[str] = field(default_factory=list)

    def stale_sources(self, threshold_s: int = 60) -> List[str]:
        return [src for src, age in self.source_staleness_seconds.items() if age > threshold_s]

    def to_observation_dict(self) -> dict:
        """Serialize for ObservationPack.quantitative_baseline."""
        return {
            "asset": self.asset,
            "as_of_ms": int(self.as_of.timestamp() * 1000),
            "mark_price": self.mark_price,
            "mid_price": self.mid_price,
            "funding_rate_8h": self.funding.rate_8h if self.funding else None,
            "funding_zscore_30d": self.funding.rate_zscore_30d if self.funding else None,
            "oi_usd": self.open_interest.oi_usd if self.open_interest else None,
            "oi_delta_1h_pct": self.open_interest.oi_delta_1h_pct if self.open_interest else None,
            "spread_bps": self.orderbook.spread_bps if self.orderbook else None,
            "depth_10bps_usd": self.orderbook.depth_10bps_usd if self.orderbook else None,
            "liq_clusters": [
                {
                    "price": c.price,
                    "side": c.side,
                    "notional_usd": c.notional_usd,
                    "distance_pct": c.distance_pct,
                }
                for c in self.liquidation_clusters
            ],
            "has_data_gap": self.has_data_gap,
            "gap_sources": self.gap_sources,
        }


# ---------------------------------------------------------------------------
# REST client
# ---------------------------------------------------------------------------

class HLRestClient:
    """
    Thin wrapper over HyperLiquid REST endpoints.
    Returns raw dicts; normalization happens in HyperliquidFeed.

    Base URL and timeout sourced from env via config loader.
    Never hardcodes credentials; HL public market endpoints are unauthenticated.
    """

    def __init__(self, base_url: str, timeout_s: float = 10.0):
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def get_candles(
        self,
        asset: str,
        interval: str,
        count: int = 200,
    ) -> list:
        """
        GET /info  →  candle snapshot.
        interval: "1m" | "5m" | "1h" | "4h"
        Returns list of raw candle dicts.
        """
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": asset,
                "interval": interval,
                "startTime": None,
                "endTime": None,
            },
        }
        resp = await self._client.post(f"{self._base}/info", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_meta_and_ctx(self) -> dict:
        """GET /info → metaAndAssetCtxs (funding, OI, mark price)."""
        resp = await self._client.post(
            f"{self._base}/info", json={"type": "metaAndAssetCtxs"}
        )
        resp.raise_for_status()
        return resp.json()

    async def get_l2_book(self, asset: str) -> dict:
        """GET /info → L2 order book snapshot."""
        resp = await self._client.post(
            f"{self._base}/info",
            json={"type": "l2Book", "coin": asset},
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------

def _normalize_candle(raw: dict, interval: str) -> HLBar:
    return HLBar(
        ts=datetime.fromtimestamp(raw["t"] / 1000, tz=timezone.utc),
        open=float(raw["o"]),
        high=float(raw["h"]),
        low=float(raw["l"]),
        close=float(raw["c"]),
        volume=float(raw["v"]),
        interval=interval,
    )


def _normalize_book(raw: dict, mid_price: float) -> HLOrderBook:
    bids = [HLOrderBookLevel(float(b[0]), float(b[1])) for b in raw.get("levels", [[]])[0]]
    asks = [HLOrderBookLevel(float(a[0]), float(a[1])) for a in raw.get("levels", [[]])[1]]

    best_bid = bids[0].price if bids else mid_price
    best_ask = asks[0].price if asks else mid_price
    mid = (best_bid + best_ask) / 2 if mid_price == 0 else mid_price
    spread_bps = ((best_ask - best_bid) / mid * 10_000) if mid > 0 else 0.0

    threshold = mid * 0.001  # 10bps
    depth_usd = sum(
        b.price * b.size for b in bids if b.price >= mid - threshold
    ) + sum(
        a.price * a.size for a in asks if a.price <= mid + threshold
    )

    return HLOrderBook(
        ts=datetime.now(tz=timezone.utc),
        bids=bids[:20],
        asks=asks[:20],
        spread_bps=round(spread_bps, 4),
        depth_10bps_usd=round(depth_usd, 2),
    )


def _normalize_funding_and_oi(
    meta_ctx: dict,
    asset: str,
) -> tuple[Optional[HLFunding], Optional[HLOpenInterest]]:
    """
    Extract funding and OI from metaAndAssetCtxs response.
    Returns (HLFunding, HLOpenInterest) or (None, None) on key error.
    """
    try:
        universe = meta_ctx[0]["universe"]
        ctxs = meta_ctx[1]
        idx = next(i for i, u in enumerate(universe) if u["name"] == asset)
        ctx = ctxs[idx]

        # HL returns funding as a decimal per 8h period
        raw_funding = float(ctx.get("funding", 0.0))

        funding = HLFunding(
            ts=datetime.now(tz=timezone.utc),
            rate_8h=raw_funding,
        )
        oi_usd = float(ctx.get("openInterest", 0.0)) * float(ctx.get("markPx", 0.0))
        oi = HLOpenInterest(
            ts=datetime.now(tz=timezone.utc),
            oi_usd=oi_usd,
        )
        return funding, oi
    except (StopIteration, IndexError, KeyError, TypeError) as exc:
        logger.warning("funding/OI extraction failed for %s: %s", asset, exc)
        return None, None


# ---------------------------------------------------------------------------
# Main feed class
# ---------------------------------------------------------------------------

RECONCILE_INTERVAL_S = 30
STALE_THRESHOLD_S = 60


class HyperliquidFeed:
    """
    Snapshot-first, event-updated market context feed for one HL perp asset.

    Lifecycle:
      1. bootstrap()  — full REST snapshot to establish truth
      2. start()      — launches background WS update loop
      3. get_context() — returns latest HLMarketContext (caller-safe)
      4. stop()       — graceful shutdown

    Thread model: asyncio. All methods are async.
    Used by: ObserverAgent, backtest_runner, qz_regime_classifier.
    """

    def __init__(
        self,
        asset: str,
        rest_client: HLRestClient,
        ws_url: str,
        stale_threshold_s: int = STALE_THRESHOLD_S,
        reconcile_interval_s: int = RECONCILE_INTERVAL_S,
    ):
        self.asset = asset
        self._rest = rest_client
        self._ws_url = ws_url
        self._stale_threshold = stale_threshold_s
        self._reconcile_interval = reconcile_interval_s

        self._context: Optional[HLMarketContext] = None
        self._lock = asyncio.Lock()
        self._running = False
        self._tasks: list[asyncio.Task] = []

        self._last_reconcile: float = 0.0

    async def bootstrap(self) -> HLMarketContext:
        """
        Full REST snapshot. Must be called before start() or get_context().
        Raises on any fetch failure — caller should handle and retry.
        """
        logger.info("[%s] bootstrapping feed via REST", self.asset)
        ctx = await self._fetch_rest_snapshot()
        async with self._lock:
            self._context = ctx
        self._last_reconcile = time.monotonic()
        logger.info("[%s] bootstrap complete; mark_price=%.2f", self.asset, ctx.mark_price)
        return ctx

    async def start(self) -> None:
        """Launch WS update loop and periodic reconciliation."""
        self._running = True
        self._tasks = [
            asyncio.create_task(self._ws_loop(), name=f"hl_ws_{self.asset}"),
            asyncio.create_task(self._reconcile_loop(), name=f"hl_rec_{self.asset}"),
        ]
        logger.info("[%s] feed started", self.asset)

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._rest.close()
        logger.info("[%s] feed stopped", self.asset)

    def get_context(self) -> Optional[HLMarketContext]:
        """
        Synchronous snapshot read (no lock needed — Python GIL).
        Returns None if bootstrap has not been called.
        """
        return self._context

    def is_stale(self) -> bool:
        ctx = self._context
        if ctx is None:
            return True
        return bool(ctx.stale_sources(self._stale_threshold)) or ctx.has_data_gap

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _fetch_rest_snapshot(self) -> HLMarketContext:
        now = datetime.now(tz=timezone.utc)
        source_staleness: Dict[str, int] = {}
        gap_sources: List[str] = []

        bars_1m, bars_5m, bars_1h, bars_4h = [], [], [], []
        for interval, store in [("1m", None), ("5m", None), ("1h", None), ("4h", None)]:
            try:
                raw = await self._rest.get_candles(self.asset, interval, count=200)
                parsed = [_normalize_candle(c, interval) for c in raw]
                source_staleness[f"bars_{interval}"] = 0
                if interval == "1m":
                    bars_1m = parsed
                elif interval == "5m":
                    bars_5m = parsed
                elif interval == "1h":
                    bars_1h = parsed
                elif interval == "4h":
                    bars_4h = parsed
            except Exception as exc:
                logger.warning("[%s] candle fetch failed (%s): %s", self.asset, interval, exc)
                source_staleness[f"bars_{interval}"] = 999
                gap_sources.append(f"bars_{interval}")

        meta_ctx = None
        try:
            meta_ctx = await self._rest.get_meta_and_ctx()
            source_staleness["meta_ctx"] = 0
        except Exception as exc:
            logger.warning("[%s] meta_ctx fetch failed: %s", self.asset, exc)
            source_staleness["meta_ctx"] = 999
            gap_sources.append("meta_ctx")

        funding, open_interest = (None, None)
        mark_price = 0.0
        mid_price = 0.0

        if meta_ctx:
            try:
                universe = meta_ctx[0]["universe"]
                ctxs = meta_ctx[1]
                idx = next(i for i, u in enumerate(universe) if u["name"] == self.asset)
                mark_price = float(ctxs[idx].get("markPx", 0.0))
                mid_price = mark_price
            except Exception:
                pass
            funding, open_interest = _normalize_funding_and_oi(meta_ctx, self.asset)

        orderbook = None
        try:
            raw_book = await self._rest.get_l2_book(self.asset)
            orderbook = _normalize_book(raw_book, mid_price)
            source_staleness["orderbook"] = 0
            mid_price = (
                (orderbook.bids[0].price + orderbook.asks[0].price) / 2
                if orderbook.bids and orderbook.asks
                else mid_price
            )
        except Exception as exc:
            logger.warning("[%s] orderbook fetch failed: %s", self.asset, exc)
            source_staleness["orderbook"] = 999
            gap_sources.append("orderbook")

        has_data_gap = bool(gap_sources)

        return HLMarketContext(
            asset=self.asset,
            as_of=now,
            mark_price=mark_price,
            mid_price=mid_price,
            index_price=None,
            bars_1m=bars_1m,
            bars_5m=bars_5m,
            bars_1h=bars_1h,
            bars_4h=bars_4h,
            orderbook=orderbook,
            funding=funding,
            open_interest=open_interest,
            liquidation_clusters=[],  # TODO: wire liq map source
            source_staleness_seconds=source_staleness,
            has_data_gap=has_data_gap,
            gap_sources=gap_sources,
        )

    async def _ws_loop(self) -> None:
        """
        WebSocket subscription for live book and ticker updates.
        Reconnects on disconnect. Updates _context in-place.
        TODO: subscribe to trades, liquidation events.
        """
        while self._running:
            try:
                async with websockets.connect(self._ws_url) as ws:
                    sub = {
                        "method": "subscribe",
                        "subscription": {"type": "l2Book", "coin": self.asset},
                    }
                    await ws.send(__import__("json").dumps(sub))
                    logger.info("[%s] WS connected", self.asset)
                    async for raw_msg in ws:
                        if not self._running:
                            break
                        await self._handle_ws_message(raw_msg)
            except Exception as exc:
                if self._running:
                    logger.warning("[%s] WS disconnected: %s — reconnecting in 5s", self.asset, exc)
                    await asyncio.sleep(5)

    async def _handle_ws_message(self, raw: str) -> None:
        import json
        try:
            msg = json.loads(raw)
            if msg.get("channel") == "l2Book":
                data = msg.get("data", {})
                ctx = self._context
                if ctx is None:
                    return
                mid = ctx.mid_price
                new_book = _normalize_book({"levels": [data.get("bids", []), data.get("asks", [])]}, mid)
                new_mid = (
                    (new_book.bids[0].price + new_book.asks[0].price) / 2
                    if new_book.bids and new_book.asks
                    else mid
                )
                async with self._lock:
                    self._context = HLMarketContext(
                        asset=ctx.asset,
                        as_of=datetime.now(tz=timezone.utc),
                        mark_price=ctx.mark_price,
                        mid_price=new_mid,
                        index_price=ctx.index_price,
                        bars_1m=ctx.bars_1m,
                        bars_5m=ctx.bars_5m,
                        bars_1h=ctx.bars_1h,
                        bars_4h=ctx.bars_4h,
                        orderbook=new_book,
                        funding=ctx.funding,
                        open_interest=ctx.open_interest,
                        liquidation_clusters=ctx.liquidation_clusters,
                        source_staleness_seconds={**ctx.source_staleness_seconds, "orderbook": 0},
                        has_data_gap=ctx.has_data_gap,
                        gap_sources=ctx.gap_sources,
                    )
        except Exception as exc:
            logger.debug("[%s] WS message parse error: %s", self.asset, exc)

    async def _reconcile_loop(self) -> None:
        """Periodic REST reconciliation to detect drift and missing deltas."""
        while self._running:
            await asyncio.sleep(self._reconcile_interval)
            try:
                ctx = await self._fetch_rest_snapshot()
                async with self._lock:
                    self._context = ctx
                logger.debug("[%s] reconciled; stale=%s", self.asset, ctx.stale_sources())
            except Exception as exc:
                logger.warning("[%s] reconciliation failed: %s", self.asset, exc)
