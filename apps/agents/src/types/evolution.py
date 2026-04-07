"""
types/evolution.py
==================
Pydantic-style dataclasses for the Agent0-pattern curriculum co-evolution loop.

All types are plain dataclasses (stdlib) to match the conventions established
in types/research.py. Convert to pydantic BaseModel if pydantic is already
available in the agents environment.

These types cross the boundary between:
  - apps/agents/src/agents/evolution_curriculum_agent.py  (agent runtime)
  - multiclaw/agent0-evolution/                           (K8s batch pod)
  - apps/orchestrator-api                                 (REST API shapes)
  - apps/dashboard                                        (evolution panel)
  - logs/evolution/evolution_registry.db                  (persistence)

Evolution registry path layout:
  logs/evolution/
    evolution_registry.db          <- SQLite: all rounds + tasks
    registry_summary.json          <- live-updated JSON mirror
    artifacts/
      <round_id>/
        curriculum_tasks.jsonl     <- task batch input
        solved_tasks.jsonl         <- executor outputs + scores
        regression_result.json     <- regression gate result
        checkpoint_manifest.json   <- promoted checkpoint metadata
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskFamily(str, Enum):
    """
    Trading-domain task families used by the CurriculumStrategyAgent.

    Each family targets a distinct competency axis in the agent's trading
    reasoning.  The curriculum samples across all families at every difficulty
    tier to ensure balanced capability growth.

    REGIME_DETECTION
        Identify the current market microstructure regime from OHLCV + funding
        + OI data.  Higher difficulties require multi-asset, multi-timeframe
        classification with transition boundary detection.

    EXECUTION_OPTIMIZATION
        Select order type, limit offset (bps), and timing given a position
        target, fee tier, and liquidity snapshot.  Higher difficulties add
        partial-fill handling, iceberg sizing, and maker-rebate maximization.

    RISK_SIZING
        Compute Kelly-derived position size under a regime + drawdown budget
        constraint set.  Higher difficulties add cross-asset correlation,
        margin-mode switching, and liquidation-distance enforcement.

    MULTI_ASSET_BASIS
        Model and exploit perp–spot basis across two or more assets.
        Higher difficulties add funding-rate path modelling and roll strategy.

    LIQUIDATION_CASCADE
        Recognise precursor signatures of a liquidation cascade and size/time
        a defensive position reduction.  Highest difficulty adds cross-exchange
        contagion modelling.

    FUNDING_CARRY
        Structure a delta-neutral funding-carry position, size it within risk
        limits, and decide entry/exit based on predicted funding persistence.
        Higher difficulties add rebalancing cost and regime-flip exit triggers.
    """

    REGIME_DETECTION = "regime_detection"
    EXECUTION_OPTIMIZATION = "execution_optimization"
    RISK_SIZING = "risk_sizing"
    MULTI_ASSET_BASIS = "multi_asset_basis"
    LIQUIDATION_CASCADE = "liquidation_cascade"
    FUNDING_CARRY = "funding_carry"


class DifficultyLevel(int, Enum):
    """
    Curriculum difficulty tiers 1–5.

    1  BASIC        Single asset, single regime, direct signal → action.
    2  INTERMEDIATE Multi-timeframe, two-asset consideration, one complication.
    3  ADVANCED     Regime transition, partial fills, cross-asset, fee impact.
    4  EXPERT       Cascading events, multi-leg positions, drawdown ceiling.
    5  FRONTIER     Novel market structure, multi-exchange, full risk stack.
    """

    BASIC = 1
    INTERMEDIATE = 2
    ADVANCED = 3
    EXPERT = 4
    FRONTIER = 5


class EvolutionStatus(str, Enum):
    """
    Lifecycle states for an EvolutionRound.

    State machine:
      QUEUED -> CURRICULUM_GENERATION -> EXECUTOR_SOLVING -> SCORING
             -> REGRESSION_CHECK -> GATE_PENDING -> COMPLETE
                                  -> REGRESSION_FAILED
                                  -> FAILED
                                  -> CANCELLED
    """

    QUEUED = "queued"
    CURRICULUM_GENERATION = "curriculum_generation"
    EXECUTOR_SOLVING = "executor_solving"
    SCORING = "scoring"
    REGRESSION_CHECK = "regression_check"
    GATE_PENDING = "gate_pending"   # awaiting human checkpoint approval
    COMPLETE = "complete"
    REGRESSION_FAILED = "regression_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Task types
# ---------------------------------------------------------------------------


@dataclass
class EvolutionTask:
    """
    A single curriculum task proposed by CurriculumStrategyAgent.

    Attributes
    ----------
    task_id:
        Unique task identifier.  Format: evtask_<round_id>_<hex8>
    round_id:
        Parent EvolutionRound identifier.
    family:
        TaskFamily this task belongs to.
    difficulty:
        DifficultyLevel for this task.
    scenario:
        Natural-language scenario description.  Written so the executor can
        reason over it using available tools (market data, backtest harness).
    instruments:
        List of HL perpetual tickers involved (e.g. ["BTC-PERP", "ETH-PERP"]).
    regime_context:
        Regime label the task is set in (from RegimeClassifier taxonomy).
        e.g. "trending_bull", "ranging_low_vol", "high_funding_contango"
    lookback_days:
        Historical window (in days) the executor should use for backtesting.
    verification_metric:
        Primary metric used to score the executor's solution objectively.
        One of: "sharpe", "sortino", "calmar", "max_drawdown_pct", "win_rate_pct"
    verification_threshold:
        Minimum acceptable value of verification_metric for the task to be
        considered solved (e.g. sharpe >= 0.8).
    parameter_space:
        Optional dict of strategy parameter ranges the executor is allowed to
        search.  Keys match StrategyConfig fields; values are [min, max] ranges
        or discrete lists.
    created_at:
        ISO-8601 UTC timestamp of task creation.
    """

    task_id: str
    round_id: str
    family: TaskFamily
    difficulty: DifficultyLevel
    scenario: str
    instruments: list[str]
    regime_context: str
    lookback_days: int
    verification_metric: str
    verification_threshold: float
    created_at: str
    parameter_space: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "round_id": self.round_id,
            "family": self.family.value,
            "difficulty": self.difficulty.value,
            "scenario": self.scenario,
            "instruments": self.instruments,
            "regime_context": self.regime_context,
            "lookback_days": self.lookback_days,
            "verification_metric": self.verification_metric,
            "verification_threshold": self.verification_threshold,
            "parameter_space": self.parameter_space,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvolutionTask":
        return cls(
            task_id=data["task_id"],
            round_id=data["round_id"],
            family=TaskFamily(data["family"]),
            difficulty=DifficultyLevel(data["difficulty"]),
            scenario=data["scenario"],
            instruments=data["instruments"],
            regime_context=data["regime_context"],
            lookback_days=data["lookback_days"],
            verification_metric=data["verification_metric"],
            verification_threshold=data["verification_threshold"],
            created_at=data["created_at"],
            parameter_space=data.get("parameter_space", {}),
        )


@dataclass
class SolvedTask:
    """
    Result of an EvolutionExecutorAgent solving an EvolutionTask.

    The reward signal is always an objective backtest metric — never
    LLM-judged.  This prevents reward hacking and ensures the curriculum
    has ground truth from the agentharness backtest engine.

    Attributes
    ----------
    task_id:
        Identifier of the solved EvolutionTask.
    round_id:
        Parent EvolutionRound identifier.
    solved:
        True if verification_metric >= verification_threshold.
    reasoning_trace:
        The executor's chain-of-thought reasoning steps as a list of strings.
        Stored for curriculum analysis and MetaClaw skills extraction.
    strategy_params:
        The parameter dict the executor settled on (matches StrategyConfig
        field names).  None if the task could not be solved.
    sharpe:
        Annualised Sharpe ratio from the agentharness backtest.
    sortino:
        Sortino ratio from the agentharness backtest.
    calmar:
        Calmar ratio from the agentharness backtest.
    max_drawdown_pct:
        Maximum drawdown percentage from the backtest.
    win_rate_pct:
        Win rate percentage from the backtest.
    n_trades:
        Number of simulated trades in the backtest window.
    tool_calls:
        List of tool call records [{"tool": str, "args": dict, "result": str}].
        Used for curriculum refinement and MetaClaw skills extraction.
    error:
        Error message if the executor failed (None on success).
    solved_at:
        ISO-8601 UTC timestamp of task completion.
    """

    task_id: str
    round_id: str
    solved: bool
    reasoning_trace: list[str]
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    max_drawdown_pct: float | None
    win_rate_pct: float | None
    n_trades: int | None
    solved_at: str
    strategy_params: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "round_id": self.round_id,
            "solved": self.solved,
            "reasoning_trace": self.reasoning_trace,
            "strategy_params": self.strategy_params,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "calmar": self.calmar,
            "max_drawdown_pct": self.max_drawdown_pct,
            "win_rate_pct": self.win_rate_pct,
            "n_trades": self.n_trades,
            "tool_calls": self.tool_calls,
            "error": self.error,
            "solved_at": self.solved_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SolvedTask":
        return cls(
            task_id=data["task_id"],
            round_id=data["round_id"],
            solved=data["solved"],
            reasoning_trace=data["reasoning_trace"],
            strategy_params=data.get("strategy_params"),
            sharpe=data.get("sharpe"),
            sortino=data.get("sortino"),
            calmar=data.get("calmar"),
            max_drawdown_pct=data.get("max_drawdown_pct"),
            win_rate_pct=data.get("win_rate_pct"),
            n_trades=data.get("n_trades"),
            tool_calls=data.get("tool_calls", []),
            error=data.get("error"),
            solved_at=data["solved_at"],
        )


@dataclass
class TaskBatch:
    """
    A batch of curriculum tasks proposed for a single evolution round.

    Attributes
    ----------
    round_id:
        Parent EvolutionRound identifier.
    difficulty:
        Difficulty level for all tasks in this batch.
    tasks:
        List of EvolutionTask objects.
    regime_distribution:
        Mapping of regime_label -> count showing how the batch is
        distributed across market regimes.
    family_distribution:
        Mapping of TaskFamily.value -> count showing family coverage.
    created_at:
        ISO-8601 UTC timestamp of batch creation.
    """

    round_id: str
    difficulty: DifficultyLevel
    tasks: list[EvolutionTask]
    regime_distribution: dict[str, int]
    family_distribution: dict[str, int]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_id": self.round_id,
            "difficulty": self.difficulty.value,
            "tasks": [t.to_dict() for t in self.tasks],
            "regime_distribution": self.regime_distribution,
            "family_distribution": self.family_distribution,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Round and regression types
# ---------------------------------------------------------------------------


@dataclass
class RegressionResult:
    """
    Result of the regression gate check after a completed evolution round.

    The regression gate compares the evolved model's backtest performance
    against the current production baseline.  A round is blocked from
    checkpoint promotion if any gated metric degrades beyond the threshold.

    Attributes
    ----------
    round_id:
        Parent EvolutionRound identifier.
    passed:
        True if all gated metrics are within acceptable degradation thresholds.
    baseline_sharpe:
        Sharpe ratio of the current production baseline model.
    evolved_sharpe:
        Sharpe ratio of the evolved model candidate.
    sharpe_delta_pct:
        Percentage change in Sharpe: (evolved - baseline) / abs(baseline) * 100
    baseline_max_drawdown_pct:
        Maximum drawdown of the current production baseline.
    evolved_max_drawdown_pct:
        Maximum drawdown of the evolved model candidate.
    regression_threshold_pct:
        Configured threshold: evolution is blocked if any metric degrades
        more than this percentage (default: 10.0).
    blocking_metrics:
        List of metric names that caused the gate to fail (empty if passed).
    evaluated_at:
        ISO-8601 UTC timestamp of regression evaluation.
    """

    round_id: str
    passed: bool
    baseline_sharpe: float
    evolved_sharpe: float
    sharpe_delta_pct: float
    baseline_max_drawdown_pct: float
    evolved_max_drawdown_pct: float
    regression_threshold_pct: float
    blocking_metrics: list[str]
    evaluated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_id": self.round_id,
            "passed": self.passed,
            "baseline_sharpe": self.baseline_sharpe,
            "evolved_sharpe": self.evolved_sharpe,
            "sharpe_delta_pct": self.sharpe_delta_pct,
            "baseline_max_drawdown_pct": self.baseline_max_drawdown_pct,
            "evolved_max_drawdown_pct": self.evolved_max_drawdown_pct,
            "regression_threshold_pct": self.regression_threshold_pct,
            "blocking_metrics": self.blocking_metrics,
            "evaluated_at": self.evaluated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegressionResult":
        return cls(
            round_id=data["round_id"],
            passed=data["passed"],
            baseline_sharpe=data["baseline_sharpe"],
            evolved_sharpe=data["evolved_sharpe"],
            sharpe_delta_pct=data["sharpe_delta_pct"],
            baseline_max_drawdown_pct=data["baseline_max_drawdown_pct"],
            evolved_max_drawdown_pct=data["evolved_max_drawdown_pct"],
            regression_threshold_pct=data["regression_threshold_pct"],
            blocking_metrics=data["blocking_metrics"],
            evaluated_at=data["evaluated_at"],
        )


@dataclass
class CheckpointManifest:
    """
    Metadata for a model checkpoint produced by a completed evolution round.

    This is a read-only proposal artifact — the checkpoint is NEVER
    automatically promoted to the live agent inference path.  A human
    operator must set approved=True via the dashboard or the registry API
    before the orchestrator pod will swap the agent model weights.

    Attributes
    ----------
    round_id:
        Source EvolutionRound identifier.
    checkpoint_path:
        Absolute path to the checkpoint artefact (relative to project root:
        logs/evolution/artifacts/<round_id>/checkpoint.pt).
    base_model_id:
        Identifier of the base model this checkpoint was fine-tuned from.
    training_task_count:
        Number of solved tasks used in the fine-tuning corpus.
    mean_sharpe:
        Mean Sharpe across all solved tasks in the batch.
    mean_sortino:
        Mean Sortino across all solved tasks in the batch.
    solve_rate_pct:
        Percentage of curriculum tasks solved in this round.
    regression_result:
        RegressionResult for this checkpoint.  Must have passed=True before
        human approval is meaningful.
    approved:
        False until a human explicitly approves this checkpoint for deployment.
        Approval is performed via the dashboard or the registry REST API.
    approved_by:
        Optional identifier of the approving operator.
    approved_at:
        ISO-8601 UTC timestamp of checkpoint approval.
    created_at:
        ISO-8601 UTC timestamp of checkpoint manifest creation.
    """

    round_id: str
    checkpoint_path: str
    base_model_id: str
    training_task_count: int
    mean_sharpe: float
    mean_sortino: float
    solve_rate_pct: float
    regression_result: RegressionResult
    created_at: str
    approved: bool = False
    approved_by: str | None = None
    approved_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_id": self.round_id,
            "checkpoint_path": self.checkpoint_path,
            "base_model_id": self.base_model_id,
            "training_task_count": self.training_task_count,
            "mean_sharpe": self.mean_sharpe,
            "mean_sortino": self.mean_sortino,
            "solve_rate_pct": self.solve_rate_pct,
            "regression_result": self.regression_result.to_dict(),
            "approved": self.approved,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CheckpointManifest":
        return cls(
            round_id=data["round_id"],
            checkpoint_path=data["checkpoint_path"],
            base_model_id=data["base_model_id"],
            training_task_count=data["training_task_count"],
            mean_sharpe=data["mean_sharpe"],
            mean_sortino=data["mean_sortino"],
            solve_rate_pct=data["solve_rate_pct"],
            regression_result=RegressionResult.from_dict(data["regression_result"]),
            created_at=data["created_at"],
            approved=data.get("approved", False),
            approved_by=data.get("approved_by"),
            approved_at=data.get("approved_at"),
        )


@dataclass
class EvolutionRound:
    """
    Represents a single Agent0-pattern curriculum co-evolution round.

    Persisted to logs/evolution/evolution_registry.db and exported to
    logs/evolution/registry_summary.json on each state transition.

    One round = one complete curriculum batch -> executor solving -> scoring
    -> regression check -> optional checkpoint creation -> human gate.

    Attributes
    ----------
    round_id:
        Unique round identifier.  Format: evround_YYYYMMDD_HHMMSS_<hex8>
    difficulty:
        DifficultyLevel applied to the full task batch for this round.
    status:
        Current lifecycle state of the round.
    task_count:
        Total number of tasks in the curriculum batch.
    solved_count:
        Number of tasks solved by the executor (objective metric passed).
    solve_rate_pct:
        solved_count / task_count * 100.  Used for difficulty auto-progression:
        if solve_rate_pct >= difficulty_up_threshold, next round difficulty += 1.
    mean_sharpe:
        Mean Sharpe across all solved tasks.  None until scoring completes.
    mean_sortino:
        Mean Sortino across all solved tasks.  None until scoring completes.
    regression_result:
        RegressionResult for this round.  None until regression_check stage.
    checkpoint_manifest:
        CheckpointManifest created if regression gate passed.  None otherwise.
    artifact_dir:
        Path to this round's artifact directory.
        Always: logs/evolution/artifacts/<round_id>/
    error:
        Error message when status == FAILED.
    started_at:
        ISO-8601 UTC timestamp of round start.
    updated_at:
        ISO-8601 UTC timestamp of most recent state change.
    completed_at:
        ISO-8601 UTC timestamp of round completion.  None until COMPLETE.
    """

    round_id: str
    difficulty: DifficultyLevel
    status: EvolutionStatus
    task_count: int
    artifact_dir: str
    started_at: str
    updated_at: str
    solved_count: int = 0
    solve_rate_pct: float = 0.0
    mean_sharpe: float | None = None
    mean_sortino: float | None = None
    regression_result: RegressionResult | None = None
    checkpoint_manifest: CheckpointManifest | None = None
    error: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_id": self.round_id,
            "difficulty": self.difficulty.value,
            "status": self.status.value,
            "task_count": self.task_count,
            "solved_count": self.solved_count,
            "solve_rate_pct": self.solve_rate_pct,
            "mean_sharpe": self.mean_sharpe,
            "mean_sortino": self.mean_sortino,
            "regression_result": (
                self.regression_result.to_dict()
                if self.regression_result
                else None
            ),
            "checkpoint_manifest": (
                self.checkpoint_manifest.to_dict()
                if self.checkpoint_manifest
                else None
            ),
            "artifact_dir": self.artifact_dir,
            "error": self.error,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvolutionRound":
        reg_raw = data.get("regression_result")
        ckpt_raw = data.get("checkpoint_manifest")
        return cls(
            round_id=data["round_id"],
            difficulty=DifficultyLevel(data["difficulty"]),
            status=EvolutionStatus(data["status"]),
            task_count=data["task_count"],
            solved_count=data.get("solved_count", 0),
            solve_rate_pct=data.get("solve_rate_pct", 0.0),
            mean_sharpe=data.get("mean_sharpe"),
            mean_sortino=data.get("mean_sortino"),
            regression_result=(
                RegressionResult.from_dict(reg_raw) if reg_raw else None
            ),
            checkpoint_manifest=(
                CheckpointManifest.from_dict(ckpt_raw) if ckpt_raw else None
            ),
            artifact_dir=data["artifact_dir"],
            error=data.get("error"),
            started_at=data["started_at"],
            updated_at=data["updated_at"],
            completed_at=data.get("completed_at"),
        )


@dataclass
class EvolutionRegistryEntry:
    """
    Lightweight registry entry for the evolution_registry.db index table.

    Stores only round-level metadata for fast listing and status queries.
    Full task / solved-task data is stored in JSONL files under artifact_dir.

    Attributes
    ----------
    round_id:      EvolutionRound.round_id
    status:        EvolutionRound.status.value
    difficulty:    EvolutionRound.difficulty.value
    solve_rate_pct: EvolutionRound.solve_rate_pct
    mean_sharpe:   EvolutionRound.mean_sharpe
    checkpoint_approved: CheckpointManifest.approved if present, else None
    started_at:    EvolutionRound.started_at
    completed_at:  EvolutionRound.completed_at
    """

    round_id: str
    status: str
    difficulty: int
    solve_rate_pct: float
    started_at: str
    mean_sharpe: float | None = None
    checkpoint_approved: bool | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_id": self.round_id,
            "status": self.status,
            "difficulty": self.difficulty,
            "solve_rate_pct": self.solve_rate_pct,
            "mean_sharpe": self.mean_sharpe,
            "checkpoint_approved": self.checkpoint_approved,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }
