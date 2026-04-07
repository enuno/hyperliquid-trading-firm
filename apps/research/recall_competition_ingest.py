"""
apps/research/recall_competition_ingest.py

Scheduled ingestion job for Recall Network competitions, agents, and portfolio snapshots.
Fetches fresh data from RecallClient, writes to structured SQLite tables, and
notifies MarketIntelligenceSifter via message queue when high-priority candidates
are available.

Run via:
  poetry run python -m apps.research.recall_competition_ingest

Cron schedule:
  * * * * *  # Every minute (lightweight leaderboard check)
  0 */6 * * * # Every 6 hours (full snapshot ingest)

Architecture constraints:
  - Idempotent: safe to run multiple times, no duplicates created
  - Atomic: transactions ensure consistency across tables
  - Lightweight: leaderboard checks < 2s, full ingest < 60s
  - No network calls in critical path — RecallClient handles retries/timeouts
  - Dead-letter queue for failed candidate notifications
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator

import aiosqlite
from dataclasses import dataclass
from typing import Optional

from apps.data
