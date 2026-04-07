"""
apps/agents/src/agents/evolution_curriculum_agent.py
=====================================================
Agent0-pattern curriculum co-evolution for the HyperLiquid Trading Firm
multi-agent orchestration platform.

This module implements THREE co-operating classes:

  CurriculumStrategyAgent
    Proposes difficulty-progressive task batches across six trading-domain
    task families.  Draws from the firm's regime taxonomy, known strategy
    failure modes, and StrategyConfig parameter space to generate scenarios
    that are: (a) objectively verifiable via backtest, (b) monotonically
    increasing in difficulty across rounds, (c) balanced across all task
    families and market regimes.

  EvolutionExecutorAgent
    Solves curriculum tasks using tool-integrated chain-of-thought reasoning.
    Tools: HyperLiquid historical OHLCV feed, funding-rate history, agentharness
    backtest engine, regime classifier.  Reward signal is ALWAYS an objective
    backtest metric (Sharpe/Sortino/Calmar) — never LLM-judged.  This prevents
    reward hacking and ensures ground-truth verifiability.

  EvolutionOrchestrator
    Manages full curriculum rounds end-to-end: task generation -> executor
    solving -> batch scoring -> regression gate -> checkpoint manifest creation
    -> registry persistence.  Implements automatic difficulty progression:
    if solve_rate >= DIFFICULTY_UP_THRESHOLD for two consecutive rounds,
    difficulty advances one tier (max DifficultyLevel.FRONTIER = 5).

  EvolutionScheduler (async entry point)
    Wraps the orchestrator with a configurable cron schedule and sleep-window
    awareness so evolution rounds never interrupt live trading sessions.

SAFETY INVARIANTS — enforced throughout:
  1. No import of SAEMiddleware, execution engine, or live order path.
  2. No writes to strategy.py, apps/agents/src/config/, or any locked file.
  3. All artifact writes are scoped to logs/evolution/artifacts/<round_id>/.
  4. Checkpoint promotion requires approved=True set by a human operator via
     the dashboard or registry REST API — never set automatically here.
  5. Regression gate blocks promotion if Sharpe degrades > REGRESSION_THRESHOLD_PCT.
  6. The curriculum never generates tasks that reference specific price targets,
     guaranteed returns, or outcomes asserted as certain.

Dependencies (all already present or stub-compatible):
  - apps/agents/src/types/evolution.py   (EvolutionTask, SolvedTask, etc.)
  - apps/agents/src/types/research.py    (StrategyMetrics for baseline context)
  - apps/agents/src/tools/market_data.py (OHLCV + funding history stubs)
  - apps/agents/src/tools/intelliclaw_client.py (IntelliClaw snapshot)
  - Python stdlib: asyncio, dataclasses, datetime, hashlib, json, logging,
    os, pathlib, random, sqlite3

LLM calls are made via a thin async wrapper (LLMClient) that reads the
firm's LLM endpoint configuration from environment variables:
  HL_LLM_BASE_URL   — OpenAI-compatible chat completions endpoint
  HL_LLM_API_KEY    — API key (never hardcoded)
  HL_LLM_MODEL_ID   — Model identifier (default: moonshotai/Kimi-K2.5)

If these are unset, LLMClient falls back to a deterministic stub that returns
predefined scenario templates — safe for unit testing without a live LLM.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..types.evolution import (
    CheckpointManifest,
    DifficultyLevel,
    EvolutionRegistryEntry,
    EvolutionRound,
    EvolutionStatus,
    EvolutionTask,
    RegressionResult,
    SolvedTask,
    TaskBatch,
    TaskFamily,
)
from ..types.research import StrategyMetrics

# ---------------------------------------------------------------------------
# Module-level configuration
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# Root path for all evolution artefacts — relative to project root.
_EVOLUTION_ROOT = Path("logs/evolution")
_ARTIFACTS_DIR = _EVOLUTION_ROOT / "artifacts"
_REGISTRY_DB = _EVOLUTION_ROOT / "evolution_registry.db"
_REGISTRY_SUMMARY = _EVOLUTION_ROOT / "registry_summary.json"

# Difficulty auto-progression: if solve_rate_pct >= this threshold for
# CONSECUTIVE_ROUNDS_FOR_PROMOTION consecutive rounds, difficulty advances.
DIFFICULTY_UP_THRESHOLD: float = 80.0
CONSECUTIVE_ROUNDS_FOR_PROMOTION: int = 2

# Regression gate: checkpoint is blocked if any listed metric degrades
# more than REGRESSION_THRESHOLD_PCT percent vs. production baseline.
REGRESSION_THRESHOLD_PCT: float = 10.0

# Default task batch size per round.
DEFAULT_BATCH_SIZE: int = 12

# Default lookback window for backtest oracle.
DEFAULT_LOOKBACK_DAYS: int = 30

# Regime taxonomy — mirrors marketstructure.yaml.  Tasks are distributed
# across these regimes to ensure coverage across market conditions.
_REGIME_TAXONOMY: list[str] = [
    "trending_bull",
    "trending_bear",
    "ranging_low_vol",
    "ranging_high_vol",
    "high_funding_contango",
    "backwardation_squeeze",
    "liquidation_cascade_precursor",
    "post_liquidation_recovery",
]

# Instruments available on HyperLiquid perps.
_HL_PERP_INSTRUMENTS: list[str] = [
    "BTC-PERP", "ETH-PERP", "SOL-PERP", "ARB-PERP",
    "AVAX-PERP", "MATIC-PERP", "APT-PERP", "INJ-PERP",
    "SUI-PERP", "OP-PERP",
]

# Families and the minimum difficulty at which multi-asset scenarios appear.
_MULTI_ASSET_MIN_DIFFICULTY: dict[str, int] = {
    TaskFamily.MULTI_ASSET_BASIS.value: 1,     # always multi-asset
    TaskFamily.LIQUIDATION_CASCADE.value: 3,   # multi-asset at ADVANCED+
    TaskFamily.FUNDING_CARRY.value: 2,          # multi-asset at INTERMEDIATE+
}


# ---------------------------------------------------------------------------
# Lightweight LLM client wrapper
# ---------------------------------------------------------------------------

class _LLMClient:
    """
    Thin async wrapper around an OpenAI-compatible chat completions endpoint.

    Reads configuration from environment variables.  Falls back to a
    deterministic stub when the endpoint is not configured, so the module
    is fully testable without a live LLM.
    """

    def __init__(self) -> None:
        self.base_url = os.environ.get("HL_LLM_BASE_URL", "")
        self.api_key = os.environ.get("HL_LLM_API_KEY", "")
        self.model_id = os.environ.get("HL_LLM_MODEL_ID", "moonshotai/Kimi-K2.5")
        self._stub_mode = not (self.base_url and self.api_key)
        if self._stub_mode:
            logger.warning(
                "_LLMClient: HL_LLM_BASE_URL or HL_LLM_API_KEY not set — "
                "running in deterministic stub mode (no live LLM calls)."
            )

    async def chat(self, system: str, user: str, temperature: float = 0.7) -> str:
        """
        Send a chat completion request and return the assistant message text.

        In stub mode, returns a JSON-serialised placeholder response that
        satisfies the expected schema for tests and CI.
        """
        if self._stub_mode:
            return self._stub_response(user)

        try:
            import aiohttp  # optional — only needed for live LLM calls
        except ImportError as exc:
            raise RuntimeError(
                "aiohttp is required for live LLM calls: pip install aiohttp"
            ) from exc

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data["choices"][0]["message"]["content"]

    @staticmethod
    def _stub_response(user_prompt: str) -> str:
        """
        Deterministic stub that returns minimal valid JSON for both the
        curriculum (task list) and executor (solution) response schemas.
        Keyed by presence of discriminating keywords in the prompt.
        """
        if "propose" in user_prompt.lower() or "curriculum" in user_prompt.lower():
            return json.dumps({
                "tasks": [
                    {
                        "family": TaskFamily.REGIME_DETECTION.value,
                        "scenario": "[STUB] Classify the current BTC-PERP regime from 4h OHLCV + funding rate data.",
                        "instruments": ["BTC-PERP"],
                        "regime_context": "trending_bull",
                        "lookback_days": 30,
                        "verification_metric": "sharpe",
                        "verification_threshold": 0.5,
                        "parameter_space": {"ema_fast": [8, 21], "ema_slow": [50, 200]},
                    }
                ]
            })
        return json.dumps({
            "reasoning_trace": ["[STUB] Step 1: Fetch OHLCV.", "[STUB] Step 2: Run backtest."],
            "strategy_params": {"ema_fast": 12, "ema_slow": 100},
            "tool_calls": [],
        })


# ---------------------------------------------------------------------------
# Simulated backtest oracle
# ---------------------------------------------------------------------------

class _BacktestOracle:
    """
    Wraps the agentharness backtest engine (apps/agents/src/strategies/).

    In the current scaffold, the real harness integration is stubbed with a
    deterministic simulator that produces plausible metric ranges keyed on
    difficulty.  Replace _run_harness_stub() with the real harness call once
    apps/agents/src/strategies/ backtest API is finalised.

    The oracle is the ONLY source of reward signal for the executor.
    No LLM judges the quality of executor outputs — all rewards are
    objective backtest metrics.
    """

    async def run(
        self,
        instruments: list[str],
        strategy_params: dict[str, Any],
        lookback_days: int,
        regime_context: str,
    ) -> dict[str, float | int]:
        """
        Run a backtest for the given strategy params and return metrics dict.

        Returns
        -------
        dict with keys: sharpe, sortino, calmar, max_drawdown_pct,
                        win_rate_pct, n_trades
        """
        # TODO: replace stub with real agentharness call:
        #   from ..strategies.agentharness import run_backtest
        #   return await run_backtest(instruments, strategy_params, lookback_days)
        return await self._run_harness_stub(instruments, strategy_params, lookback_days, regime_context)

    @staticmethod
    async def _run_harness_stub(
        instruments: list[str],
        strategy_params: dict[str, Any],
        lookback_days: int,
        regime_context: str,
    ) -> dict[str, float | int]:
        """
        Deterministic stub backtest.  Produces metrics in plausible ranges,
        seeded from the strategy_params hash for reproducibility.
        """
        await asyncio.sleep(0)  # yield to event loop
        seed_str = json.dumps(strategy_params, sort_keys=True) + regime_context
        seed = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % (2**31)
        rng = random.Random(seed)

        # Trending regimes produce better metrics on average.
        base_sharpe = 0.9 if "trending" in regime_context else 0.4
        sharpe = round(base_sharpe + rng.uniform(-0.3, 0.8), 3)
        sortino = round(sharpe * rng.uniform(1.1, 1.6), 3)
        calmar = round(sharpe * rng.uniform(0.4, 0.9), 3)
        max_dd = round(rng.uniform(5.0, 25.0), 2)
        win_rate = round(rng.uniform(42.0, 68.0), 1)
        n_trades = rng.randint(15, 120)

        return {
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "max_drawdown_pct": max_dd,
            "win_rate_pct": win_rate,
            "n_trades": n_trades,
        }


# ---------------------------------------------------------------------------
# Registry persistence
# ---------------------------------------------------------------------------

class _EvolutionRegistry:
    """
    SQLite-backed registry for evolution rounds.

    Schema mirrors the research registry pattern from research_agent.py.
    All writes are atomic; the JSON summary is updated after every state
    transition for live dashboard consumption.
    """

    def __init__(self, db_path: Path = _REGISTRY_DB, summary_path: Path = _REGISTRY_SUMMARY) -> None:
        self.db_path = db_path
        self.summary_path = summary_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS evolution_rounds (
                    round_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    difficulty INTEGER NOT NULL,
                    solve_rate_pct REAL DEFAULT 0.0,
                    mean_sharpe REAL,
                    checkpoint_approved INTEGER,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    json_blob TEXT NOT NULL
                )
            """)
            conn.commit()

    def upsert_round(self, rnd: EvolutionRound) -> None:
        """Insert or update a round record and refresh the JSON summary."""
        approved = None
        if rnd.checkpoint_manifest:
            approved = int(rnd.checkpoint_manifest.approved)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO evolution_rounds
                  (round_id, status, difficulty, solve_rate_pct,
                   mean_sharpe, checkpoint_approved, started_at,
                   completed_at, json_blob)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(round_id) DO UPDATE SET
                  status=excluded.status,
                  difficulty=excluded.difficulty,
                  solve_rate_pct=excluded.solve_rate_pct,
                  mean_sharpe=excluded.mean_sharpe,
                  checkpoint_approved=excluded.checkpoint_approved,
                  started_at=excluded.started_at,
                  completed_at=excluded.completed_at,
                  json_blob=excluded.json_blob
            """, (
                rnd.round_id,
                rnd.status.value,
                rnd.difficulty.value,
                rnd.solve_rate_pct,
                rnd.mean_sharpe,
                approved,
                rnd.started_at,
                rnd.completed_at,
                json.dumps(rnd.to_dict()),
            ))
            conn.commit()
        self._refresh_summary()

    def list_rounds(self, limit: int = 50) -> list[EvolutionRegistryEntry]:
        """Return the most recent N rounds as lightweight registry entries."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT round_id, status, difficulty, solve_rate_pct,
                       mean_sharpe, checkpoint_approved, started_at, completed_at
                FROM evolution_rounds
                ORDER BY started_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return [
            EvolutionRegistryEntry(
                round_id=r[0],
                status=r[1],
                difficulty=r[2],
                solve_rate_pct=r[3],
                mean_sharpe=r[4],
                checkpoint_approved=bool(r[5]) if r[5] is not None else None,
                started_at=r[6],
                completed_at=r[7],
            )
            for r in rows
        ]

    def get_round(self, round_id: str) -> EvolutionRound | None:
        """Fetch a full EvolutionRound from the json_blob column."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT json_blob FROM evolution_rounds WHERE round_id = ?",
                (round_id,),
            ).fetchone()
        if not row:
            return None
        return EvolutionRound.from_dict(json.loads(row[0]))

    def get_current_difficulty(self) -> DifficultyLevel:
        """
        Determine the difficulty level for the next round.

        Auto-progression rule: if the last CONSECUTIVE_ROUNDS_FOR_PROMOTION
        completed rounds all have solve_rate_pct >= DIFFICULTY_UP_THRESHOLD,
        advance difficulty by one tier (capped at FRONTIER).
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT difficulty, solve_rate_pct
                FROM evolution_rounds
                WHERE status = 'complete'
                ORDER BY started_at DESC
                LIMIT ?
            """, (CONSECUTIVE_ROUNDS_FOR_PROMOTION,)).fetchall()

        if not rows:
            return DifficultyLevel.BASIC

        last_difficulty = rows[0][0]
        all_high = all(
            r[1] >= DIFFICULTY_UP_THRESHOLD for r in rows
        ) and len(rows) == CONSECUTIVE_ROUNDS_FOR_PROMOTION

        if all_high:
            next_d = min(last_difficulty + 1, DifficultyLevel.FRONTIER.value)
            logger.info(
                "Difficulty auto-progression: %d -> %d "
                "(solve_rate >= %.1f%% for %d consecutive rounds)",
                last_difficulty, next_d,
                DIFFICULTY_UP_THRESHOLD, CONSECUTIVE_ROUNDS_FOR_PROMOTION,
            )
            return DifficultyLevel(next_d)
        return DifficultyLevel(last_difficulty)

    def get_baseline_metrics(self) -> dict[str, float]:
        """
        Return the production baseline metrics for the regression gate.

        Reads from the most recent COMPLETE round's mean_sharpe as a proxy.
        In production, this should read from the live strategy performance
        dashboard (SAE middleware reporting path) — never from the execution
        path directly.
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("""
                SELECT mean_sharpe FROM evolution_rounds
                WHERE status = 'complete' AND mean_sharpe IS NOT NULL
                ORDER BY started_at DESC LIMIT 1
            """).fetchone()
        return {"sharpe": row[0] if row else 0.8, "max_drawdown_pct": 15.0}

    def _refresh_summary(self) -> None:
        """Regenerate registry_summary.json from recent rounds."""
        entries = self.list_rounds(limit=100)
        summary = {
            "generated_at": _utcnow(),
            "total_rounds": len(entries),
            "rounds": [e.to_dict() for e in entries],
        }
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)
        self.summary_path.write_text(json.dumps(summary, indent=2))


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _make_round_id() -> str:
    """Generate a unique round ID."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = hashlib.md5(str(random.random()).encode()).hexdigest()[:8]
    return f"evround_{ts}_{suffix}"


def _make_task_id(round_id: str, idx: int) -> str:
    """Generate a unique task ID within a round."""
    suffix = hashlib.md5(f"{round_id}_{idx}".encode()).hexdigest()[:8]
    return f"evtask_{round_id}_{suffix}"


# ---------------------------------------------------------------------------
# CurriculumStrategyAgent
# ---------------------------------------------------------------------------

class CurriculumStrategyAgent:
    """
    Proposes difficulty-progressive task batches for the executor to solve.

    Design principles (from Agent0 paper):
      - Tasks are drawn from the frontier of current agent capability — not
        so easy they provide no training signal, not so hard they are unsolvable.
      - Each batch covers all TaskFamily values and samples from all regimes
        to ensure broad coverage, not specialisation on recent conditions.
      - Tasks are phrased as objective scenarios with measurable success criteria
        (verification_metric + verification_threshold) that the backtest oracle
        can evaluate without human judgment.
      - The curriculum never generates tasks asserting specific price outcomes,
        guaranteed profit, or legally constrained investment advice.

    Parameters
    ----------
    llm:
        Injected _LLMClient instance.  Defaults to a fresh instance reading
        credentials from environment variables.
    batch_size:
        Number of tasks to propose per round (default: DEFAULT_BATCH_SIZE).
    """

    _SYSTEM_PROMPT = """\
