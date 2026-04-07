"""
types/research.py
=================
Pydantic-style dataclasses for the ResearchAgent and research-bridge module.

All types are plain dataclasses (stdlib) to avoid adding pydantic as a
dependency specifically for the research layer. If pydantic is already
available in the agents environment (via pyproject.toml), you may convert
these to BaseModel subclasses for richer validation.

These types cross the boundary between:
  - multiclaw/research-bridge  (AutoResearchClaw orchestration)
  - apps/agents/src/agents/research_agent.py  (firm-side agent)
  - apps/orchestrator-api  (REST API response shapes — serialize via .to_dict())
  - apps/dashboard  (dashboard research panel — consumes registry_summary.json)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ResearchMode(str, Enum):
    """
    Controls AutoResearchClaw gate configuration and experiment execution mode.

    Gate matrix (True = human gate active, False = auto-approved):

                         stage_5  stage_9  stage_20
      DEEP                 True     True     True
      STRATEGY_SCAN        True     False    False
      PROJECT_AUDIT        True     True     True
      COMPETITIVE_BACKTEST False    True     False
      NIGHTLY_DIGEST       False    False    False
    """

    DEEP = "deep"
    STRATEGY_SCAN = "strategy_scan"
    PROJECT_AUDIT = "project_audit"
    COMPETITIVE_BACKTEST = "competitive_backtest"
    NIGHTLY_DIGEST = "nightly_digest"


class ResearchStatus(str, Enum):
    """
    Lifecycle states for a ResearchJob.

    State machine:
      QUEUED -> RUNNING -> GATE_PENDING -> RUNNING -> ... -> COMPLETE
                        -> FAILED
                        -> CANCELLED
    """

    QUEUED = "queued"
    RUNNING = "running"
    GATE_PENDING = "gate_pending"  # paused awaiting human gate approval
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Supporting types
# ---------------------------------------------------------------------------


@dataclass
class GateState:
    """
    Tracks the state of a human approval gate for a pipeline job.

    Attributes
    ----------
    stage:
        AutoResearchClaw stage number at which the gate is active (5, 9, or 20).
    approved:
        True once the gate has been approved by a human operator.
    approved_by:
        Optional identifier of the operator who approved the gate.
    approved_at:
        ISO-8601 UTC timestamp of gate approval.
    """

    stage: int
    approved: bool = False
    approved_by: str | None = None
    approved_at: str | None = None


@dataclass
class StrategyMetrics:
    """
    Current performance metrics for a strategy, used to focus STRATEGY_SCAN
    research topics on the specific failure modes most relevant to the current
    performance envelope.

    Attributes
    ----------
    sharpe:
        Annualised Sharpe ratio.
    max_drawdown_pct:
        Maximum drawdown as a percentage (positive = loss).
    win_rate_pct:
        Percentage of trades that closed in profit.
    regime_label:
        Human-readable current regime label from the regime classifier
        (e.g. "trending_bull", "ranging_low_vol", "high_funding_contango").
    annualised_return_pct:
        Optional annualised return percentage.
    sortino:
        Optional Sortino ratio.
    calmar:
        Optional Calmar ratio.
    """

    sharpe: float
    max_drawdown_pct: float
    win_rate_pct: float
    regime_label: str
    annualised_return_pct: float | None = None
    sortino: float | None = None
    calmar: float | None = None


# ---------------------------------------------------------------------------
# Core job type
# ---------------------------------------------------------------------------


@dataclass
class ResearchJob:
    """
    Represents a single AutoResearchClaw pipeline execution.

    Persisted to logs/research/research_registry.db and exported to
    logs/research/registry_summary.json on each state transition.

    Attributes
    ----------
    job_id:
        Unique job identifier. Format: rcjob_YYYYMMDD_HHMMSS_<hex8>
    topic:
        Original human-readable research topic as submitted by the analyst.
    enriched_topic:
        topic string after context_injector enrichment with firm context.
        This is what AutoResearchClaw receives as input.
    mode:
        ResearchMode controlling gate config and experiment execution mode.
    status:
        Current lifecycle state of the job.
    stage:
        Current AutoResearchClaw pipeline stage (1–23). 0 = not yet started.
    artifact_dir:
        Absolute path to the job's artifact output directory.
        All pipeline outputs land here. Never outside logs/research/artifacts/.
    gate_state:
        Present when status == GATE_PENDING; describes which gate is active.
    error:
        Error message when status == FAILED.
    quality_score:
        AutoResearchClaw quality score (0–5) for the completed paper.
        None until the job reaches COMPLETE status.
    created_at:
        ISO-8601 UTC timestamp of job creation.
    updated_at:
        ISO-8601 UTC timestamp of most recent state change.
    completed_at:
        ISO-8601 UTC timestamp of job completion. None until COMPLETE.
    """

    job_id: str
    topic: str
    enriched_topic: str
    mode: ResearchMode
    status: ResearchStatus
    stage: int
    artifact_dir: str
    created_at: str
    updated_at: str
    gate_state: GateState | None = None
    error: str | None = None
    quality_score: float | None = None
    completed_at: str | None = None
    _process: Any = field(default=None, repr=False, compare=False)  # asyncio subprocess

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict for registry_summary.json and the REST API."""
        return {
            "job_id": self.job_id,
            "topic": self.topic,
            "enriched_topic": self.enriched_topic,
            "mode": self.mode.value,
            "status": self.status.value,
            "stage": self.stage,
            "artifact_dir": self.artifact_dir,
            "gate_state": (
                {
                    "stage": self.gate_state.stage,
                    "approved": self.gate_state.approved,
                    "approved_by": self.gate_state.approved_by,
                    "approved_at": self.gate_state.approved_at,
                }
                if self.gate_state
                else None
            ),
            "error": self.error,
            "quality_score": self.quality_score,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchJob":
        """Deserialise from registry_summary.json entry."""
        gate_raw = data.get("gate_state")
        return cls(
            job_id=data["job_id"],
            topic=data["topic"],
            enriched_topic=data["enriched_topic"],
            mode=ResearchMode(data["mode"]),
            status=ResearchStatus(data["status"]),
            stage=data["stage"],
            artifact_dir=data["artifact_dir"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            gate_state=(
                GateState(
                    stage=gate_raw["stage"],
                    approved=gate_raw["approved"],
                    approved_by=gate_raw.get("approved_by"),
                    approved_at=gate_raw.get("approved_at"),
                )
                if gate_raw
                else None
            ),
            error=data.get("error"),
            quality_score=data.get("quality_score"),
            completed_at=data.get("completed_at"),
        )


# ---------------------------------------------------------------------------
# Output artifact types
# ---------------------------------------------------------------------------


@dataclass
class Hypothesis:
    """
    A single research-backed hypothesis from a STRATEGY_SCAN or DEEP job.

    Attributes
    ----------
    statement:
        Plain-language hypothesis statement.
    confidence:
        Estimated confidence level: "low", "medium", or "high".
        Derived from the number and quality of supporting citations.
    parameter_suggestions:
        Optional dict of suggested strategy parameter adjustments.
        Keys are parameter names matching StrategyConfig fields;
        values are suggested ranges or point estimates.
    supporting_citations:
        List of citation keys from the accompanying citations.bib.
    """

    statement: str
    confidence: str  # "low" | "medium" | "high"
    parameter_suggestions: dict[str, Any] = field(default_factory=dict)
    supporting_citations: list[str] = field(default_factory=list)


@dataclass
class HypothesisSet:
    """
    Collection of hypotheses from a completed STRATEGY_SCAN or DEEP job.

    This is a read-only proposal artifact. It must be explicitly reviewed
    and approved by a human operator before the iteration loop can consume
    it. The ResearchAgent never promotes hypotheses automatically.

    Attributes
    ----------
    job_id:
        Source job identifier.
    hypotheses:
        List of Hypothesis objects parsed from hypotheses.json.
    citations:
        List of raw citation dicts from the accompanying literature.
    quality_score:
        AutoResearchClaw quality score for the underlying job.
    approved:
        False until a human explicitly approves this set for iteration loop
        consumption. Approval is performed via the dashboard or by moving
        the approved file to the iteration loop's context path.
    approved_by:
        Optional identifier of the approving operator.
    approved_at:
        ISO-8601 UTC timestamp of approval.
    """

    job_id: str
    hypotheses: list[Hypothesis | dict]
    citations: list[dict]
    quality_score: float | None = None
    approved: bool = False
    approved_by: str | None = None
    approved_at: str | None = None


@dataclass
class ProjectReport:
    """
    Structured due-diligence report from a completed PROJECT_AUDIT job.

    Parsed from synthesis.json in the job's artifact directory.

    Attributes
    ----------
    job_id:
        Source job identifier.
    ticker:
        Asset ticker symbol that was audited.
    summary:
        Plain-language executive summary of the research findings.
    tokenomics:
        Optional dict of tokenomics analysis findings.
    competitive_landscape:
        Optional dict of competitive landscape findings.
    defi_integration_risks:
        Optional dict of identified DeFi integration risks.
    citations:
        List of raw citation dicts.
    quality_score:
        AutoResearchClaw quality score for the underlying job.
    """

    job_id: str
    ticker: str
    summary: str
    tokenomics: dict[str, Any] | None = None
    competitive_landscape: dict[str, Any] | None = None
    defi_integration_risks: dict[str, Any] | None = None
    citations: list[dict] = field(default_factory=list)
    quality_score: float | None = None
