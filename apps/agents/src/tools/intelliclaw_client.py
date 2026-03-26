"""IntelliClaw HTTP client for the HyperLiquid trading firm agents.

Exposes three primary call patterns:
  1. get_intel_snapshot()   – single-asset normalised IntelSnapshot (cached)
  2. search_events()        – historical events for a given asset + window
  3. iter_alert_stream()    – SSE/polling stream of live IntelliClaw alerts

Configuration via environment variables:
  INTELLICLAW_URL       Base URL of the IntelliClaw API  (required)
  INTELLICLAW_API_KEY   Bearer token for authenticated endpoints (optional)
  INTELLICLAW_CACHE_TTL Cache TTL in seconds for snapshot calls (default 60)

Error handling:
  - Transient HTTP errors are retried with exponential back-off (max 3 attempts).
  - On persistent failure, get_intel_snapshot() raises IntelliClawError.
  - Cache is in-process (TTL-based dict); replace with Redis for multi-worker.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Dict, Generator, Iterator, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..types.intel import IntelAlert, IntelSnapshot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL: str = os.environ.get("INTELLICLAW_URL", "http://intelliclaw:8080")
API_KEY: Optional[str] = os.environ.get("INTELLICLAW_API_KEY")
CACHE_TTL: int = int(os.environ.get("INTELLICLAW_CACHE_TTL", "60"))


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class IntelliClawError(RuntimeError):
    """Raised when IntelliClaw returns a non-retryable error."""


# ---------------------------------------------------------------------------
# Internal session with retry logic
# ---------------------------------------------------------------------------

def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    if API_KEY:
        session.headers.update({"Authorization": f"Bearer {API_KEY}"})
    return session


_session: requests.Session = _build_session()


# ---------------------------------------------------------------------------
# Simple TTL cache (in-process; swap for Redis in multi-worker deployments)
# ---------------------------------------------------------------------------

_snapshot_cache: Dict[str, tuple] = {}  # asset -> (IntelSnapshot, expires_at)


def _cache_get(asset: str) -> Optional[IntelSnapshot]:
    entry = _snapshot_cache.get(asset)
    if entry and time.monotonic() < entry[1]:
        return entry[0]
    return None


def _cache_set(asset: str, snapshot: IntelSnapshot) -> None:
    _snapshot_cache[asset] = (snapshot, time.monotonic() + CACHE_TTL)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_intel_snapshot(
    asset: str,
    window_hours: int = 24,
    bypass_cache: bool = False,
) -> IntelSnapshot:
    """Fetch and return a normalised IntelSnapshot for *asset*.

    Results are cached in-process for INTELLICLAW_CACHE_TTL seconds.

    Args:
        asset:         Ticker symbol, e.g. "BTC", "ETH".
        window_hours:  Aggregation window passed to IntelliClaw (default 24 h).
        bypass_cache:  If True, always fetch fresh data.

    Returns:
        IntelSnapshot dataclass.

    Raises:
        IntelliClawError: On non-retryable HTTP or parsing failures.
    """
    cache_key = f"{asset}:{window_hours}"

    if not bypass_cache:
        cached = _cache_get(cache_key)
        if cached:
            logger.debug("[intelliclaw] cache hit for %s", cache_key)
            return cached

    logger.debug("[intelliclaw] fetching snapshot for %s (window=%dh)", asset, window_hours)
    try:
        resp = _session.get(
            f"{BASE_URL}/intel/snapshot",
            params={"asset": asset, "window_hours": window_hours},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise IntelliClawError(f"IntelliClaw snapshot request failed for {asset}: {exc}") from exc

    try:
        data = resp.json()
        snapshot = IntelSnapshot.from_dict(data)
    except Exception as exc:
        raise IntelliClawError(f"Failed to parse IntelliClaw response for {asset}: {exc}") from exc

    _cache_set(cache_key, snapshot)
    logger.info(
        "[intelliclaw] snapshot ok: asset=%s sentiment=%s confidence=%.2f alerts=%d",
        asset,
        snapshot.overall_sentiment,
        snapshot.confidence,
        len(snapshot.alerts),
    )
    return snapshot


def search_events(
    asset: str,
    window: str = "24h",
    limit: int = 50,
    importance: Optional[str] = None,
) -> List[dict]:
    """Search recent IntelliClaw events (news, protocol changes, exploits, etc.).

    Args:
        asset:       Ticker symbol.
        window:      Lookback window string, e.g. "6h", "24h", "7d".
        limit:       Max number of events to return.
        importance:  Filter by importance level: "low", "medium", "high", "critical".

    Returns:
        List of raw event dicts from IntelliClaw.  Callers may cast to IntelHeadline
        via IntelHeadline.from_dict() if needed.

    Raises:
        IntelliClawError: On request or parsing failures.
    """
    params: dict = {"asset": asset, "window": window, "limit": limit}
    if importance:
        params["importance"] = importance

    logger.debug("[intelliclaw] searching events: %s", params)
    try:
        resp = _session.get(f"{BASE_URL}/intel/events", params=params, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise IntelliClawError(f"IntelliClaw events request failed: {exc}") from exc

    try:
        return resp.json().get("events", [])
    except Exception as exc:
        raise IntelliClawError(f"Failed to parse IntelliClaw events response: {exc}") from exc


def iter_alert_stream(
    asset: str,
    poll_interval: float = 5.0,
    max_alerts: Optional[int] = None,
) -> Generator[IntelAlert, None, None]:
    """Poll IntelliClaw's alert endpoint and yield new IntelAlert objects.

    This is a polling-based fallback.  If IntelliClaw exposes a Server-Sent
    Events (SSE) endpoint at /intel/alerts/stream, replace the body with an
    sseclient-based implementation.

    Args:
        asset:          Ticker symbol to filter alerts by.
        poll_interval:  Seconds between polls (default 5).
        max_alerts:     Stop after yielding this many alerts (None = run forever).

    Yields:
        IntelAlert objects as they arrive.
    """
    seen_ids: set = set()
    yielded = 0

    while True:
        try:
            resp = _session.get(
                f"{BASE_URL}/intel/alerts",
                params={"asset": asset, "limit": 20},
                timeout=10,
            )
            resp.raise_for_status()
            raw_alerts = resp.json().get("alerts", [])

            for raw in raw_alerts:
                alert_id = raw.get("alert_id", "")
                if alert_id in seen_ids:
                    continue
                seen_ids.add(alert_id)
                try:
                    alert = IntelAlert.from_dict(raw)
                    yield alert
                    yielded += 1
                    if max_alerts and yielded >= max_alerts:
                        return
                except Exception as parse_exc:
                    logger.warning("[intelliclaw] failed to parse alert: %s", parse_exc)

        except requests.exceptions.RequestException as exc:
            logger.warning("[intelliclaw] alert poll failed: %s — retrying in %.1fs", exc, poll_interval)

        time.sleep(poll_interval)


def get_multi_snapshot(
    assets: List[str],
    window_hours: int = 24,
) -> Dict[str, IntelSnapshot]:
    """Convenience wrapper — fetch IntelSnapshot for multiple assets.

    Snapshots for each asset are fetched sequentially (cached where available).
    For high-frequency use, consider parallelising with concurrent.futures.

    Args:
        assets:       List of ticker symbols.
        window_hours: Aggregation window.

    Returns:
        Dict mapping asset symbol -> IntelSnapshot.
        Assets that fail are omitted; errors are logged as warnings.
    """
    results: Dict[str, IntelSnapshot] = {}
    for asset in assets:
        try:
            results[asset] = get_intel_snapshot(asset, window_hours=window_hours)
        except IntelliClawError as exc:
            logger.warning("[intelliclaw] skipping %s: %s", asset, exc)
    return results