You are the CurriculumStrategyAgent for an institutional-grade HyperLiquid
perpetual futures trading firm.

Your role: propose a batch of trading-domain curriculum tasks for the
EvolutionExecutorAgent to solve.  Each task must be:
  - Objectively verifiable via a backtest oracle (Sharpe/Sortino/Calmar).
  - Grounded in real market microstructure — no synthetic or invented data.
  - Within the specified difficulty tier and task family.
  - Free of specific price predictions, guaranteed returns, or investment advice.

Respond ONLY with a JSON object in this exact schema:
{
  "tasks": [
    {
      "family": "<TaskFamily value>",
      "scenario": "<plain-language scenario for the executor>",
      "instruments": ["<HL perp tickers>"],
      "regime_context": "<regime label>",
      "lookback_days": <int>,
      "verification_metric": "<sharpe|sortino|calmar|max_drawdown_pct|win_rate_pct>",
      "verification_threshold": <float>,
      "parameter_space": {"<param_name>": [<min>, <max>]}
    }
  ]
}
"""

    def __init__(
        self,
        llm: _LLMClient | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._llm = llm or _LLMClient()
        self.batch_size = batch_size

    async def propose_task_batch(
        self,
        round_id: str,
        difficulty: DifficultyLevel,
        strategy_metrics: StrategyMetrics | None = None,
    ) -> TaskBatch:
        """
        Generate a task batch for the given difficulty level.

        Parameters
        ----------
        round_id:
            EvolutionRound identifier to embed in all task IDs.
        difficulty:
            Difficulty tier for all tasks in the batch.
        strategy_metrics:
            Optional current strategy performance snapshot.  Used to focus
            curriculum on the specific failure modes most relevant to the
            current performance envelope (mirrors STRATEGY_SCAN research mode).
        """
        logger.info(
            "CurriculumStrategyAgent: proposing batch of %d tasks "
            "at difficulty=%s for round=%s",
            self.batch_size, difficulty.name, round_id,
        )

        # Build the user prompt: request tasks covering all families and regimes.
        family_spec = [
            f"{f.value} (difficulty {difficulty.value})" for f in TaskFamily
        ]
        regime_spec = random.sample(_REGIME_TAXONOMY, min(len(_REGIME_TAXONOMY), self.batch_size))

        perf_context = ""
        if strategy_metrics:
            perf_context = (
                f"\nCurrent strategy performance context:\n"
                f"  Sharpe: {strategy_metrics.sharpe:.2f}\n"
                f"  Max drawdown: {strategy_metrics.max_drawdown_pct:.1f}%\n"
                f"  Win rate: {strategy_metrics.win_rate_pct:.1f}%\n"
                f"  Current regime: {strategy_metrics.regime_label}\n"
                f"Bias tasks toward failure modes relevant to this performance envelope."
            )

        user_prompt = (
            f"Propose exactly {self.batch_size} curriculum tasks.\n"
            f"Difficulty tier: {difficulty.name} ({difficulty.value}/5)\n"
            f"Required task families (at least one task per family):\n"
            + "\n".join(f"  - {s}" for s in family_spec)
            + f"\nRequired regime distribution (cover all listed):\n"
            + "\n".join(f"  - {r}" for r in regime_spec)
            + perf_context
        )

        raw = await self._llm.chat(
            system=self._SYSTEM_PROMPT,
            user=user_prompt,
            temperature=0.7,
        )

        tasks = self._parse_tasks(raw, round_id, difficulty)

        # Compute distribution stats.
        regime_dist: dict[str, int] = {}
        family_dist: dict[str, int] = {}
        for t in tasks:
            regime_dist[t.regime_context] = regime_dist.get(t.regime_context, 0) + 1
            family_dist[t.family.value] = family_dist.get(t.family.value, 0) + 1

        batch = TaskBatch(
            round_id=round_id,
            difficulty=difficulty,
            tasks=tasks,
            regime_distribution=regime_dist,
            family_distribution=family_dist,
            created_at=_utcnow(),
        )
        logger.info(
            "CurriculumStrategyAgent: batch ready — %d tasks, "
            "families=%s, regimes=%s",
            len(tasks), family_dist, regime_dist,
        )
        return batch

    def _parse_tasks(
        self,
        raw: str,
        round_id: str,
        difficulty: DifficultyLevel,
    ) -> list[EvolutionTask]:
        """Parse LLM JSON output into EvolutionTask objects."""
        try:
            data = json.loads(raw)
            task_dicts = data["tasks"]
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(
                "CurriculumStrategyAgent: failed to parse LLM response — %s\nRaw: %s",
                exc, raw[:500],
            )
            task_dicts = self._fallback_task_dicts(difficulty)

        tasks: list[EvolutionTask] = []
        for idx, td in enumerate(task_dicts[: self.batch_size]):
            try:
                family = TaskFamily(td["family"])
                tasks.append(EvolutionTask(
                    task_id=_make_task_id(round_id, idx),
                    round_id=round_id,
                    family=family,
                    difficulty=difficulty,
                    scenario=str(td["scenario"]),
                    instruments=list(td.get("instruments", ["BTC-PERP"])),
                    regime_context=str(td.get("regime_context", "trending_bull")),
                    lookback_days=int(td.get("lookback_days", DEFAULT_LOOKBACK_DAYS)),
                    verification_metric=str(td.get("verification_metric", "sharpe")),
                    verification_threshold=float(td.get("verification_threshold", 0.5)),
                    parameter_space=dict(td.get("parameter_space", {})),
                    created_at=_utcnow(),
                ))
            except (KeyError, ValueError) as exc:
                logger.warning("CurriculumStrategyAgent: skipping malformed task %d — %s", idx, exc)

        if not tasks:
            logger.error("CurriculumStrategyAgent: no valid tasks parsed — using fallback batch.")
            tasks = self._build_fallback_tasks(round_id, difficulty)

        return tasks

    @staticmethod
    def _fallback_task_dicts(difficulty: DifficultyLevel) -> list[dict]:
        """Minimal deterministic fallback task dicts for CI / stub mode."""
        return [
            {
                "family": fam.value,
                "scenario": f"[FALLBACK] {fam.value} task at difficulty {difficulty.value}.",
                "instruments": ["BTC-PERP"],
                "regime_context": regime,
                "lookback_days": DEFAULT_LOOKBACK_DAYS,
                "verification_metric": "sharpe",
                "verification_threshold": 0.3 * difficulty.value,
                "parameter_space": {},
            }
            for fam, regime in zip(TaskFamily, _REGIME_TAXONOMY)
        ]

    def _build_fallback_tasks(self, round_id: str, difficulty: DifficultyLevel) -> list[EvolutionTask]:
        """Build EvolutionTask objects from the fallback task dicts."""
        tasks = []
        for idx, td in enumerate(self._fallback_task_dicts(difficulty)):
            tasks.append(EvolutionTask(
                task_id=_make_task_id(round_id, idx),
                round_id=round_id,
                family=TaskFamily(td["family"]),
                difficulty=difficulty,
                scenario=td["scenario"],
                instruments=td["instruments"],
                regime_context=td["regime_context"],
                lookback_days=DEFAULT_LOOKBACK_DAYS,
                verification_metric="sharpe",
                verification_threshold=td["verification_threshold"],
                parameter_space={},
                created_at=_utcnow(),
            ))
        return tasks


# ---------------------------------------------------------------------------
# EvolutionExecutorAgent
# ---------------------------------------------------------------------------

class EvolutionExecutorAgent:
    """
    Solves curriculum tasks via tool-integrated chain-of-thought reasoning.

    The executor follows a three-phase loop for each task:
      1. THINK: Reason over the scenario using available trading-domain tools.
      2. ACT:   Call tools to gather market data, classify regime, run backtest.
      3. SCORE: Extract the objective verification metric from the backtest
                result and compare to the task threshold — no LLM scoring.

    Reward signal is always objective backtest metrics from _BacktestOracle.
    The executor's chain-of-thought reasoning trace is stored for:
      - Curriculum refinement (CurriculumStrategyAgent difficulty calibration)
      - MetaClaw skills extraction (skills library seeding)

    Parameters
    ----------
    llm:
        Injected _LLMClient instance.
    oracle:
        Injected _BacktestOracle instance.
    max_retries:
        Number of times the executor will retry a failed task with a revised
        strategy_params before marking it as unsolved (default: 2).
    """

    _SYSTEM_PROMPT = """\
