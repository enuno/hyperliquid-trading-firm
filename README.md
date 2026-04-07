# HyperLiquid Autonomous Trading Firm

This repository contains a modular, multi-agent trading system designed to run production-grade strategies on HyperLiquid perpetual futures (with extensions for DEX arbitrage and treasury flows).

The application runs as a stand-alone trading "firm" with its own agents, risk engine, and dashboard, but can also be orchestrated remotely by OpenClaw or other controllers via a clean API surface.

> **Warning:** This codebase is **experimental research software**. It is not audited and is not suitable for trading large capital without additional review, hardening, and monitoring.

---

## High-Level Architecture

The system is split into several independently deployable services:

- **Orchestrator API (`apps/orchestrator-api`)**  
  Central HTTP/WS API and coordinator. Runs TradingAgents-style decision cycles:
  1. Trigger analyst agents.
  2. Run bull/bear research debate.
  3. Ask the Trader agent for a decision.
  4. Ask the Risk Council and Fund Manager to approve/adjust.
  5. Call the SAE engine and execution adapters.

- **SAE Engine (`apps/sae-engine`)**  
  Survivability-Aware Execution middleware implementing per-strategy and per-asset policies:
  - Validates trade requests against leverage, size, and drawdown rules.
  - Builds staged execution plans (slices, pacing, algo choice).
  - Acts as a non-bypassable guardrail in front of all executors.

