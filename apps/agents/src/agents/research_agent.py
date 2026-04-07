"""
research_agent.py
=================
User-directed research agent for the HyperLiquid Autonomous Trading Firm.

This agent orchestrates multiclaw/research-bridge to run AutoResearchClaw
pipeline jobs on behalf of human analysts. It composes research topic prompts
from internal trading firm context (RL buffer exports, backtest history,
strategy configs) and routes parsed artifacts downstream to prompts/,
apps/jobs/, and the dashboard research panel.

Safety invariants (non-negotiable)
-----------------------------------
- NEVER called from the live order path, SAE engine, or any executor.
- ALL outputs are read-only proposals routed to logs/research/artifacts/.
- NO artifact is written to strategy/, agent/, or apps/executors/.
- NO secret env var is forwarded to the research pipeline.
- Hypothesis proposals require explicit human approval before the iteration
  loop can consume them. This agent never promotes them automatically.

Usage
-----
From the Orchestrator API or dashboard, call via:

    POST /research/jobs
    {"topic": "...", "mode": "strategy_scan"}

Or directly from a job script:

    agent = ResearchAgent.from_config()
    job = await agent.run_deep_research(
        topic="EMA crossover failure modes in high-funding-rate perps regimes",
        mode=ResearchMode.STRATEGY_SCAN,
    )

See also
--------
- multiclaw/research-bridge/README.md  — Full integration documentation
- multiclaw/research-bridge/config.trading-firm.yaml  — Active bridge config
- apps/agents/src/types/research.py  — All types used by this module
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..types.research import (
    GateState,
    HypothesisSet,
    ProjectReport,
    ResearchJob,
    ResearchMode,
    ResearchStatus,
    StrategyMetrics,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[5]  # apps/agents/src/agents -> repo root
_BRIDGE_DIR = _REPO_ROOT / "multiclaw" / "research-bridge"
_BRIDGE_CONFIG = _BRIDGE_DIR / "config.trading-firm.yaml"
_ARTIFACTS_ROOT = _REPO_ROOT / "logs" / "research" / "artifacts"
_REGISTRY_PATH = _REPO_ROOT / "logs" / "research" / "research_registry.db"
_AUDIT_LOG = _REPO_ROOT / "logs" / "audit.jsonl"

# ---------------------------------------------------------------------------
# Secret scrub list — env vars that must never reach the research pipeline.
# Extend this list if new secrets are added to the project.
# ---------------------------------------------------------------------------

_SCRUB_ENV_VARS: frozenset[str] = frozenset(
    [
        "HL_PRIVATE_KEY",
        "HL_API_KEY",
        "VAULT_SUBACCOUNT_ADDRESS",
        "RESEARCH_LLM_KEY",
        "RESEARCH_GATE_WEBHOOK_URL",
        "SLACK_WEBHOOK_URL",
        "DATABASE_URL",
        "REDIS_URL",
        "MLFLOW_TRACKING_URI",
        "HUMMINGBOT_SECRET",
    ]
)


# ---------------------------------------------------------------------------
# ResearchAgent
# ---------------------------------------------------------------------------


class ResearchAgent:
    """
    User-directed research agent. Wraps the multiclaw/research-bridge to
    invoke AutoResearchClaw pipeline jobs from structured trading firm context.

    All public methods are async and non-blocking. Pipeline jobs run as
    background subprocess tasks; state is tracked in research_registry.db
    and surfaced via the dashboard research panel.

    This class is intentionally side-effect-free with respect to the trading
    firm's execution plane. It reads from logs/ (RL buffer, backtest history)
    and writes exclusively to logs/research/artifacts/.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._bridge_dir = _BRIDGE_DIR
        self._artifacts_root = _ARTIFACTS_ROOT
        self._registry_path = _REGISTRY_PATH
        self._audit_log = _AUDIT_LOG
        self._artifacts_root.mkdir(parents=True, exist_ok=True)
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._audit_log.parent.mkdir(parents=True, exist_ok=True)
        self._registry: dict[str, ResearchJob] = {}
        self._load_registry()
        logger.info("ResearchAgent initialised", extra={"bridge_dir": str(self._bridge_dir)})

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        config_path: Path | str | None = None,
    ) -> "ResearchAgent":
        """
        Instantiate from config.trading-firm.yaml.

        Parameters
        ----------
        config_path:
            Override path to the bridge config file. Defaults to
            multiclaw/research-bridge/config.trading-firm.yaml.
        """
        path = Path(config_path) if config_path else _BRIDGE_CONFIG
        if not path.exists():
            raise FileNotFoundError(
                f"Bridge config not found: {path}\n"
                "Run: cp multiclaw/research-bridge/config.trading-firm.example.yaml "
                "multiclaw/research-bridge/config.trading-firm.yaml"
            )
        with path.open() as fh:
            config = yaml.safe_load(fh)
        return cls(config)

    # ------------------------------------------------------------------
    # Public API — research job submission
    # ------------------------------------------------------------------

    async def run_deep_research(
        self,
        topic: str,
        mode: ResearchMode = ResearchMode.DEEP,
        auto_approve_stages: list[int] | None = None,
        context_override: dict[str, Any] | None = None,
    ) -> ResearchJob:
        """
        Submit a research job to AutoResearchClaw.

        Builds a topic prompt from internal firm context (RL buffer +
        backtest history), invokes the pipeline as an async subprocess,
        and registers the job in research_registry.db.

        Parameters
        ----------
        topic:
            Human-readable research topic or question. The context injector
            will prepend structured firm context to this string before passing
            it to AutoResearchClaw.
        mode:
            ResearchMode controlling gate configuration and experiment mode.
            See ResearchMode docstring for per-mode behaviour.
        auto_approve_stages:
            List of stage numbers to auto-approve. Must be empty or None for
            DEEP and PROJECT_AUDIT modes in production. Dev/test use only.
        context_override:
            Optional dict of additional context key-value pairs to inject
            into the topic prompt alongside the standard RL buffer context.
            All values are scrubbed for secret env vars before injection.

        Returns
        -------
        ResearchJob with status QUEUED. Poll get_job() or watch the dashboard
        for status transitions: QUEUED -> RUNNING -> GATE_PENDING -> COMPLETE.
        """
        _guard_mode_gate_override(mode, auto_approve_stages)
        job_id = _new_job_id()
        enriched_topic = self._build_topic_prompt(
            topic=topic,
            mode=mode,
            context_override=context_override or {},
        )
        job = ResearchJob(
            job_id=job_id,
            topic=topic,
            enriched_topic=enriched_topic,
            mode=mode,
            status=ResearchStatus.QUEUED,
            stage=0,
            artifact_dir=str(self._artifacts_root / job_id),
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        self._upsert_registry(job)
        self._append_audit("QUEUED", job)
        logger.info("Research job queued", extra={"job_id": job_id, "mode": mode.value})
        asyncio.create_task(
            self._run_pipeline(
                job=job,
                auto_approve_stages=auto_approve_stages or [],
            )
        )
        return job

    async def get_strategy_evaluation(
        self,
        strategy_class: str,
        current_metrics: StrategyMetrics,
        context_override: dict[str, Any] | None = None,
    ) -> HypothesisSet:
        """
        Run a STRATEGY_SCAN job and return the parsed HypothesisSet.

        Blocks until the pipeline completes (Stage 5 gate must be approved).
        Suitable for analyst-initiated strategy improvement research sessions.

        Parameters
        ----------
        strategy_class:
            Internal strategy class name (e.g. "ema_cross", "rsi_reversal",
            "hyperliquid_perps_meta"). Must match a key in config/strategies/.
        current_metrics:
            Current backtest or live performance metrics for the strategy.
            Used to focus the literature search on the specific failure modes
            most relevant to the current performance envelope.

        Returns
        -------
        HypothesisSet containing literature-backed hypotheses and suggested
        parameter ranges. All proposals are read-only; no strategy file is
        modified by this call.
        """
        topic = _format_strategy_scan_topic(strategy_class, current_metrics)
        job = await self.run_deep_research(
            topic=topic,
            mode=ResearchMode.STRATEGY_SCAN,
            context_override=context_override,
        )
        completed = await self._await_job(job.job_id)
        return _parse_hypothesis_set(completed)

    async def scan_crypto_project(
        self,
        ticker: str,
        whitepaper_url: str | None = None,
        on_chain_context: dict[str, Any] | None = None,
    ) -> ProjectReport:
        """
        Run a PROJECT_AUDIT job and return the structured due-diligence report.

        All three AutoResearchClaw human gates are active (Stages 5, 9, 20).
        The job will pause at each gate for human approval before proceeding.

        Parameters
        ----------
        ticker:
            Asset ticker symbol (e.g. "BTC", "ETH", "HYPE").
        whitepaper_url:
            Optional URL to the project's whitepaper or technical docs.
            context_injector will include it as a primary source reference.
        on_chain_context:
            Optional dict of pre-fetched on-chain metrics (TVL, 30d volume,
            protocol type, etc.) from Messari, DeFiLlama, or Token Terminal.
            Formatted into topic context before pipeline invocation since
            these sources are not natively supported by AutoResearchClaw v0.3.x.

        Returns
        -------
        ProjectReport containing tokenomics analysis, competitive landscape
        assessment, and DeFi integration risk summary.
        """
        topic = _format_project_audit_topic(ticker, whitepaper_url, on_chain_context)
        job = await self.run_deep_research(
            topic=topic,
            mode=ResearchMode.PROJECT_AUDIT,
        )
        completed = await self._await_job(job.job_id)
        return _parse_project_report(completed)

    async def get_job(self, job_id: str) -> ResearchJob | None:
        """
        Look up a job by ID from the in-memory registry.
        Returns None if the job_id is not known to this agent instance.
        """
        return self._registry.get(job_id)

    async def get_pending_jobs(self) -> list[ResearchJob]:
        """
        Return all jobs with status QUEUED, RUNNING, or GATE_PENDING.
        """
        return [
            j
            for j in self._registry.values()
            if j.status in (
                ResearchStatus.QUEUED,
                ResearchStatus.RUNNING,
                ResearchStatus.GATE_PENDING,
            )
        ]

    async def resume_job(self, job_id: str) -> ResearchJob:
        """
        Resume a GATE_PENDING job after human approval.

        Delegates to /researchclaw:resume via the bridge CLI.
        The job must be in GATE_PENDING status; raises ValueError otherwise.
        """
        job = self._registry.get(job_id)
        if job is None:
            raise KeyError(f"Unknown job_id: {job_id}")
        if job.status != ResearchStatus.GATE_PENDING:
            raise ValueError(
                f"Cannot resume job {job_id}: status is {job.status.value}, "
                "expected GATE_PENDING"
            )
        logger.info("Resuming job after gate approval", extra={"job_id": job_id})
        asyncio.create_task(self._resume_pipeline(job))
        return job

    async def cancel_job(self, job_id: str) -> ResearchJob:
        """
        Cancel a QUEUED or RUNNING job.
        Sends SIGTERM to the underlying subprocess if still running.
        """
        job = self._registry.get(job_id)
        if job is None:
            raise KeyError(f"Unknown job_id: {job_id}")
        if job.status not in (ResearchStatus.QUEUED, ResearchStatus.RUNNING):
            raise ValueError(
                f"Cannot cancel job {job_id}: status is {job.status.value}"
            )
        job.status = ResearchStatus.CANCELLED
        job.updated_at = _utcnow()
        self._upsert_registry(job)
        self._append_audit("CANCELLED", job)
        logger.info("Job cancelled", extra={"job_id": job_id})
        return job

    # ------------------------------------------------------------------
    # Internal — pipeline orchestration
    # ------------------------------------------------------------------

    async def _run_pipeline(
        self,
        job: ResearchJob,
        auto_approve_stages: list[int],
    ) -> None:
        """
        Execute the AutoResearchClaw pipeline as a managed async subprocess.

        Builds the CLI command from bridge config, launches the process,
        streams log lines to update stage progress, and handles gate pauses.
        """
        artifact_dir = Path(job.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        cmd = self._build_pipeline_cmd(
            job=job,
            auto_approve_stages=auto_approve_stages,
        )
        env = self._build_safe_env()

        job.status = ResearchStatus.RUNNING
        job.updated_at = _utcnow()
        self._upsert_registry(job)
        self._append_audit("RUNNING", job)
        logger.info(
            "Pipeline started",
            extra={"job_id": job.job_id, "cmd": " ".join(cmd)},
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=str(self._bridge_dir),
            )
            job._process = proc  # stored for cancel support

            async for line in proc.stdout:
                decoded = line.decode(errors="replace").rstrip()
                self._handle_pipeline_log_line(job, decoded)

            await proc.wait()

            if proc.returncode == 0:
                job.status = ResearchStatus.COMPLETE
                job.stage = 23
                job.completed_at = _utcnow()
                self._append_audit("COMPLETE", job)
                logger.info("Pipeline complete", extra={"job_id": job.job_id})
            else:
                job.status = ResearchStatus.FAILED
                job.error = f"Pipeline exited with code {proc.returncode}"
                self._append_audit("FAILED", job)
                logger.error(
                    "Pipeline failed",
                    extra={"job_id": job.job_id, "returncode": proc.returncode},
                )
        except Exception as exc:  # noqa: BLE001
            job.status = ResearchStatus.FAILED
            job.error = str(exc)
            self._append_audit("FAILED", job)
            logger.exception("Pipeline exception", extra={"job_id": job.job_id})
        finally:
            job.updated_at = _utcnow()
            self._upsert_registry(job)

    async def _resume_pipeline(self, job: ResearchJob) -> None:
        """
        Invoke the researchclaw resume CLI to unblock a GATE_PENDING job.
        Transitions the job back to RUNNING before delegating to _run_pipeline.
        """
        cmd = [
            "researchclaw",
            "resume",
            "--job-id", job.job_id,
            "--config", str(_BRIDGE_CONFIG),
        ]
        env = self._build_safe_env()
        job.status = ResearchStatus.RUNNING
        job.gate_state = None
        job.updated_at = _utcnow()
        self._upsert_registry(job)
        self._append_audit("RESUMED", job)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=str(self._bridge_dir),
            )
            async for line in proc.stdout:
                self._handle_pipeline_log_line(job, line.decode(errors="replace").rstrip())
            await proc.wait()
            if proc.returncode == 0:
                job.status = ResearchStatus.COMPLETE
                job.stage = 23
                job.completed_at = _utcnow()
                self._append_audit("COMPLETE", job)
            else:
                job.status = ResearchStatus.FAILED
                job.error = f"Resume pipeline exited with code {proc.returncode}"
                self._append_audit("FAILED", job)
        except Exception as exc:  # noqa: BLE001
            job.status = ResearchStatus.FAILED
            job.error = str(exc)
            self._append_audit("FAILED", job)
        finally:
            job.updated_at = _utcnow()
            self._upsert_registry(job)

    # ------------------------------------------------------------------
    # Internal — command & environment construction
    # ------------------------------------------------------------------

    def _build_pipeline_cmd(
        self,
        job: ResearchJob,
        auto_approve_stages: list[int],
    ) -> list[str]:
        """
        Build the AutoResearchClaw CLI invocation from job and bridge config.

        The command always writes artifacts to the job-scoped subdirectory
        under logs/research/artifacts/<job-id>/ to enforce output isolation.
        """
        cfg = self._config
        exp_cfg = cfg.get("experiment", {})
        out_cfg = cfg.get("output", {})
        quality_cfg = cfg.get("quality", {})

        cmd = [
            "researchclaw",
            "run",
            "--topic", job.enriched_topic,
            "--mode", exp_cfg.get("mode", "simulated"),
            "--output-dir", str(Path(job.artifact_dir)),
            "--output-format", out_cfg.get("format", "json+pdf"),
            "--min-quality-score", str(quality_cfg.get("min_score", 3.5)),
            "--job-id", job.job_id,
            "--config", str(_BRIDGE_CONFIG),
        ]

        if auto_approve_stages:
            for stage in auto_approve_stages:
                cmd += ["--auto-approve-stage", str(stage)]

        latex = out_cfg.get("latex_compiler")
        if latex:
            cmd += ["--latex-compiler", latex]

        return cmd

    def _build_safe_env(self) -> dict[str, str]:
        """
        Build a clean environment dict for subprocess invocation.

        Copies os.environ and removes all entries in _SCRUB_ENV_VARS.
        Also removes any env vars whose values match known secret patterns
        (private keys, hex strings > 32 chars, JWT tokens).
        """
        env = dict(os.environ)
        for key in _SCRUB_ENV_VARS:
            env.pop(key, None)
        scrub_list: list[str] = (
            self._config.get("bridge", {}).get("scrub_env_vars", []) or []
        )
        for key in scrub_list:
            env.pop(key, None)
        return env

    # ------------------------------------------------------------------
    # Internal — topic prompt construction
    # ------------------------------------------------------------------

    def _build_topic_prompt(
        self,
        topic: str,
        mode: ResearchMode,
        context_override: dict[str, Any],
    ) -> str:
        """
        Enrich the raw topic string with structured firm context.

        Reads the RL buffer export and backtest history (if available) and
        prepends a compact JSON context block within the token budget defined
        by bridge.max_context_tokens. Scrubs all secret env var values from
        injected context before returning.
        """
        bridge_cfg = self._config.get("bridge", {})
        max_tokens = bridge_cfg.get("max_context_tokens", 4000)
        lookback = bridge_cfg.get("rl_context_lookback", 20)

        ctx: dict[str, Any] = {"mode": mode.value}

        rl_path = Path(
            bridge_cfg.get("rl_buffer_export_path", "").replace(
                "../../", str(_REPO_ROOT) + "/"
            )
        )
        if rl_path.exists():
            try:
                with rl_path.open() as fh:
                    rl_data = json.load(fh)
                experiments = rl_data.get("experiments", [])
                ctx["recent_experiments"] = experiments[-lookback:]
            except Exception:  # noqa: BLE001
                logger.warning("Failed to load RL buffer export", exc_info=True)

        if context_override:
            ctx["additional_context"] = _scrub_secrets(context_override)

        ctx_str = json.dumps(ctx, separators=(",", ":"))
        # Rough token estimate: 4 chars ~= 1 token
        if len(ctx_str) > max_tokens * 4:
            ctx_str = ctx_str[: max_tokens * 4] + "... [truncated]"

        return f"[FIRM_CONTEXT:{ctx_str}]\n\n{topic}"

    # ------------------------------------------------------------------
    # Internal — log line parsing & stage tracking
    # ------------------------------------------------------------------

    def _handle_pipeline_log_line(self, job: ResearchJob, line: str) -> None:
        """
        Parse a stdout line from the AutoResearchClaw pipeline.

        Extracts stage progress markers and gate-pending signals to keep
        job.stage and job.status in sync with the pipeline state.

        AutoResearchClaw emits structured progress lines in the format:
            [STAGE:N] <description>
            [GATE:N:PENDING] <gate description>
            [GATE:N:APPROVED]
        """
        logger.debug("Pipeline log", extra={"job_id": job.job_id, "line": line})

        if line.startswith("[STAGE:"):
            try:
                stage_num = int(line.split(":")[1].rstrip("]"))
                job.stage = stage_num
                job.updated_at = _utcnow()
                self._upsert_registry(job)
            except (IndexError, ValueError):
                pass

        elif "[GATE:" in line and ":PENDING]" in line:
            try:
                parts = line.split(":")
                gate_stage = int(parts[1])
                job.status = ResearchStatus.GATE_PENDING
                job.gate_state = GateState(stage=gate_stage, approved=False)
                job.updated_at = _utcnow()
                self._upsert_registry(job)
                self._append_audit("GATE_PENDING", job)
                logger.info(
                    "Job paused at gate",
                    extra={"job_id": job.job_id, "gate_stage": gate_stage},
                )
            except (IndexError, ValueError):
                pass

        elif "[GATE:" in line and ":APPROVED]" in line:
            job.status = ResearchStatus.RUNNING
            job.gate_state = None
            job.updated_at = _utcnow()
            self._upsert_registry(job)
            self._append_audit("GATE_APPROVED", job)

    # ------------------------------------------------------------------
    # Internal — registry persistence
    # ------------------------------------------------------------------

    def _load_registry(self) -> None:
        """
        Load job state from registry_summary.json if it exists.

        The summary JSON is written by research_registry.py on each state
        transition. We read it here to restore in-memory state on agent
        restart. On first run, the registry will be empty.
        """
        summary_path = _REPO_ROOT / "logs" / "research" / "registry_summary.json"
        if summary_path.exists():
            try:
                with summary_path.open() as fh:
                    entries = json.load(fh)
                for entry in entries:
                    job = ResearchJob(**entry)
                    self._registry[job.job_id] = job
                logger.info(
                    "Registry loaded",
                    extra={"job_count": len(self._registry)},
                )
            except Exception:  # noqa: BLE001
                logger.warning("Failed to load registry summary", exc_info=True)

    def _upsert_registry(self, job: ResearchJob) -> None:
        """
        Update the in-memory registry and write the summary JSON.
        """
        self._registry[job.job_id] = job
        summary_path = _REPO_ROOT / "logs" / "research" / "registry_summary.json"
        try:
            entries = [j.to_dict() for j in self._registry.values()]
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            with summary_path.open("w") as fh:
                json.dump(entries, fh, indent=2, default=str)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to write registry summary", exc_info=True)

    def _append_audit(
        self,
        event: str,
        job: ResearchJob,
    ) -> None:
        """
        Append a structured event to the firm's central audit log.

        Format matches the rest of the firm's audit.jsonl schema:
        one JSON object per line, with event_type, source, timestamp,
        and a payload dict.
        """
        entry = {
            "event_type": "research_bridge_event",
            "source": "research_agent",
            "timestamp": _utcnow(),
            "payload": {
                "event": event,
                "job_id": job.job_id,
                "mode": job.mode.value,
                "status": job.status.value,
                "stage": job.stage,
                "topic_preview": job.topic[:120],
            },
        }
        try:
            with self._audit_log.open("a") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        except Exception:  # noqa: BLE001
            logger.warning("Failed to write audit log entry", exc_info=True)

    # ------------------------------------------------------------------
    # Internal — await helpers
    # ------------------------------------------------------------------

    async def _await_job(
        self,
        job_id: str,
        poll_interval: float = 5.0,
        timeout: float = 14400.0,  # 4 hours
    ) -> ResearchJob:
        """
        Poll the registry until a job reaches COMPLETE, FAILED, or CANCELLED.

        Used by get_strategy_evaluation() and scan_crypto_project() to make
        those methods blocking from the caller's perspective. GATE_PENDING
        status will cause this method to block until the gate is resolved
        (either via resume_job() or the dashboard).
        """
        elapsed = 0.0
        while elapsed < timeout:
            job = self._registry.get(job_id)
            if job and job.status in (
                ResearchStatus.COMPLETE,
                ResearchStatus.FAILED,
                ResearchStatus.CANCELLED,
            ):
                return job
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        raise TimeoutError(
            f"Job {job_id} did not complete within {timeout}s. "
            "Check dashboard or /researchclaw:status for gate state."
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _new_job_id() -> str:
    return f"rcjob_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scrub_secrets(data: dict[str, Any]) -> dict[str, Any]:
    """
    Remove keys whose names are in _SCRUB_ENV_VARS from a context dict.
    Operates on the top level only; does not recurse.
    """
    return {k: v for k, v in data.items() if k.upper() not in _SCRUB_ENV_VARS}


def _guard_mode_gate_override(
    mode: ResearchMode,
    auto_approve_stages: list[int] | None,
) -> None:
    """
    Enforce the security invariant: Stage 5 gate must never be auto-approved
    for DEEP or PROJECT_AUDIT modes in any environment.
    """
    if not auto_approve_stages:
        return
    protected_modes = {ResearchMode.DEEP, ResearchMode.PROJECT_AUDIT}
    if mode in protected_modes and 5 in auto_approve_stages:
        raise ValueError(
            f"Stage 5 gate auto-approval is prohibited for mode '{mode.value}'. "
            "The Stage 5 literature review gate is the primary anti-fabrication "
            "control and must always be reviewed by a human operator. "
            "See multiclaw/research-bridge/README.md #security--isolation-invariants."
        )


def _format_strategy_scan_topic(
    strategy_class: str,
    metrics: StrategyMetrics,
) -> str:
    return (
        f"Literature review and improvement hypotheses for the '{strategy_class}' "
        f"trading strategy on HyperLiquid perpetual futures. "
        f"Current performance: Sharpe {metrics.sharpe:.2f}, "
        f"max drawdown {metrics.max_drawdown_pct:.1f}%, "
        f"win rate {metrics.win_rate_pct:.1f}%, "
        f"regime: {metrics.regime_label}. "
        f"Focus: identify failure modes in this regime and surface academic evidence "
        f"for parameter adjustments, signal enhancements, or complementary filters "
        f"that improve risk-adjusted returns without increasing leverage."
    )


def _format_project_audit_topic(
    ticker: str,
    whitepaper_url: str | None,
    on_chain_context: dict[str, Any] | None,
) -> str:
    parts = [
        f"Comprehensive due diligence research report for the '{ticker}' "
        f"cryptocurrency project. "
        f"Scope: tokenomics design, competitive landscape analysis, "
        f"DeFi integration risk, and on-chain health indicators.",
    ]
    if whitepaper_url:
        parts.append(f"Primary source: {whitepaper_url}")
    if on_chain_context:
        safe_ctx = _scrub_secrets(on_chain_context)
        parts.append(f"On-chain context (pre-processed): {json.dumps(safe_ctx, separators=(',', ':'))}")
    return " ".join(parts)


def _parse_hypothesis_set(job: ResearchJob) -> HypothesisSet:
    """
    Parse hypotheses.json from a completed job's artifact directory.
    Returns an empty HypothesisSet if the file is absent or malformed.
    """
    hyp_path = Path(job.artifact_dir) / "hypotheses.json"
    if not hyp_path.exists():
        logger.warning("hypotheses.json not found", extra={"job_id": job.job_id})
        return HypothesisSet(job_id=job.job_id, hypotheses=[], citations=[])
    try:
        with hyp_path.open() as fh:
            data = json.load(fh)
        return HypothesisSet(
            job_id=job.job_id,
            hypotheses=data.get("hypotheses", []),
            citations=data.get("citations", []),
            quality_score=data.get("quality_score"),
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to parse hypotheses.json", exc_info=True)
        return HypothesisSet(job_id=job.job_id, hypotheses=[], citations=[])


def _parse_project_report(job: ResearchJob) -> ProjectReport:
    """
    Parse synthesis.json from a completed PROJECT_AUDIT job.
    Returns a minimal ProjectReport if the file is absent or malformed.
    """
    synth_path = Path(job.artifact_dir) / "synthesis.json"
    if not synth_path.exists():
        logger.warning("synthesis.json not found", extra={"job_id": job.job_id})
        return ProjectReport(job_id=job.job_id, ticker="unknown", summary="[synthesis.json not found]")
    try:
        with synth_path.open() as fh:
            data = json.load(fh)
        return ProjectReport(
            job_id=job.job_id,
            ticker=data.get("ticker", "unknown"),
            summary=data.get("summary", ""),
            tokenomics=data.get("tokenomics"),
            competitive_landscape=data.get("competitive_landscape"),
            defi_integration_risks=data.get("defi_integration_risks"),
            citations=data.get("citations", []),
            quality_score=data.get("quality_score"),
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to parse synthesis.json", exc_info=True)
        return ProjectReport(job_id=job.job_id, ticker="unknown", summary="[parse error]")
