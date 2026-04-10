# hyperliquid-trading-firm — Development Plan

> **Version:** 3.0.0
> **Tracks:** SPEC.md v3.0
> **Updated:** 2026-04-10
> **Supersedes:** DEVELOPMENT_PLAN-v1.md (v1.0.0), DEVELOPMENT_PLAN.md (v2.1.0)
> **Target:** Paper trading continuous operation with full audit trail
> **Repo:** https://github.com/enuno/hyperliquid-trading-firm

---

## Overview

This plan covers eight sequential phases. Each phase has an explicit exit gate — a condition that
**must** be met before work on the next phase begins. No phase is skipped.

The system adopts [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
as the agent framework foundation, extending it with HyperLiquid-specific adapters, a
deterministic quant pre-processing layer, the SAE hard safety layer, Clawvisor HITL governance,
treasury management, autonomous optimizer agent, and full DecisionTrace audit infrastructure.

All architecture decisions are governed by `SPEC.md` v3.0. When this plan conflicts with
`SPEC.md`, `SPEC.md` wins and this document is updated.

---

## Current State — Implementation Inventory (as of 2026-04-10)

### Implemented with real code

| Component | File | Lines | Status |
|:--|:--|:--|:--|
| IntelliClaw client | `apps/agents/src/tools/intelliclaw_client.py` | 222 | Full HTTP client with caching, retry, alert stream |
| IntelSnapshot types | `apps/agents/src/types/intel.py` | 190 | Complete dataclass schema |
| Research types | `apps/agents/src/types/research.py` | 270 | ResearchJob, HypothesisSet, ProjectReport |
| Evolution types | `apps/agents/src/types/evolution.py` | 560 | EvolutionTask, SolvedTask, EvolutionRound |
| ResearchAgent | `apps/agents/src/agents/research_agent.py` | 873 | Full AutoResearchClaw integration |
| Evolution Curriculum Agent | `apps/agents/src/agents/evolution_curriculum_agent.py` | 1246 | Agent0-pattern curriculum co-evolution |
| HyperLiquid feed | `apps/quant/feeds/hyperliquid_feed.py` | 526 | REST bootstrap + WS delta + reconciliation |
| Regime mapper | `apps/quant/regimes/regime_mapper.py` | 231 | QZRegime to MarketRegime mapping |
| Wave detector | `apps/quant/signals/wave_detector.py` | 643 | Deterministic multi-TF wave structure |
| Wave adapter | `apps/quant/signals/wave_adapter.py` | 296 | WaveDetector bridge to ObservationPack |
| Kelly sizing | `apps/quant/sizing/kelly_sizing_service.py` | 252 | Fractional Kelly with OOS gating |
| Recall client | `apps/data_sources/recall/recall_client.py` | 577 | Recall Network API client |
| Recall ablation bridge | `apps/jobs/recall_ablation_bridge.py` | 100 | Recall to Ablation to Registry pipeline |
| Research prompts | `prompts/research/*.yaml` | 3 files | market_structure, crypto_project_scan, strategy_evaluation |
| Proto schema | `proto/recall.proto` | 1 file | Recall Network data contract |
| Sentiment analyst stub | `apps/agents/src/agents/sentiment_analyst.py` | 8 | Minimal skeleton (reference pattern) |
| Base strategy stub | `apps/agents/src/strategies/base_strategy.py` | 28 | Skeleton with empty hooks |
| Strategy registry | `apps/orchestrator-api/src/services/StrategyRegistry.ts` | 1 file | Static list of 4 strategies |

### External projects (multiclaw/ submodules)

All with substantial real code: AutoResearchClaw, researchclaw-skill, research-bridge,
agent0-evolution, metaclaw, hyperliquid-claw, intelliclaw, mlflow, openclaw-supermemory, bankr.

### Empty / not yet implemented (~80 files, 0 bytes)

- **Entire orchestrator-api** — routes, services, types (13 files)
- **Entire sae-engine** — index, policy engine, types (5 files)
- **Entire dashboard** — pages, components, API (8 files)
- **Entire executors** — HL executor, DEX, Hummingbot (4 files)
- **11 core agent stubs** — all analysts except sentiment, researchers, trader, risk council, fund manager
- **All tool stubs** except intelliclaw_client — market_data, news, onchain, rag, sentiment
- **All strategy implementations** — grid_bot, dca_bot, rsi_reversion, hyperliquid_perps_meta
- **All config files** — db.yaml, logging.yaml, queues.yaml, strategy YAMLs
- **All tests** — agents, executors, orchestrator, sae-engine (empty READMEs only)
- **docker-compose.yml** and **Makefile** (0 bytes)
- **All K8s base deployment manifests** (0 bytes)
- **logic/** directory (abandoned duplicate of apps/agents/src/, all 0 bytes)

### Missing directories (referenced in SPEC but do not exist)

- `strategy/` — no strategy_paper.py, strategy_live.py, strategy_base.py, strategy_vault.py
- `agent/` — no safety.py, live_bot.py, paper_bot.py, rl_buffer.py, recovery.py, exchange.py, harness.py, iteration_loop.py
- `packages/` — no schemas, prompt-policies, or strategy-sdk

---

## Phase 0 — Scaffolding and Contract-First Foundation

**Goal:** Every service can boot, the contract layer compiles, and the local dev environment is
fully reproducible.

### Tasks

- [ ] **P0-01** Create missing top-level directories per SPEC.md §28: `strategy/`, `agent/`,
      `packages/schemas/`, `packages/prompt-policies/`, `packages/strategy-sdk/`
- [ ] **P0-02** Remove abandoned `logic/` directory (all 0 bytes, duplicate of `apps/agents/src/`)
- [ ] **P0-03** Write all `.proto` files per SPEC.md §8 (`common`, `decisioning`, `risk`,
      `execution`, `controlplane`) — currently only `recall.proto` exists
- [ ] **P0-04** Set up protobuf codegen pipeline (buf.build or protoc) generating Python +
      TypeScript clients into `packages/schemas/`
- [ ] **P0-05** Write JSON Schema equivalents for all handoff artifacts (used for REST and storage)
- [ ] **P0-06** Implement `docker-compose.yml` (currently 0 bytes) with: Postgres, Redis, MLflow,
      all service containers (stub health endpoints only)
- [ ] **P0-07** Implement `Makefile` (currently 0 bytes) with targets: `make boot`, `make codegen`,
      `make test-contracts`, `make lint`, `make migrate`
- [ ] **P0-08** Populate `.env.example` with all required variables from SPEC.md §29 (partially
      done — currently 570 bytes with basic vars, needs SAE/Kelly/Treasury/Fund Manager vars)
- [ ] **P0-09** Set up Postgres schema migrations (Alembic for Python, raw SQL for TS) for all
      tables in SPEC.md §25
- [ ] **P0-10** Write contract test suite in `tests/contract/` — verifies proto-generated models
      serialize/deserialize correctly in both TS and Python
- [ ] **P0-11** Add `tradingagents` as git submodule under `apps/agents/tradingagents/`
      pointing to `TauricResearch/TradingAgents`
- [ ] **P0-12** Create `strategy/strategy_base.py` with locked `BaseStrategy` interface and
      `StrategyConfig` dataclass per SPEC.md §11.2
- [ ] **P0-13** Create `strategy/strategy_paper.py` (initial agent-editable implementation)
- [ ] **P0-14** Create `strategy/strategy_live.py` (placeholder, written only by promotion logic)
- [ ] **P0-15** Create `strategy/strategy_vault.py` (vault transfer logic)
- [ ] **P0-16** Implement stub health endpoints for: `apps/orchestrator-api`, `apps/sae-engine`,
      `apps/executors`, `apps/treasury/` (all currently 0 bytes)
- [ ] **P0-17** Populate empty config files: `config/db.yaml`, `config/logging.yaml`,
      `config/queues.yaml`, `config/strategies/*.yaml`
- [ ] **P0-18** Implement K8s base manifests in `infra/k8s/base/` (all currently 0 bytes)
- [ ] **P0-19** Write `docs/tradingagents-integration.md` per SPEC.md §4
- [ ] **P0-20** Write `docs/treasury.md` documenting conversion strategy and thresholds
- [ ] **P0-21** Add pre-commit hooks: `ruff`, `mypy`, `eslint`, `prettier`

### Exit Gate

- `make boot` starts all containers without errors
- `make codegen` regenerates schemas from proto without errors
- `make test-contracts` passes (TS + Python round-trip serialization)
- `make migrate` runs without errors on a clean Postgres instance
- `POST /healthz` returns 200 on orchestrator-api, sae-engine
- All table definitions present in migration files including `treasury_events` and `optimizer_runs`

---

## Phase 1 — Data Ingestion and Analyst Layer

**Goal:** Five specialist analyst agents consume real data sources and produce typed
`ResearchPacket` artifacts. Quant layer integrated into ObserverAgent. No trading decisions yet.

### Tasks

#### Quant Layer Integration (already implemented, needs wiring)

- [x] **P1-01** `HyperliquidFeed` — REST/WS feed with reconciliation (526 lines, complete)
- [x] **P1-02** `WaveDetector` + `WaveAdapter` — wave structure detection (939 lines combined, complete)
- [x] **P1-03** `RegimeMapper` — QZRegime to MarketRegime mapping (231 lines, complete)
- [x] **P1-04** `KellySizingService` — fractional Kelly with OOS gating (252 lines, complete)
- [ ] **P1-05** Implement `ObserverAgent` — assembles `ObservationPack` from quant outputs +
      `HLMarketContext` + IntelliClaw data per SPEC.md §5.1 and §21.5

#### IntelliClaw (partially implemented, needs tests)

- [x] **P1-06** `intelliclaw_client.py` — full HTTP client (222 lines, complete)
- [x] **P1-07** `intel.py` types — IntelSnapshot, IntelHeadline, etc. (190 lines, complete)
- [ ] **P1-08** Unit tests: `tests/unit/test_intel_schema.py` — valid payload, legacy alerts,
      `to_analyst_context()`, `has_critical_alerts`
- [ ] **P1-09** Unit tests: `tests/unit/test_intelliclaw_client.py` — mock HTTP 200/500, cache
      hit, bypass_cache, multi_snapshot partial failure
- [ ] **P1-10** Integration test: `tests/integration/test_intelliclaw_live.py` (requires live service)

#### Data Source Adapters

- [ ] **P1-11** Implement `apps/agents/src/tools/market_data.py` (currently 0 bytes) — HL
      candles, order book, funding rate, OI adapter
- [ ] **P1-12** Implement `apps/agents/src/tools/sentiment.py` (currently 0 bytes) — social
      sentiment with bot-filter weights
- [ ] **P1-13** Implement `apps/agents/src/tools/news.py` (currently 0 bytes) — news feed adapter
- [ ] **P1-14** Implement `apps/agents/src/tools/onchain.py` (currently 0 bytes) — HL vault
      flows, liquidation map, whale tracker
- [ ] **P1-15** Implement `MarketSnapshot` builder: assembles all sources into timestamped
      snapshot; writes to Postgres `market_snapshots` table
- [ ] **P1-16** Add stale-data detection: flag `has_data_gap` if any source > 60s old

#### Analyst Agents (all currently 0 bytes except sentiment_analyst stub)

- [ ] **P1-17** Implement `sentiment_analyst.py` — complete the existing 8-line stub using
      IntelliClaw sentiment + headlines; write prompt policy to
      `packages/prompt-policies/analyst/sentiment/v1/`
- [ ] **P1-18** Implement `fundamental_analyst.py` (0 bytes) — consumes `intel.fundamental`,
      fetches macro data; output `AnalystScore`
- [ ] **P1-19** Implement `news_analyst.py` (0 bytes) — consumes `intel.headlines` +
      `intel.key_points`; output `AnalystScore`
- [ ] **P1-20** Implement `market_analyst.py` (0 bytes) — primary from HL candles + technical
      indicators; output `AnalystScore`
- [ ] **P1-21** Implement `onchain_analyst.py` (0 bytes) — HL-specific: vault flows, liquidation
      map, whale tracker; output `AnalystScore`
- [ ] **P1-22** Implement `apps/agents/src/types/reports.py` (0 bytes) — all typed `*AnalystReport`
      dataclasses
- [ ] **P1-23** Implement `ResearchPacket` assembler: aggregates 5 `AnalystScore` objects +
      `MarketRegime` + feature flags
- [ ] **P1-24** Implement `apps/agents/src/config/model_routing.yaml` (0 bytes) — LLM model
      routing per agent role per SPEC.md §4.4

#### Market Data Ingestor

- [ ] **P1-25** Implement `apps/jobs/src/backtest_runner.py` market ingestor component (0 bytes)
      — polls HL `candleSnapshot` API, writes to `candles` table
- [ ] **P1-26** WebSocket `candle` stream subscription for live incremental updates
- [ ] **P1-27** Backfill job: loads 365-day rolling window of 1-minute candles on first start

#### Orchestrator — Analyst Dispatch

- [ ] **P1-28** Implement `apps/orchestrator-api/src/index.ts` (0 bytes) — Express/Fastify server
- [ ] **P1-29** Implement `apps/orchestrator-api/src/routes/health.ts` (0 bytes) — health check
- [ ] **P1-30** Implement analyst dispatch: fan-out to 5 analysts in parallel, collect results
      with per-analyst timeout (30s), assemble `ResearchPacket`
- [ ] **P1-31** Implement partial `DecisionTrace` write after analyst stage completes

### Exit Gate

- `POST /cycles/trigger` with `mode: paper` produces a complete `ResearchPacket` in Postgres
- All 5 analyst scores populated with real data (no stubs or hardcoded values)
- `has_data_gap` flag correctly set when a source is stale or unavailable
- `DecisionTrace` row exists in Postgres with populated `research_packet` field
- `make test tests/unit/test_intel_schema.py` — all pass
- `make test tests/unit/test_intelliclaw_client.py` — all pass

---

## Phase 2 — Debate, Trader Agent, and Trace Persistence

**Goal:** Full decision pipeline from analysts through to `TradeIntent`, with every artifact
persisted. No execution yet; executor remains stubbed.

### Tasks

#### Researchers and Debate

- [ ] **P2-01** Implement `bullish_researcher.py` (0 bytes) — consumes `ResearchPacket`, produces
      bull thesis with evidence refs; prompt policy in `packages/prompt-policies/bull/v1/`
- [ ] **P2-02** Implement `bearish_researcher.py` (0 bytes) — bear thesis; prompt policy in
      `packages/prompt-policies/bear/v1/`
- [ ] **P2-03** Implement debate `facilitator.py` — N rounds (configurable, default 2), produces
      `DebateOutcome` with `consensus_strength` and `open_risks`
- [ ] **P2-04** Implement `consensus_strength` gate: if below threshold, emit FLAT and persist
      trace without proceeding to trader

#### Trader Agent

- [ ] **P2-05** Implement `trader_agent.py` (0 bytes) — consumes `ResearchPacket` + `DebateOutcome`,
      produces typed `TradeIntent`; calls `KellySizingService` for sizing
- [ ] **P2-06** Implement `TradeIntent` validation: all fields present, `action` is valid
      `Direction`, `confidence` in [0,1], `target_notional_pct` within bounds

#### Orchestration and Persistence

- [ ] **P2-07** Wire full cycle: analyst → debate → trader → write partial `DecisionTrace`
- [ ] **P2-08** Implement stubbed execution path: log intent, record `result: no_fill`
- [ ] **P2-09** Implement `GET /traces/:id` endpoint
- [ ] **P2-10** Implement `GET /traces` with pagination and filters

### Exit Gate

- `POST /cycles/trigger` returns a complete `DecisionTrace` with `research_packet`,
  `debate_outcome`, and `trade_intent` all populated
- `consensus_strength < threshold` correctly routes to FLAT without invoking trader
- All artifacts retrievable via `GET /traces/:id`
- No execution attempted (executor stub receives zero calls)

---

## Phase 3 — Risk Council, Fund Manager, and SAE

**Goal:** Three-profile risk committee, fund-manager portfolio governance, and non-bypassable
SAE approval. Architecture invariants verified by automated tests.

### Tasks

#### Risk Committee

- [ ] **P3-01** Implement `risk_agent_aggressive.py` (0 bytes) — consumes `TradeIntent` +
      portfolio state, emits `RiskVote`
- [ ] **P3-02** Implement `risk_agent_neutral.py` (0 bytes) — same pattern
- [ ] **P3-03** Implement `risk_agent_conservative.py` (0 bytes) — same pattern
- [ ] **P3-04** Implement committee aggregator: 3 votes → `RiskReview` with `committee_result`
      logic (all approve / approve_with_modification / reject)
- [ ] **P3-05** Write prompt policies for all 3 risk profiles

#### Fund Manager

- [ ] **P3-06** Implement `fund_manager.py` (0 bytes) — consumes `ExecutionApprovalRequest`,
      applies concentration/PnL/correlation constraints per SPEC.md §17
- [ ] **P3-07** Emits `ExecutionApproval` with `final_notional_pct`, `final_leverage`,
      `execution_algo`

#### SAE Engine

- [ ] **P3-08** Implement `apps/sae-engine/src/index.ts` (0 bytes) — all SAE checks per
      SPEC.md §16.1 as deterministic rule functions; **no LLM calls**
- [ ] **P3-09** Implement SAE check execution order: sequential, first failure stops and rejects
- [ ] **P3-10** Implement `ExecutionDecision` emitter with `staged_requests` when approved
- [ ] **P3-11** Implement SAE policy hot-reload via `POST /sae/policies/reload`
- [ ] **P3-12** Write initial SAE policy YAML in `config/policies/default_v1.yaml` with all
      thresholds from SPEC.md §16.1

#### Architecture Invariant Tests

- [ ] **P3-13** Test: no `ExecutionRequest` created unless `ExecutionDecision.allowed == true`
- [ ] **P3-14** Test: executor receives zero calls when SAE rejects
- [ ] **P3-15** Test: `RiskReview.committee_result == reject` produces no `ExecutionApproval`
      when `require_risk_unanimity` configured
- [ ] **P3-16** Full cycle trace test: verify all 8 artifact types present in `DecisionTrace`

### Exit Gate

- All invariant tests pass (P3-13 through P3-16)
- Full `DecisionTrace` with all 8 artifact types persisted
- SAE rejects correctly when any policy threshold is exceeded
- `POST /sae/policies/reload` takes effect within 5s without restart
- No LLM calls anywhere in `apps/sae-engine/` (verified by grep in CI)

---

## Phase 4 — Paper Executor, Treasury, and Evaluation Harness

**Goal:** Real HyperLiquid paper trading with fill reconciliation, treasury module operational
in paper mode, full backtesting capability, ablation suite, and MLflow experiment tracking.

### Tasks

#### Paper Executor

- [ ] **P4-01** Implement `apps/executors/src/hyperliquid_executor.py` (0 bytes) — submits
      `ExecutionRequest` to HL paper API using staged requests; handles partial fills;
      records `FillReport`
- [ ] **P4-02** Implement `FillReconciler` — updates portfolio state from fill reports
- [ ] **P4-03** Implement paper portfolio state machine: FLAT → OPENING → LONG/SHORT → CLOSING → FLAT
- [ ] **P4-04** Implement funding payment accrual for open positions (mark-to-market every 8h)
- [ ] **P4-05** Implement slippage and fee modeling per HL maker/taker fee schedule

#### Treasury Module (Paper Mode)

- [ ] **P4-06** Implement `TreasuryManager` — evaluates realized PnL against conversion triggers
      per SPEC.md §20
- [ ] **P4-07** In paper mode, treasury conversions are simulated; log to `treasury_events`
      with `mode: paper`
- [ ] **P4-08** Implement `ConversionPolicy` loader from `config/policies/treasury_default_v1.json`
- [ ] **P4-09** Write `treasury_event` field into `DecisionTrace` JSON

#### Strategy Iteration and Autoresearch

- [ ] **P4-10** Create `agent/harness.py` — backtest scoring: Sharpe, max_dd, win_rate,
      profit_factor, n_trades; 5-min timeout via `asyncio.wait_for`
- [ ] **P4-11** Create `agent/rl_buffer.py` — async write `PaperTradeOutcome`, rolling aggregates,
      `meets_promotion_criteria()` check
- [ ] **P4-12** Create `agent/paper_bot.py` — continuous 24/7 WS subscription, signal generation
      via `strategy_paper.py`, simulated fills, RL buffer writes
- [ ] **P4-13** Create `agent/iteration_loop.py` — overnight autoresearch engine:
      `build_proposal_context()`, LLM propose, validate, backtest, score, git commit
- [ ] **P4-14** Implement `validate_strategy_module()` — AST parse, security checks, max 3
      param changes
- [ ] **P4-15** `should_keep()` logic: hard reject on max_dd > 0.08 or n_trades < 10;
      accept if Sharpe improves

#### Evaluation Jobs

- [ ] **P4-16** Implement `apps/jobs/src/backtest_runner.py` (0 bytes) — replay historical
      cycles; outputs MLflow run
- [ ] **P4-17** Implement ablation variants in `apps/jobs/src/rl_execution_trainer.py` (0 bytes):
      single_agent, no_debate, no_risk_committee, no_sae (paper only), no_fund_manager,
      no_treasury, full_system
- [ ] **P4-18** Implement `apps/jobs/src/atlas_prompt_update.py` (0 bytes) — prompt-policy
      version candidate scoring

#### MLflow Integration

- [ ] **P4-19** All backtest runs log to MLflow via `MLFLOW_TRACKING_URI`
- [ ] **P4-20** Required fields: model family, dataset id, all `StrategyConfig` params,
      metrics, artifact URI
- [ ] **P4-21** `mlflow.log_artifact("strategy/strategy_paper.py")` on each accepted run

#### Metrics and Observability

- [ ] **P4-22** Implement metrics collector: trading, process, and safety metrics per SPEC.md §26
- [ ] **P4-23** Integrate Prometheus metrics export via `GET /metrics` on Orchestrator API
- [ ] **P4-24** Set up Grafana dashboard in `infra/observability/`

### Exit Gate

- System can run 48h continuous paper trading on BTC-PERP without crashes
- `backtest_runner.py` produces reproducible results (same seed → same output)
- All 7 ablation variants run cleanly; full_system vs single_agent comparison in MLflow
- Treasury paper-mode simulation running; `treasury_events` rows in Postgres
- overnight_loop(max_iterations=5) completes without crash
- At least 1 experiment committed to git with tag `paper/v{N}`
- ArgoCD detects commit → paper pod restarts with new strategy
- MLflow UI shows >= 1 run in experiment `backtest_*`
- No metric fabrication: all numbers traceable to actual fills

---

## Phase 5 — OpenClaw Governance and HITL

**Goal:** OpenClaw adapter fully operational, Clawvisor HITL rulesets enforced, human approval
UI live, and all governance actions logged.

### Tasks

#### OpenClaw Adapter

- [ ] **P5-01** Implement `apps/orchestrator-api/src/adapters/openclaw/` with action scope
      mapping: cycle:trigger, policy:update, hitl:approve, service:halt, service:resume,
      strategy:promote, prompt-policy:promote, treasury:convert
- [ ] **P5-02** Implement authentication: API key validation and scope enforcement
- [ ] **P5-03** Implement event push to OpenClaw: cycle events, HITL gates, fills, treasury

#### HITL Engine

- [ ] **P5-04** Implement HITL gate evaluation in Orchestrator: after `ExecutionApproval`,
      before SAE, evaluate active `HITLRuleSet`; pause cycle if any rule matches
- [ ] **P5-05** Implement `POST /governance/hitl-rules/:rule/approve` handler
- [ ] **P5-06** Implement HITL timeout handler: apply `on_timeout` policy per ruleset
- [ ] **P5-07** Load initial ruleset from `config/hitl-rulesets/default_v1.json` per SPEC.md §18

#### Governance Actions

- [ ] **P5-08** Implement strategy version promotion: requires HITL in live mode
- [ ] **P5-09** Implement prompt-policy promotion: immutable once promoted
- [ ] **P5-10** Write all governance actions to `governance_events` table

#### Dashboard

- [ ] **P5-11** Implement `apps/dashboard/` (all 0 bytes currently):
      - Market research page with 365-day candle chart
      - Paper / Live P/L views
      - Strategy experiments list with MLflow links
      - Risk and halt status page
      - HITL approval queue
      - Governance audit log
      - Treasury approval queue
- [ ] **P5-12** Dashboard API backend (FastAPI or Next.js API routes)
- [ ] **P5-13** Dashboard auth: SSO or reverse-proxy; no secrets exposed

#### 12-Hour Status Reporter

- [ ] **P5-14** Scheduled every 12h: paper P/L, live P/L, balances, drawdown, state
- [ ] **P5-15** Delivery: Slack webhook (primary), Telegram (fallback), email (tertiary)
- [ ] **P5-16** No secrets in notification payloads

### Exit Gate

- Paper cycle with `notional_pct >= 0.05` correctly opens HITL gate and pauses
- Strategy promotion rejected without HITL approval when live ruleset is active
- Treasury large-conversion HITL gate fires when above threshold
- All governance actions appear in `governance_events` within 1s
- Dashboard renders all pages with real data
- 12-hour status message delivered to Slack
- Dashboard auth blocks unauthenticated access

---

## Phase 6 — Optimizer Agent (Off-Path)

**Goal:** Autonomous AI optimizer agent operational, submitting recommendations for human
review via the governance queue — never auto-promoting.

### Tasks

- [ ] **P6-01** Implement `apps/agents/optimizer/optimizer_agent.py` as background process
      reading from Postgres `decision_traces` and `ablation_results`
- [ ] **P6-02** Implement pattern detection: correlate prompt-policy versions and strategy
      parameters with improved metrics using statistical significance thresholds
- [ ] **P6-03** Implement candidate proposal generator: creates versioned prompt-policy
      candidates with `status: candidate`
- [ ] **P6-04** Auto-submission to evaluation harness; scores to `optimizer_runs` table
- [ ] **P6-05** Governance queue poster: recommendations to `governance_events`
- [ ] **P6-06** Invariant test: optimizer has **zero ability** to call promote endpoints
      directly; all promotions require human sign-off through HITL
- [ ] **P6-07** Build optimizer recommendations view in dashboard

### Exit Gate

- Optimizer runs 24h without crash, producing at least one recommendation
- P6-06 invariant test passes (cannot self-promote)
- Recommendation visible in dashboard with scoring evidence
- Operator can approve via dashboard → HITL → promotion end-to-end

---

## Phase 7 — Live Execution and Recovery Hardening

**Goal:** HyperLiquid live execution enabled under strict conditions, full recovery state
machine, live treasury conversions, chaos testing, and runbooks verified.

### Tasks

#### Live Executor

- [ ] **P7-01** Implement `HyperLiquidLiveExecutor` — real order submission via HL SDK
- [ ] **P7-02** Implement redundant live position limit enforcement at executor level
- [ ] **P7-03** Implement live order status polling and partial fill handling
- [ ] **P7-04** Implement `POST /control/emergency-close` — immediate FLAT via reduce-only
      market orders

#### Live Bot and Vault

- [ ] **P7-05** Create `agent/live_bot.py` — real-fund execution with `LiveSession` state
      per SPEC.md §14
- [ ] **P7-06** Implement vault deduction: `close_position_and_vault()` per SPEC.md §14.2
- [ ] **P7-07** Create `agent/exchange.py` — HL SDK auth, rate-limit wrapper (locked file)

#### Safety and Recovery

- [ ] **P7-08** Create `agent/safety.py` — kill switches, drawdown guard, `TradingHalt`
      exception per SPEC.md §16.3
- [ ] **P7-09** Create `agent/recovery.py` — `RecoveryState` machine per SPEC.md §15;
      triggers on equity <= 50% of session start
- [ ] **P7-10** Implement promotion logic: `promote_to_live()` in paper_bot — writes
      `strategy/strategy_live.py` (only write path for that file)

#### Live Treasury

- [ ] **P7-11** Enable real spot conversion in `TreasuryManager` for live mode
- [ ] **P7-12** Treasury conversions > threshold require HITL approval
- [ ] **P7-13** Fill receipts from conversions to `treasury_events` with `mode: live`

#### Chaos and Hardening Tests

- [ ] **P7-14** `make chaos-agent-kill` — kill agents mid-cycle; no orphaned orders
- [ ] **P7-15** `make chaos-sae-kill` — kill SAE mid-cycle; executor gets no requests
- [ ] **P7-16** `make chaos-stale-data` — inject 120s stale snapshot; SAE rejects
- [ ] **P7-17** `make chaos-position-drift` — out-of-band position change; reconciler detects
- [ ] **P7-18** `make chaos-prompt-injection` — adversarial text in news; SAE gates hold

#### Runbooks and Production Readiness

- [ ] **P7-19** Write and verify all runbooks: `halt-and-resume.md`, `emergency-close.md`,
      `position-drift-recovery.md`, `prompt-policy-rollback.md`, `stale-data-incident.md`,
      `treasury-conversion-failure.md`
- [ ] **P7-20** Two-person sign-off: SAE policy YAML, HITL ruleset, live strategy config;
      both identities logged in `governance_events`
- [ ] **P7-21** 30-day continuous paper trading run with no unhandled crashes
- [ ] **P7-22** Full ablation results in MLflow showing `full_system` outperforms `single_agent`

#### Markets

- [ ] **P7-23** Live executor configured for `BTC-PERP` only (Phase 7)
- [ ] **P7-24** `ETH-PERP` gated by `n_successful_btc_iterations >= 50`

### Exit Gate

- All chaos tests pass (P7-14 through P7-18)
- 30-day paper run complete with no unhandled crashes
- Two-person sign-off complete and logged
- Live executor correctly flat-closes via `POST /control/emergency-close`
- Treasury live mode converts correctly and blocked by HITL above threshold
- All runbooks written and reviewed
- HARD: `TRADE_MODE=live` requires manual K8s Secret patch confirmed by 2nd person

---

## Implementation Defaults

### Language Choices

| Service | Language | Rationale |
|:--|:--|:--|
| `agents` | Python | TradingAgents framework is Python-native; ML/AI ecosystem |
| `jobs` | Python | Pandas/NumPy/MLflow ecosystem |
| `executors` | Python | HL Python SDK is most complete |
| `treasury` | Python | Shares portfolio state types with executors |
| `quant` | Python | NumPy/SciPy signal processing, closed-bar analysis |
| `orchestrator-api` | TypeScript/Node | Strict API discipline, low-latency coordination |
| `sae-engine` | TypeScript/Node | Deterministic rules, zero LLM runtime dependency |
| `dashboard` | Next.js (TypeScript) | React ecosystem, fast iteration on governance UI |

### Non-Negotiable Engineering Rules

1. **No LLM output is executable trading authority on its own** — all agent outputs are
   typed artifacts consumed by downstream deterministic services
2. **All adaptation happens off the hot path** — prompt-policy changes, strategy upgrades,
   and evaluation results are promoted through explicit versioned gates requiring human approval
3. **SAE has zero LLM dependency** — pure rule engine; any attempt to add LLM calls requires
   architecture review and SPEC.md update
4. **DecisionTrace is immutable once written** — no in-place updates; corrections only via
   append-only amendment records
5. **Live mode always requires HITL** — `live_always_requires_human` rule may not be removed
   without two-person governance sign-off
6. **Chaos tests must pass before live** — no exceptions
7. **Optimizer agent never self-promotes** — invariant test must remain in CI permanently
8. **Closed bars only** — all quant analysis runs on closed bars; incomplete bar never included

### Testing Strategy

| Layer | Tool | Location |
|:--|:--|:--|
| Python unit tests | `pytest` | `tests/unit/` |
| TypeScript unit tests | `vitest` | `apps/*/src/__tests__/` |
| Integration tests | `pytest` (marked) | `tests/integration/` |
| Contract tests | `pytest` + `vitest` | `tests/contract/` |
| E2E dashboard tests | `playwright` | `tests/e2e/` |
| Load testing | `k6` | `tests/load/` |
| Chaos testing | manual + `chaos-mesh` | `tests/chaos/` |

### Dependency Versions (pin in `requirements.txt` and `package.json`)

| Dependency | Version | Notes |
|:--|:--|:--|
| `hyperliquid-python-sdk` | latest stable | Pin exact version |
| `aiohttp` | >= 3.9 | Async HTTP for IntelliClaw, feeds |
| `pydantic` | >= 2.0 | Data validation and config models |
| `mlflow` | >= 2.10 | Experiment tracking |
| `numpy` | >= 1.26 | Harness scoring, quant layer |
| `pandas` | >= 2.1 | Strategy signal generation |
| `pytest` | >= 8.0 | Test runner |
| `ruff` | >= 0.4 | Linter/formatter |
| `mypy` | >= 1.8 | Type checker |
| TypeScript | 5.x | Orchestrator + SAE |
| Next.js | 14.x | Dashboard |

---

## Progress Tracker

| Phase | Status | Completed | Outstanding |
|:--|:--|:--|:--|
| 0 — Scaffolding | In Progress | Repo structure, .env.example (partial), docs (extensive) | docker-compose, Makefile, protos, migrations, strategy/, agent/, packages/, K8s manifests, all config files |
| 1 — Data + Analysts | In Progress | IntelliClaw client + types, quant layer (5 modules), ResearchAgent, research prompts | Unit tests, ObserverAgent, 5 analyst agents, data tools, market ingestor, orchestrator |
| 2 — Debate + Trader | Not Started | — | Researchers, facilitator, trader agent, trace persistence |
| 3 — Risk + SAE | Not Started | — | Risk council, fund manager, SAE engine, invariant tests |
| 4 — Paper + Eval | Not Started | — | Paper executor, treasury, harness, RL buffer, paper bot, iteration loop, MLflow, ablations |
| 5 — Governance + HITL | Not Started | — | OpenClaw adapter, HITL engine, dashboard, status reporter |
| 6 — Optimizer | Not Started | — | Optimizer agent, recommendations, dashboard view |
| 7 — Live + Recovery | Not Started | — | Live executor, live bot, safety, recovery, vault, chaos tests, runbooks |

---

## Open Questions

| # | Question | Priority | Notes |
|:--|:--|:--|:--|
| 1 | **TradingAgents submodule vs vendor**: git submodule with pinned SHA (recommended) or vendored copy? | High | Needed before Phase 1 analyst wrapping |
| 2 | **LLM model provider selection**: which providers and model versions for each routing tier in `config/model-routing/`? | High | Needed before Phase 1 P1-24 |
| 3 | **IntelliClaw deployment**: run from source or pull image? Startup config? | High | Needed before Phase 1 integration tests |
| 4 | **HL mainnet vs testnet**: target mainnet or testnet for initial paper trading? | Medium | Testnet recommended until Phase 5 HITL is operational |
| 5 | **Redis**: deploy in cluster now (Phase 0) or defer to Phase 5? | Medium | In-process cache is fine for single-pod dev |
| 6 | **Dashboard auth**: Cloudflare Access, Authelia, or Nginx basic-auth for dev? | Medium | Needed before Phase 5 |
| 7 | **Treasury conversion threshold**: what USD amount triggers BTC→USDC? | Medium | Recommended: $500 min, $10K HITL threshold |
| 8 | **Two-person sign-off identities**: identify both signatories for P7-20 | Low | Needed before Phase 7 |
| 9 | **Optimizer statistical threshold**: what minimum p-value or effect size for recommendations? | Low | Needed before Phase 6 P6-02 |
| 10 | **ETH-PERP gate**: is 50 BTC iterations the right threshold or should it be time-based? | Low | Phase 7 |
| 11 | **`logic/` directory**: confirm it's an abandoned duplicate and safe to delete | Low | All files are 0 bytes; appears to be a dead mirror of `apps/agents/src/` |