You are the EvolutionExecutorAgent for an institutional-grade HyperLiquid
perpetual futures trading firm.

Your role: solve a curriculum task by reasoning step-by-step and proposing
a concrete set of strategy parameters to be evaluated by the backtest oracle.

Available tools (call by naming them in your reasoning):
  - fetch_ohlcv(instrument, interval, lookback_days) -> candles
  - fetch_funding_history(instrument, lookback_days) -> funding rates
  - fetch_open_interest(instrument, lookback_days) -> OI history
  - classify_regime(ohlcv, funding, oi) -> regime_label
  - compute_kelly_fraction(sharpe, win_rate, avg_win_loss_ratio) -> fraction

Think step by step.  Your final output must be a JSON object:
{
  "reasoning_trace": ["step 1 ...", "step 2 ..."],
  "strategy_params": {"<param_name>": <value>},
  "tool_calls": [{"tool": "<name>", "args": {}, "result": "<summary>"}]
}

Do not assert specific price targets or guaranteed outcomes.  Work only
from the scenario description and tool outputs.
"""

    def __init__(
        self,
        llm: _LLMClient | None = None,
        oracle: _BacktestOracle | None = None,
        max_retries: int = 2,
    ) -> None:
        self._llm = llm or _LLMClient()
        self._oracle = oracle or _BacktestOracle()
        self.max_retries = max_retries

    async def solve(self, task: EvolutionTask) -> SolvedTask:
        """
        Attempt to solve a curriculum task.

        Runs up to max_retries + 1 attempts, each with a progressively
        narrower parameter space hint to guide the executor toward a
        passing solution.  Returns the best-scoring SolvedTask.
        """
        logger.info(
            "EvolutionExecutorAgent: solving task=%s family=%s difficulty=%s",
            task.task_id, task.family.name, task.difficulty.name,
        )

        best: SolvedTask | None = None

        for attempt in range(self.max_retries + 1):
            candidate = await self._solve_attempt(task, attempt)
            if best is None or (candidate.sharpe or -999) > (best.sharpe or -999):
                best = candidate
            if candidate.solved:
                break
            logger.debug(
                "EvolutionExecutorAgent: task=%s attempt=%d unsolved "
                "(metric=%s=%.3f < threshold=%.3f), retrying...",
                task.task_id, attempt,
                task.verification_metric,
                getattr(candidate, task.verification_metric) or 0.0,
                task.verification_threshold,
            )

        assert best is not None  # always set after first iteration
        return best

    async def _solve_attempt(self, task: EvolutionTask, attempt: int) -> SolvedTask:
        """Single solve attempt — returns a SolvedTask with backtest metrics."""
        retry_hint = (
            f"\n[Attempt {attempt + 1}/{self.max_retries + 1}] "
            "Adjust your strategy parameters to achieve a higher result."
            if attempt > 0 else ""
        )

        user_prompt = (
            f"Task ID: {task.task_id}\n"
            f"Family: {task.family.value}\n"
            f"Difficulty: {task.difficulty.name}\n"
            f"Instruments: {', '.join(task.instruments)}\n"
            f"Regime context: {task.regime_context}\n"
            f"Lookback: {task.lookback_days} days\n"
            f"Scenario:\n{task.scenario}\n\n"
            f"Success criterion: {task.verification_metric} >= {task.verification_threshold}\n"
            f"Parameter search space: {json.dumps(task.parameter_space)}\n"
            + retry_hint
        )

        raw = await self._llm.chat(
            system=self._SYSTEM_PROMPT,
            user=user_prompt,
            temperature=max(0.3, 0.7 - attempt * 0.2),  # reduce temperature on retries
        )

        reasoning_trace: list[str] = []
        strategy_params: dict[str, Any] = {}
        tool_calls: list[dict[str, Any]] = []
        error: str | None = None

        try:
            parsed = json.loads(raw)
            reasoning_trace = list(parsed.get("reasoning_trace", []))
            strategy_params = dict(parsed.get("strategy_params", {}))
            tool_calls = list(parsed.get("tool_calls", []))
        except (json.JSONDecodeError, TypeError) as exc:
            error = f"Failed to parse executor response: {exc}"
            logger.warning("EvolutionExecutorAgent: task=%s parse error — %s", task.task_id, error)

        # Run the backtest oracle — this is the ONLY reward signal.
        backtest_metrics: dict[str, Any] = {}
        if strategy_params:
            try:
                backtest_metrics = await self._oracle.run(
                    instruments=task.instruments,
                    strategy_params=strategy_params,
                    lookback_days=task.lookback_days,
                    regime_context=task.regime_context,
                )
            except Exception as exc:  # noqa: BLE001
                error = f"Backtest oracle error: {exc}"
                logger.error("EvolutionExecutorAgent: task=%s oracle error — %s", task.task_id, exc)

        # Evaluate objective pass/fail against verification criterion.
        metric_value = backtest_metrics.get(task.verification_metric)
        solved = (
            metric_value is not None
            and float(metric_value) >= task.verification_threshold
        )

        return SolvedTask(
            task_id=task.task_id,
            round_id=task.round_id,
            solved=solved,
            reasoning_trace=reasoning_trace,
            strategy_params=strategy_params if strategy_params else None,
            sharpe=backtest_metrics.get("sharpe"),
            sortino=backtest_metrics.get("sortino"),
            calmar=backtest_metrics.get("calmar"),
            max_drawdown_pct=backtest_metrics.get("max_drawdown_pct"),
            win_rate_pct=backtest_metrics.get("win_rate_pct"),
            n_trades=backtest_metrics.get("n_trades"),
            tool_calls=tool_calls,
            error=error,
            solved_at=_utcnow(),
        )


# ---------------------------------------------------------------------------
# EvolutionOrchestrator
# ---------------------------------------------------------------------------

class EvolutionOrchestrator:
    """
    Manages full curriculum rounds end-to-end.

    Lifecycle of a round:
      1. CURRICULUM_GENERATION  — CurriculumStrategyAgent proposes TaskBatch
      2. EXECUTOR_SOLVING        — EvolutionExecutorAgent solves each task
      3. SCORING                 — aggregate metrics from SolvedTask results
      4. REGRESSION_CHECK        — compare evolved metrics vs. baseline
      5. GATE_PENDING            — persist CheckpointManifest (approved=False)
      6. COMPLETE / REGRESSION_FAILED

    All artefacts are written under logs/evolution/artifacts/<round_id>/.
    No writes to strategy.py, config/, or any locked file.

    Parameters
    ----------
    curriculum:
        Injected CurriculumStrategyAgent.
    executor:
        Injected EvolutionExecutorAgent.
    registry:
        Injected _EvolutionRegistry.
    regression_threshold_pct:
        Sharpe degradation threshold for the regression gate.
    """

    def __init__(
        self,
        curriculum: CurriculumStrategyAgent | None = None,
        executor: EvolutionExecutorAgent | None = None,
        registry: _EvolutionRegistry | None = None,
        regression_threshold_pct: float = REGRESSION_THRESHOLD_PCT,
        base_model_id: str = "moonshotai/Kimi-K2.5",
    ) -> None:
        self._curriculum = curriculum or CurriculumStrategyAgent()
        self._executor = executor or EvolutionExecutorAgent()
        self._registry = registry or _EvolutionRegistry()
        self._regression_threshold_pct = regression_threshold_pct
        self._base_model_id = base_model_id

    async def run_round(
        self,
        strategy_metrics: StrategyMetrics | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> EvolutionRound:
        """
        Execute a full curriculum round and return the completed EvolutionRound.

        Parameters
        ----------
        strategy_metrics:
            Optional current strategy performance snapshot passed to the
            curriculum agent for failure-mode-focused task generation.
        batch_size:
            Override the default batch size for this round.
        """
        difficulty = self._registry.get_current_difficulty()
        round_id = _make_round_id()
        artifact_dir = _ARTIFACTS_DIR / round_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        rnd = EvolutionRound(
            round_id=round_id,
            difficulty=difficulty,
            status=EvolutionStatus.CURRICULUM_GENERATION,
            task_count=batch_size,
            artifact_dir=str(artifact_dir),
            started_at=_utcnow(),
            updated_at=_utcnow(),
        )
        self._registry.upsert_round(rnd)
        logger.info("EvolutionOrchestrator: started round=%s difficulty=%s", round_id, difficulty.name)

        try:
            # --- Stage 1: Curriculum generation ---
            self._curriculum.batch_size = batch_size
            batch = await self._curriculum.propose_task_batch(
                round_id=round_id,
                difficulty=difficulty,
                strategy_metrics=strategy_metrics,
            )
            self._write_jsonl(artifact_dir / "curriculum_tasks.jsonl", [t.to_dict() for t in batch.tasks])
            rnd.task_count = len(batch.tasks)
            rnd.status = EvolutionStatus.EXECUTOR_SOLVING
            rnd.updated_at = _utcnow()
            self._registry.upsert_round(rnd)

            # --- Stage 2: Executor solving ---
            solved_tasks = await self._solve_all(batch.tasks)
            self._write_jsonl(artifact_dir / "solved_tasks.jsonl", [s.to_dict() for s in solved_tasks])

            # --- Stage 3: Scoring ---
            rnd.status = EvolutionStatus.SCORING
            rnd.updated_at = _utcnow()
            self._registry.upsert_round(rnd)

            solved_count = sum(1 for s in solved_tasks if s.solved)
            sharpe_values = [s.sharpe for s in solved_tasks if s.sharpe is not None]
            sortino_values = [s.sortino for s in solved_tasks if s.sortino is not None]

            rnd.solved_count = solved_count
            rnd.solve_rate_pct = (
                solved_count / len(batch.tasks) * 100.0 if batch.tasks else 0.0
            )
            rnd.mean_sharpe = (
                sum(sharpe_values) / len(sharpe_values) if sharpe_values else None
            )
            rnd.mean_sortino = (
                sum(sortino_values) / len(sortino_values) if sortino_values else None
            )

            logger.info(
                "EvolutionOrchestrator: round=%s scored — "
                "solve_rate=%.1f%% mean_sharpe=%.3f",
                round_id, rnd.solve_rate_pct, rnd.mean_sharpe or 0.0,
            )

            # --- Stage 4: Regression gate ---
            rnd.status = EvolutionStatus.REGRESSION_CHECK
            rnd.updated_at = _utcnow()
            self._registry.upsert_round(rnd)

            regression = self._run_regression_gate(round_id, rnd.mean_sharpe or 0.0)
            rnd.regression_result = regression
            (artifact_dir / "regression_result.json").write_text(
                json.dumps(regression.to_dict(), indent=2)
            )

            if not regression.passed:
                rnd.status = EvolutionStatus.REGRESSION_FAILED
                rnd.updated_at = _utcnow()
                rnd.completed_at = _utcnow()
                self._registry.upsert_round(rnd)
                logger.warning(
                    "EvolutionOrchestrator: round=%s REGRESSION_FAILED — "
                    "blocking_metrics=%s",
                    round_id, regression.blocking_metrics,
                )
                return rnd

            # --- Stage 5: Checkpoint manifest (human gate) ---
            rnd.status = EvolutionStatus.GATE_PENDING
            rnd.updated_at = _utcnow()

            manifest = CheckpointManifest(
                round_id=round_id,
                checkpoint_path=str(artifact_dir / "checkpoint.pt"),
                base_model_id=self._base_model_id,
                training_task_count=solved_count,
                mean_sharpe=rnd.mean_sharpe or 0.0,
                mean_sortino=rnd.mean_sortino or 0.0,
                solve_rate_pct=rnd.solve_rate_pct,
                regression_result=regression,
                approved=False,   # NEVER auto-approved — human gate
                created_at=_utcnow(),
            )
            rnd.checkpoint_manifest = manifest
            (artifact_dir / "checkpoint_manifest.json").write_text(
                json.dumps(manifest.to_dict(), indent=2)
            )

            rnd.status = EvolutionStatus.COMPLETE
            rnd.completed_at = _utcnow()
            rnd.updated_at = _utcnow()
            self._registry.upsert_round(rnd)

            logger.info(
                "EvolutionOrchestrator: round=%s COMPLETE — "
                "checkpoint at %s (approved=False, awaiting human gate)",
                round_id, manifest.checkpoint_path,
            )
            return rnd

        except Exception as exc:  # noqa: BLE001
            logger.exception("EvolutionOrchestrator: round=%s FAILED — %s", round_id, exc)
            rnd.status = EvolutionStatus.FAILED
            rnd.error = str(exc)
            rnd.updated_at = _utcnow()
            rnd.completed_at = _utcnow()
            self._registry.upsert_round(rnd)
            return rnd

    async def _solve_all(self, tasks: list[EvolutionTask]) -> list[SolvedTask]:
        """Solve all tasks concurrently (bounded by a semaphore)."""
        sem = asyncio.Semaphore(4)  # max 4 concurrent executor calls

        async def _bounded(task: EvolutionTask) -> SolvedTask:
            async with sem:
                return await self._executor.solve(task)

        return list(await asyncio.gather(*[_bounded(t) for t in tasks]))

    def _run_regression_gate(
        self,
        round_id: str,
        evolved_sharpe: float,
    ) -> RegressionResult:
        """Compare evolved metrics against production baseline and gate."""
        baseline = self._registry.get_baseline_metrics()
        baseline_sharpe: float = baseline["sharpe"]
        baseline_dd: float = baseline["max_drawdown_pct"]

        sharpe_delta_pct = (
            (evolved_sharpe - baseline_sharpe) / abs(baseline_sharpe) * 100.0
            if baseline_sharpe != 0
            else 0.0
        )

        blocking: list[str] = []
        if sharpe_delta_pct < -self._regression_threshold_pct:
            blocking.append("sharpe")

        passed = len(blocking) == 0
        return RegressionResult(
            round_id=round_id,
            passed=passed,
            baseline_sharpe=baseline_sharpe,
            evolved_sharpe=evolved_sharpe,
            sharpe_delta_pct=round(sharpe_delta_pct, 2),
            baseline_max_drawdown_pct=baseline_dd,
            evolved_max_drawdown_pct=baseline_dd,  # placeholder until real harness integration
            regression_threshold_pct=self._regression_threshold_pct,
            blocking_metrics=blocking,
            evaluated_at=_utcnow(),
        )

    @staticmethod
    def _write_jsonl(path: Path, records: list[dict]) -> None:
        """Write a list of dicts as newline-delimited JSON."""
        with open(path, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------------------
# EvolutionScheduler (async entry point)
# ---------------------------------------------------------------------------

class EvolutionScheduler:
    """
    Async entry point for scheduled evolution rounds.

    Wraps EvolutionOrchestrator with:
      - Configurable cron-style interval (default: weekly, Sunday 22:00 UTC)
      - Sleep-window awareness: refuses to start a round during configured
        trading-session hours to avoid any latency impact on live agents
      - Consecutive failure backoff: doubles the wait interval after each
        failed round, up to max_backoff_hours

    Usage::

        scheduler = EvolutionScheduler()
        await scheduler.start()  # runs indefinitely

    Or for a single one-shot run (e.g. K8s batch job)::

        orchestrator = EvolutionOrchestrator()
        round_result = await orchestrator.run_round()

    Parameters
    ----------
    interval_hours:
        Hours between evolution rounds (default: 168 = weekly).
    sleep_start_hour:
        UTC hour at which the sleep window begins (exclusive of round starts).
    sleep_end_hour:
        UTC hour at which the sleep window ends.
    max_backoff_hours:
        Maximum backoff interval after consecutive failures.
    """

    def __init__(
        self,
        interval_hours: float = 168.0,
        sleep_start_hour: int = 22,
        sleep_end_hour: int = 7,
        max_backoff_hours: float = 72.0,
        orchestrator: EvolutionOrchestrator | None = None,
    ) -> None:
        self._interval_hours = interval_hours
        self._sleep_start = sleep_start_hour
        self._sleep_end = sleep_end_hour
        self._max_backoff = max_backoff_hours
        self._orchestrator = orchestrator or EvolutionOrchestrator()
        self._consecutive_failures = 0

    async def start(self) -> None:
        """Run the evolution scheduler indefinitely."""
        logger.info(
            "EvolutionScheduler: starting — interval=%.1fh sleep_window=%d:00–%d:00 UTC",
            self._interval_hours, self._sleep_start, self._sleep_end,
        )
        while True:
            await self._wait_for_safe_window()
            rnd = await self._orchestrator.run_round()
            if rnd.status in (EvolutionStatus.FAILED, EvolutionStatus.REGRESSION_FAILED):
                self._consecutive_failures += 1
                backoff = min(
                    self._interval_hours * (2 ** self._consecutive_failures),
                    self._max_backoff,
                )
                logger.warning(
                    "EvolutionScheduler: round failed (%s) — "
                    "consecutive_failures=%d, backoff=%.1fh",
                    rnd.status.value, self._consecutive_failures, backoff,
                )
                await asyncio.sleep(backoff * 3600)
            else:
                self._consecutive_failures = 0
                await asyncio.sleep(self._interval_hours * 3600)

    def _in_sleep_window(self) -> bool:
        """Return True if current UTC hour is within the configured sleep window."""
        hour = datetime.now(timezone.utc).hour
        if self._sleep_start > self._sleep_end:  # window wraps midnight
            return hour >= self._sleep_start or hour < self._sleep_end
        return self._sleep_start <= hour < self._sleep_end

    async def _wait_for_safe_window(self) -> None:
        """Block until we are NOT in the sleep window."""
        if not self._in_sleep_window():
            return
        logger.info(
            "EvolutionScheduler: in sleep window (%d:00–%d:00 UTC) — waiting.",
            self._sleep_start, self._sleep_end,
        )
        while self._in_sleep_window():
            await asyncio.sleep(300)  # check every 5 minutes
        logger.info("EvolutionScheduler: sleep window ended — proceeding with round.")