- **Agent Services (`apps/agents`)**  
  Python services implementing LLM-based agents and tools:
  - ATLAS-style Market/News/Fundamental/On-chain analysts.
  - Sentiment analyst with pluggable providers.
  - Bullish/Bearish researchers and debate facilitator.
  - Trader agent, three-profile Risk Council, Fund Manager.
  - **ResearchAgent** — wraps the multiclaw research-bridge to run AutoResearchClaw pipeline jobs (strategy scans, project audits, nightly digests) on behalf of human analysts.
  - **CurriculumStrategyAgent + EvolutionExecutorAgent** — Agent0-pattern curriculum co-evolution loop for autonomous strategy improvement (see [Auto-Evolution Layer](#auto-evolution-layer-agent0--metaclaw)).
  - **EvolutionOrchestrator / EvolutionScheduler** — manages full curriculum rounds, difficulty progression, regression gating, and SQLite registry persistence.
  - Strategy plugins (Open-Trader/Freqtrade-style) used by the Trader as building blocks.
  - ATLAS Adaptive-OPRO prompt optimizer and RAG utilities.

- **Executors (`apps/executors`)**  
  Venue adapters responsible for turning validated execution plans into real orders:
  - HyperLiquid perps executor.
  - Hummingbot controller for MM / arbitrage.
  - DEX gateway adapter for on-chain routes.

- **Dashboard (`apps/dashboard`)**  
  Web UI for:
  - Live positions, PnL, and equity curves.
  - Strategy configuration and regime toggles.
  - Decision traces for each trade (analyst reports → debate → trader → risk → SAE → orders).
  - Research panel for job status, gate approvals, and hypothesis review.

- **Jobs (`apps/jobs`)**  
  Offline/batch processes:
  - Backtesting and evaluation harness.
  - RL training for execution timing and strategy parameters.
  - Adaptive-OPRO prompt updates.
  - Treasury DCA/staking/profit-vault flows.

- **Multiclaw Research Bridge (`multiclaw/research-bridge`)**  
  Bridge module connecting the trading firm to the AutoResearchClaw and ResearchClaw pipelines:
  - `config.trading-firm.yaml` — active bridge configuration.
  - Injects RL buffer exports and backtest context into research topic prompts.
  - Enforces secret scrubbing; never forwards trading keys to the research pipeline.
  - See [`multiclaw/research-bridge/README.md`](multiclaw/research-bridge/README.md) for full integration docs.

- **Skills Library (`skills/`)**  
  MetaClaw-compatible skill packages providing reusable, versioned trading knowledge units:
  - **Regime Detection skills** — `high-funding-carry-avoidance`, `liquidation-cascade-risk`, `trending-bull-entry-timing`
  - **Execution skills** — `maker-order-preference-fee-reduction`, `limit-offset-bps-calculation`, `slippage-budget-enforcement`
  - **Risk skills** — `kelly-position-sizing-perps`, `drawdown-kill-switch-trigger`, `max-concurrent-positions`
  - **Strategy skills** — `ema-cross-failure-modes`, `rsi-reversal-regime-dependency`, `funding-rate-awareness`
  - `skills-lock.json` pins all installed skill versions for reproducibility.

- **Prompt Templates (`prompts/`)**  
  Structured YAML prompt templates for research pipeline modes:
  - `market_structure.yaml` — NIGHTLY_DIGEST mode.
  - `strategy_evaluation.yaml` — STRATEGY_SCAN mode.
  - `crypto_project_scan.yaml` — PROJECT_AUDIT mode.

- **Infra (`infra/`)**  
  Kubernetes manifests, Terraform modules, and Helm charts for production deployment.

---

## Key Concepts

### Multi-Agent Firm Structure

The system models a trading "firm" rather than a single bot:
- Analysts prepare structured market intelligence.
- Researchers debate the bull and bear cases.
- Trader agent proposes trades.
- Risk Council (aggressive/neutral/conservative) votes per trade.
- Fund Manager applies portfolio-level constraints.
- SAE engine validates and stages execution.

### ATLAS Market Intelligence + Adaptive-OPRO

Analyst microservices implement ATLAS-style Market, News, and Fundamental pipelines, feeding structured context into decision agents. Adaptive-OPRO runs offline to continually refine the Trader's prompt and hyperparameters based on realized performance.

### SAE (Survivability-Aware Execution)

All trades pass through a dedicated engine that enforces:
- Position and leverage caps.
- Drawdown-aware regime selection.
- Staged execution with algo hints (TWAP/VWAP/POV/Iceberg).
- Integration with RL-based execution agents for timing.

### Strategy Plugins

Classical strategies (grid, DCA, RSI reversion, EMA cross, funding-rate carry, etc.) are implemented as small Python classes with a common interface. The LLM Trader agent can select and configure these strategies dynamically, combining human-readable logic with agentic decision-making.

### Auto-Evolution Layer (Agent0 + MetaClaw)

The firm includes an autonomous strategy improvement layer modelled on the Agent0 curriculum co-evolution approach:

- **CurriculumStrategyAgent** — proposes difficulty-progressive task batches across six task families (`regime_detection`, `execution_optimization`, `risk_sizing`, `multi_asset_basis`, `liquidation_cascade`, `funding_carry`) and eight market regime contexts. Task difficulty auto-progresses when the executor solve-rate exceeds 80% for two consecutive rounds.
- **EvolutionExecutorAgent** — solves tasks via tool-integrated chain-of-thought reasoning. Reward signal is always an objective backtest metric (Sharpe/Sortino/Calmar) from the `_BacktestOracle` — never LLM-judged, ensuring ground-truth verifiability.
- **EvolutionOrchestrator** — manages the full round lifecycle: curriculum generation → executor solving → scoring → regression gate → checkpoint manifest creation (human-gated, `approved=False` by default).
- **EvolutionScheduler** — async entry point with configurable cron schedule and sleep-window awareness so evolution rounds never interrupt live trading sessions.

**Safety invariants** (all enforced in code):
- No import of, or dependency on, SAEMiddleware, the execution engine, or any live order path.
- No writes to `strategy.py`, `config/`, or any locked file.
- All artifacts are scoped to `logs/evolution/artifacts/<round_id>/`.
- Checkpoint promotion requires human gate (`approved=True` via dashboard or registry REST API).
- Regression gate blocks promotion if Sharpe degrades > 10% vs. production baseline.

### Multiclaw Research Architecture

The research subsystem is a multi-claw architecture integrating two complementary tools:

- **AutoResearchClaw** (karpathy-style) — used for deep strategy research, lit review, and auto-tuning via the research-bridge pipeline. Runs gated 23-stage research jobs with mandatory human checkpoints at Stages 5, 9, and 20.
- **ResearchClaw / OpenClaw** (OthmanAdi, aiming-lab) — end-user-centric, supplemental research tool for analyst-initiated queries and project due-diligence reports.

The `ResearchAgent` class orchestrates both tools. All job state is persisted in `logs/research/research_registry.db` and surfaced via the dashboard research panel.

---

## LLM Configuration

The agent layer uses an OpenAI-compatible chat completions endpoint configured via environment variables. Set the following in your `.env`:

```env
HL_LLM_BASE_URL=https://api.your-llm-provider.com/v1
HL_LLM_API_KEY=<your-api-key>
HL_LLM_MODEL_ID=moonshotai/Kimi-K2.5   # default
```

If these are unset, all LLM clients fall back to a deterministic stub mode (safe for CI and unit testing without a live LLM).

---

## Getting Started (Dev)

### Prerequisites

- Docker / Docker Compose
- Node.js (LTS) + pnpm or npm
- Python 3.11+
- A HyperLiquid testnet API key
- Access tokens for your LLM provider(s)

### Quick Start

Clone and enter the repo:

```bash
git clone https://github.com/enuno/hyperliquid-trading-firm.git
cd hyperliquid-trading-firm
```

Copy environment template and edit:

```bash
cp .env.example .env
# edit .env with API keys, DB connection strings, LLM endpoint, etc.
```

Copy the research bridge config:

```bash
cp multiclaw/research-bridge/config.trading-firm.example.yaml \
   multiclaw/research-bridge/config.trading-firm.yaml
# edit with your AutoResearchClaw endpoint and quality thresholds
```

Start core services in development mode:

```bash
docker-compose up -d
```

This brings up:

- Orchestrator API
- SAE engine
- Agent workers
- HyperLiquid executor (paper mode)
- Postgres / Redis
- Dashboard (http://localhost:3000 by default)

### Running a Single Evolution Round (One-Shot)

```python
from apps.agents.src.agents.evolution_curriculum_agent import EvolutionOrchestrator
import asyncio

orchestrator = EvolutionOrchestrator()
result = asyncio.run(orchestrator.run_round())
print(result.status, result.solve_rate_pct, result.mean_sharpe)
```

### Running a Research Job

```python
from apps.agents.src.agents.research_agent import ResearchAgent, ResearchMode

agent = ResearchAgent.from_config()
job = asyncio.run(agent.run_deep_research(
    topic="EMA crossover failure modes in high-funding-rate perps regimes",
    mode=ResearchMode.STRATEGY_SCAN,
))
print(job.job_id, job.status)
```

---

## Repository Layout

```text
apps/
  quant/                    # Quant-Zero Kelly Sizing
  orchestrator-api/         # Node/TS REST+WS API and agent coordination
  sae-engine/               # TypeScript SAE policy evaluation and staging
  agents/
    src/
      agents/               # Python LLM agents
        research_agent.py           # ResearchAgent (multiclaw bridge)
        evolution_curriculum_agent.py  # CurriculumStrategyAgent, EvolutionExecutorAgent,
                                       # EvolutionOrchestrator, EvolutionScheduler
        sentiment_analyst.py
        bearish_researcher.py / bullish_researcher.py
        fund_manager.py / trader_agent.py
        risk_agent_{aggressive,neutral,conservative}.py
        market_analyst.py / news_analyst.py / fundamental_analyst.py / onchain_analyst.py
      types/
        research.py         # ResearchJob, ResearchMode, StrategyMetrics, HypothesisSet, etc.
        evolution.py        # EvolutionTask, SolvedTask, EvolutionRound, CheckpointManifest, etc.
  executors/                # Python venue adapters (HyperLiquid, Hummingbot, DEX)
  dashboard/                # Web UI (React/Next.js) with research panel
  jobs/                     # Offline backtests, RL training, prompt updates, treasury flows

multiclaw/
  research-bridge/          # AutoResearchClaw + ResearchClaw bridge
    README.md               # Full integration documentation
    config.trading-firm.yaml           # Active bridge config (gitignored secrets)
    config.trading-firm.example.yaml   # Annotated example config

skills/                     # MetaClaw skill packages (regime, execution, risk, strategy)
  regime-detection/
    high-funding-carry-avoidance/
    liquidation-cascade-risk/
    trending-bull-entry-timing/
  execution/
    maker-order-preference-fee-reduction/
    limit-offset-bps-calculation/
    slippage-budget-enforcement/
  risk/
    kelly-position-sizing-perps/
    drawdown-kill-switch-trigger/
    max-concurrent-positions/
  strategy/
    ema-cross-failure-modes/
    rsi-reversal-regime-dependency/
    funding-rate-awareness/

skills-lock.json            # Pinned skill versions

prompts/
  market_structure.yaml     # NIGHTLY_DIGEST prompt template
  strategy_evaluation.yaml  # STRATEGY_SCAN prompt template
  crypto_project_scan.yaml  # PROJECT_AUDIT prompt template

logs/
  research/
    artifacts/              # Per-job research artifacts (read-only proposals)
    research_registry.db    # SQLite job registry
    registry_summary.json   # Live JSON summary for dashboard
  evolution/
    artifacts/              # Per-round evolution artifacts
    evolution_registry.db   # SQLite evolution registry
    registry_summary.json   # Live JSON summary for dashboard
  audit.jsonl               # Firm-wide immutable audit log

infra/
  k8s/                      # Kubernetes manifests and overlays
  terraform/                # Optional infra provisioning
  helm/                     # Optional Helm charts

config/                     # Environment, logging, DB, queues, strategy configs
.claude/                    # Claude / AI agent context files (AGENTS.md refs)
tests/                      # Unit/integration tests per service
```

---

## OpenClaw / MetaClaw Integration

This application is designed to be controlled by OpenClaw or MetaClaw orchestrators:

- **OpenClaw** can:
  - Trigger decision cycles via the Orchestrator API.
  - Adjust SAE policies and strategy configs via config endpoints.
  - Inspect decision traces and metrics for auto-research loops.
  - Invoke ResearchClaw pipeline jobs via the `/research/jobs` endpoint.

- **MetaClaw** (`metaclaw/config.trading-firm.yaml`) configures:
  - Skills library binding (all skill packages under `skills/`).
  - RL policy and OPD (Offline Policy Distillation) settings.
  - Evolution scheduler cron and sleep-window configuration.

- The trading firm can also run completely standalone, with its own job schedulers, evolution loops, and dashboards.

---

## Key Documentation

| Document | Description |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Full agent roster, roles, multiclaw architecture, and safety invariants |
| [`CLAUDE.md`](CLAUDE.md) | Lean modular file with @-reference pointers for AI agent context |
| [`STRATEGY.md`](STRATEGY.md) | Strategy plugin specifications and regime taxonomy |
| [`ANALYTICS.md`](ANALYTICS.md) | Analytics, metrics definitions, and reporting |
| [`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md) | Current development roadmap and milestone tracking |
| [`SPEC.md`](SPEC.md) | Full system specification (latest) |
| [`multiclaw/research-bridge/README.md`](multiclaw/research-bridge/README.md) | Research bridge integration docs |

---

## Status

The following components are implemented and active:

- ✅ Agent package structure and `__init__` exports
- ✅ `ResearchAgent` — multiclaw/research-bridge integration with SQLite registry, audit log, and secret scrubbing
- ✅ `CurriculumStrategyAgent` + `EvolutionExecutorAgent` + `EvolutionOrchestrator` + `EvolutionScheduler` (Agent0 auto-evolution)
- ✅ Evolution type system (`EvolutionTask`, `SolvedTask`, `EvolutionRound`, `CheckpointManifest`, `RegressionResult`, etc.)
- ✅ Research type system (`ResearchJob`, `ResearchMode`, `StrategyMetrics`, `HypothesisSet`, `ProjectReport`, etc.)
- ✅ Skills library — 10 MetaClaw-compatible skill packages across regime, execution, risk, and strategy domains
- ✅ Prompt templates — NIGHTLY_DIGEST, STRATEGY_SCAN, PROJECT_AUDIT YAML templates
- ✅ `multiclaw/research-bridge` config and README
- ✅ `CLAUDE.md` rewritten as lean modular file with @-reference pointers
- ✅ `AGENTS.md` updated to reflect ResearchClaw integration and multiclaw architecture

The following components remain stubs pending implementation:

- ⬜ Full agent prompt implementations (Trader, Risk Council, Fund Manager, analysts)
- ⬜ Real agentharness backtest integration (currently stubbed in `_BacktestOracle`)
- ⬜ SAE policy rules for target assets
- ⬜ Dashboard views (research panel, evolution dashboard, metrics)
- ⬜ Live HyperLiquid executor (paper mode available)
- ⬜ `docker-compose.yml` and `Makefile` implementations

Use this as a starting point for iterative development and experimentation.
