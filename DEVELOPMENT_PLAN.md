# hyperliquid-trading-firm — Development Plan

> **Version:** 2.1.0
> **Last updated:** 2026-03-29
> **Target:** Paper trading continuous operation with full audit trail
> **Repo:** https://github.com/enuno/hyperliquid-trading-firm

---

## Overview

This plan covers seven sequential phases. Each phase has an explicit exit gate — a condition that
**must** be met before work on the next phase begins. No phase is skipped.

The system adopts [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
as the agent framework foundation, extending it with HyperLiquid-specific adapters, the SAE hard
safety layer, Clawvisor HITL governance, treasury management, autonomous optimizer agent, and
full DecisionTrace audit infrastructure.

All architecture decisions are governed by `SPEC.md`. When this plan conflicts with `SPEC.md`,
`SPEC.md` wins and this document is updated.

---

## Phase 0 — Scaffolding and Contract-First Foundation

**Goal:** Every service can boot, the contract layer compiles and passes, and the local dev
environment is fully reproducible.

### Tasks

- [ ] **P0-01** Create repo directory structure per SPEC.md §3
- [ ] **P0-02** Write all `.proto` files per SPEC.md §6 (`common`, `decisioning`, `risk`,
      `execution`, `controlplane`)
- [ ] **P0-03** Set up protobuf codegen pipeline (buf.build or protoc) generating Python +
      TypeScript clients into `packages/schemas/`
- [ ] **P0-04** Write JSON Schema equivalents for all handoff artifacts (used for REST and storage)
- [ ] **P0-05** Initialize `docker-compose.yml` with: Postgres, Redis, MLflow, all service
      containers (stub health endpoints only)
- [ ] **P0-06** Write Makefile targets: `make boot`, `make codegen`, `make test-contracts`,
      `make lint`, `make migrate`
- [ ] **P0-07** Write `.env.example` with all required variables documented and typed
- [ ] **P0-08** Set up Postgres schema migrations (Alembic for Python services, raw SQL with
      version tracking for TS services) for all tables in SPEC.md §10
- [ ] **P0-09** Add contract test suite in `tests/contract/` — verifies proto-generated models
      serialize/deserialize correctly in both TS and Python
- [ ] **P0-10** Add `tradingagents` as git submodule under `apps/agents/tradingagents/`
      pointing to `TauricResearch/TradingAgents`
- [ ] **P0-11** Stub `apps/orchestrator-api/` with health endpoint and empty cycle trigger handler
- [ ] **P0-12** Stub `apps/sae-engine/` with health endpoint and pass-through (no policy yet)
- [ ] **P0-13** Stub `apps/executors/` with health endpoint and paper stub (log only, no fills)
- [ ] **P0-14** Stub `apps/treasury/` with health endpoint and no-op conversion handler
- [ ] **P0-15** Write `docs/tradingagents-integration.md` per SPEC.md §4
- [ ] **P0-16** Write `docs/treasury.md` documenting conversion strategy and thresholds

### Exit Gate

✅ `make boot` starts all containers without errors
✅ `make codegen` regenerates schemas from proto without errors
✅ `make test-contracts` passes (TS + Python round-trip serialization)
✅ `make migrate` runs without errors on a clean Postgres instance
✅ `POST /cycles/trigger` returns 202 with a `cycle_id` (no agent work yet)
✅ All table definitions present in migration files including `treasury_events` and
   `optimizer_runs`

---

## Phase 1 — Data Ingestion and Analyst Layer

**Goal:** Five specialist analyst agents consume real data sources and produce typed
`ResearchPacket` artifacts. No trading decisions yet.

### Tasks

#### Data Sources
- [ ] **P1-01** Implement HyperLiquid REST + WebSocket adapter: OHLCV, order book snapshot,
      funding rate, open interest — use official HL Python SDK where available
- [ ] **P1-02** Implement IntelliClaw intel feed adapter (news, alpha signals) — document
      field mapping in `docs/api-contracts.md`
- [ ] **P1-03** Implement sentiment adapter: social sentiment score with confidence and
      bot-filter weight applied (per hypersignal reliability requirements documented in
      `docs/architecture.md`)
- [ ] **P1-04** Implement onchain adapter: HL vault flows, liquidation map, whale wallet
      tracker — this is the new `OnchainAnalyst` not present in base TradingAgents
- [ ] **P1-05** Implement `MarketSnapshot` builder: assembles all sources into a timestamped,
      versioned snapshot object; writes to Postgres `market_snapshots` table
- [ ] **P1-06** Add stale-data detection: flag `has_data_gap` if any source is > 60s old;
      stale snapshot must propagate `has_data_gap: true` to `ResearchPacket`

#### Analyst Agents (wrapping TradingAgents)
- [ ] **P1-07** Wrap TradingAgents `FundamentalsAnalyst` with HL adapter; output conforms to
      `AnalystScore` proto; write prompt policy to
      `packages/prompt-policies/analyst/fundamental/v1/`
- [ ] **P1-08** Wrap TradingAgents `SentimentAnalyst`; add bot-filter confidence weight to
      score calculation; output `AnalystScore`; prompt policy in
      `packages/prompt-policies/analyst/sentiment/v1/`
- [ ] **P1-09** Wrap TradingAgents `NewsAnalyst`; output `AnalystScore`; prompt policy in
      `packages/prompt-policies/analyst/news/v1/`
- [ ] **P1-10** Wrap TradingAgents `TechnicalAnalyst`; add HL-specific indicators (funding
      rate z-score, OI delta, liquidation proximity); output `AnalystScore`; prompt policy in
      `packages/prompt-policies/analyst/technical/v1/`
- [ ] **P1-11** Write new `OnchainAnalyst` (not in base TradingAgents framework); output
      `AnalystScore`; prompt policy in `packages/prompt-policies/analyst/onchain/v1/`
- [ ] **P1-12** Implement `ResearchPacket` assembler: aggregates 5 `AnalystScore` objects +
      market regime classification (`MarketRegime` enum) + all feature flags from snapshot
- [ ] **P1-13** Write `ResearchPacket` and individual `AnalystScore` records to Postgres
      `analyst_reports` table keyed on `cycle_id`

#### Orchestrator
- [ ] **P1-14** Implement analyst dispatch in Orchestrator: fan-out to 5 analysts in parallel,
      collect results with per-analyst timeout (default 30s), assemble `ResearchPacket`
- [ ] **P1-15** Implement partial `DecisionTrace` write after analyst stage completes;
      `final_state.result` set to `partial` until cycle completes

### Exit Gate

✅ `POST /cycles/trigger` with `mode: paper` produces a complete `ResearchPacket` in Postgres
✅ All 5 analyst scores populated with real data (no stubs or hardcoded values)
✅ `has_data_gap` flag correctly set when a source is stale or unavailable
✅ `DecisionTrace` row exists in Postgres with populated `research_packet` field

---

## Phase 2 — Debate, Trader Agent, and Trace Persistence

**Goal:** Full decision pipeline from analysts through to `TradeIntent`, with every artifact
persisted. No execution yet; executor remains stubbed.

### Tasks

#### Researchers and Debate
- [ ] **P2-01** Wrap TradingAgents `BullResearcher`: consumes `ResearchPacket`, produces bull
      thesis with evidence refs, score, and supporting analyst refs; prompt policy in
      `packages/prompt-policies/bull/v1/`
- [ ] **P2-02** Wrap TradingAgents `BearResearcher`: same structure for bear thesis; prompt
      policy in `packages/prompt-policies/bear/v1/`
- [ ] **P2-03** Implement debate `Facilitator`: runs N rounds (configurable via
      `config/strategies/`, default 2), produces `DebateOutcome` with `consensus_strength`
      and `open_risks`; prompt policy in `packages/prompt-policies/facilitator/v1/`
- [ ] **P2-04** Implement `consensus_strength` gate: if `consensus_strength` falls below
      `config.min_consensus_threshold`, emit `action: FLAT` and persist trace with
      `final_state.result: flat` without proceeding to trader

#### Trader Agent
- [ ] **P2-05** Wrap TradingAgents `TraderAgent` as `apps/agents/trader/trader_agent.py`
      (replaces legacy `trading_agent.py` if present); consumes `ResearchPacket` +
      `DebateOutcome`; produces typed `TradeIntent`; prompt policy in
      `packages/prompt-policies/trader/v1/`
- [ ] **P2-06** Implement `TradeIntent` validation: all required fields present, `action`
      is valid `Direction` enum, `confidence` and `thesis_strength` in [0.0, 1.0],
      `target_notional_pct` within configured bounds
- [ ] **P2-07** Migrate any logic from legacy `strategy_paper.py` / `strategy_live.py` that
      belongs in the trader agent into `trader_agent.py`; strategy files become thin plugin
      wrappers calling the agent pipeline

#### Orchestration and Persistence
- [ ] **P2-08** Wire full cycle: analyst → debate → trader → write complete partial
      `DecisionTrace` (all artifacts up to `trade_intent`)
- [ ] **P2-09** Implement stubbed execution path: if `trade_intent.action != FLAT`, log
      intent and record `result: no_fill` in `final_state`; no exchange calls
- [ ] **P2-10** Implement `GET /traces/:id` endpoint returning full `DecisionTrace` JSON
- [ ] **P2-11** Implement `GET /traces` with pagination and filters: `asset`, `mode`,
      date range, `result` type, `strategy_version`

### Exit Gate

✅ `POST /cycles/trigger` returns a complete `DecisionTrace` with `research_packet`,
   `debate_outcome`, and `trade_intent` all populated
✅ `consensus_strength < threshold` correctly routes to FLAT and persists trace without
   invoking trader
✅ All artifacts retrievable via `GET /traces/:id`
✅ No execution attempted (executor stub receives zero calls)
✅ `trading_program.md` updated to reflect multi-agent pipeline intent

---

## Phase 3 — Risk Council, Fund Manager, and SAE

**Goal:** Three-profile risk committee, fund-manager portfolio governance, and non-bypassable
SAE approval. Architecture invariants verified by automated tests.

### Tasks

#### Risk Committee
- [ ] **P3-01** Wrap TradingAgents risk management agents into 3 typed profiles:
      `RiskAggressiveAgent`, `RiskNeutralAgent`, `RiskConservativeAgent`; each in
      `apps/agents/risk/`
- [ ] **P3-02** Each profile consumes `TradeIntent` + current portfolio state (from
      `fill_reconciler` state); emits typed `RiskVote`
- [ ] **P3-03** Implement committee aggregator: combines 3 votes into `RiskReview` with
      `committee_result` logic:
      - All approve → `approve`
      - 2 approve, 1 dissents → `approve_with_modification`
      - Majority or all reject → `reject`
- [ ] **P3-04** Write prompt policies for all 3 risk profiles under
      `packages/prompt-policies/risk-aggressive/v1/`,
      `packages/prompt-policies/risk-neutral/v1/`,
      `packages/prompt-policies/risk-conservative/v1/`

#### Fund Manager
- [ ] **P3-05** Implement `FundManagerAgent` in `apps/agents/fund_manager/fund_manager_agent.py`:
      consumes `ExecutionApprovalRequest` (trade intent + risk review + portfolio state);
      applies concentration limits, daily PnL gates, correlation constraints
- [ ] **P3-06** Emits `ExecutionApproval` with `final_notional_pct`, `final_leverage`, and
      `execution_algo`; rejection sets `approved: false` with `rejection_reason`
- [ ] **P3-07** Write prompt policy for fund manager under
      `packages/prompt-policies/fund-manager/v1/`

#### SAE Engine
- [ ] **P3-08** Implement all SAE checks per SPEC.md §9.2 as deterministic rule functions
      in `apps/sae-engine/`; **no LLM calls, no network calls** inside SAE hot path
- [ ] **P3-09** Implement SAE check execution order: checks run sequentially; first failure
      stops evaluation and populates `checks_failed`; all passing checks populate
      `checks_passed`
- [ ] **P3-10** Implement `ExecutionDecision` emitter with `staged_requests` when approved
- [ ] **P3-11** Implement SAE policy hot-reload via `POST /sae/policies/reload`; policy
      changes take effect within 5 seconds without service restart
- [ ] **P3-12** Write initial SAE policy YAML files under `config/policies/default_v1.yaml`
      with all thresholds from SPEC.md §9.2 as defaults

#### Architecture Invariant Tests
- [ ] **P3-13** Write test: no `ExecutionRequest` is created unless
      `ExecutionDecision.allowed == true` — executor receives zero calls when SAE rejects
- [ ] **P3-14** Write test: executor stub receives no calls when SAE rejects
- [ ] **P3-15** Write test: `RiskReview.committee_result == reject` produces no
      `ExecutionApproval` when `require_risk_unanimity` is configured
- [ ] **P3-16** Write full cycle trace test: verify all 8 artifact types present in
      `DecisionTrace` for an approved cycle: `research_packet`, `debate_outcome`,
      `trade_intent`, `risk_review`, `execution_approval_req`, `execution_approval`,
      `sae_decision`, `final_state`

### Exit Gate

✅ All invariant tests pass (P3-13, P3-14, P3-15)
✅ Full `DecisionTrace` with all 8 artifact types persisted (P3-16)
✅ SAE rejects correctly when any policy threshold is exceeded
✅ `POST /sae/policies/reload` takes effect within 5 seconds without service restart
✅ No LLM calls exist anywhere in `apps/sae-engine/` (verified by grep in CI)

---

## Phase 4 — Paper Executor, Treasury, and Evaluation Harness

**Goal:** Real HyperLiquid paper trading with fill reconciliation, treasury module operational
in paper mode, full backtesting capability, ablation suite, and MLflow experiment tracking.

### Tasks

#### Paper Executor
- [ ] **P4-01** Implement `HyperLiquidPaperExecutor` in `apps/executors/hyperliquid_paper.py`:
      submits `ExecutionRequest` to HL paper API using staged requests from `ExecutionDecision`;
      handles partial fills; records `FillReport`
- [ ] **P4-02** Implement `FillReconciler` in `apps/executors/fill_reconciler.py`: updates
      portfolio state (position, realized PnL, unrealized PnL, exposure, drawdown) from
      fill reports; writes to Postgres `fills` table
- [ ] **P4-03** Implement paper portfolio state machine:
      `FLAT → OPENING → LONG/SHORT → CLOSING → FLAT`
- [ ] **P4-04** Implement funding payment accrual for open positions (mark-to-market every 8h)
- [ ] **P4-05** Implement slippage and fee modeling per HL maker/taker fee schedule using
      configurable fee tier in `.env`

#### Treasury Module (Paper Mode)
- [ ] **P4-06** Implement `TreasuryManager` in `apps/treasury/treasury_manager.py`: evaluates
      realized PnL against conversion triggers per `config/` treasury policy
- [ ] **P4-07** In paper mode, treasury conversions are **simulated** (no real spot orders);
      log simulated conversion events to `treasury_events` table with `mode: paper`
- [ ] **P4-08** Implement `ConversionPolicy` loader in `apps/treasury/conversion_policy.py`;
      load from `config/policies/treasury_default_v1.json` per SPEC.md §8.3
- [ ] **P4-09** Write `treasury_event` field into `DecisionTrace` JSON after each cycle that
      triggers an evaluation (even if no conversion occurs)

#### Evaluation Jobs
- [ ] **P4-10** Implement `backtest_runner.py` in `apps/jobs/`: replay historical cycles
      using only data available at each decision point; no look-ahead allowed; outputs
      MLflow run with all metrics per SPEC.md §11.1
- [ ] **P4-11** Implement ablation variants in `apps/jobs/ablation_runner.py`:
      - `variant: single_agent` — analyst scores only, no debate, no risk committee
      - `variant: no_debate` — skip debate, trader uses `ResearchPacket` directly
      - `variant: no_risk_committee` — skip risk review, fund manager only
      - `variant: no_sae` — skip SAE checks (**paper only, never live**)
      - `variant: no_fund_manager` — skip fund manager approval
      - `variant: no_treasury` — skip treasury evaluation
      - `variant: full_system` — all stages active
- [ ] **P4-12** Implement `prompt_policy_scorer.py` in `apps/jobs/`: evaluates prompt-policy
      version candidates against held-out cycles; outputs score and recommendation to
      `optimizer_runs` table

#### Metrics and Dashboard
- [ ] **P4-13** Implement metrics collector: all trading, process, and safety metrics per
      SPEC.md §11.1
- [ ] **P4-14** Integrate Prometheus metrics export via `GET /metrics` on Orchestrator API
- [ ] **P4-15** Set up Grafana dashboard per SPEC.md §11 using configs in
      `infra/observability/`
- [ ] **P4-16** Build `apps/dashboard/` decision trace viewer: cycle timeline, per-artifact
      drill-down, debate transcript, SAE check results, treasury event display
- [ ] **P4-17** Build experiment comparison view: ablation results table,
      Sharpe/drawdown/hit-rate charts per variant
- [ ] **P4-18** Build prompt-policy history view: version tree, per-version metrics, scoring
      history

### Exit Gate

✅ System can run 48h continuous paper trading on BTC-PERP without crashes or unhandled
   exceptions
✅ `backtest_runner.py` produces reproducible results (same seed → same output, verified
   by running twice)
✅ All 7 ablation variants run cleanly; `full_system` vs `single_agent` comparison available
   in MLflow
✅ Treasury paper-mode simulation running; `treasury_events` rows appearing in Postgres
✅ Dashboard shows complete trace for any cycle via `cycle_id` lookup including treasury field
✅ No metric fabrication: all numbers traceable to actual fills, simulated events, or explicit
   stubs in test fixtures

---

## Phase 5 — OpenClaw Governance and HITL

**Goal:** OpenClaw adapter fully operational, Clawvisor HITL rulesets enforced for all
configurable trigger conditions, human approval UI live, and all governance actions logged.

### Tasks

#### OpenClaw Adapter
- [ ] **P5-01** Implement `apps/orchestrator-api/src/adapters/openclaw/` with action scope
      mapping:
      - `cycle:trigger` — start a cycle
      - `policy:update` — update SAE/HITL policy
      - `hitl:approve` — approve an open HITL gate
      - `service:halt` — emergency halt
      - `service:resume` — resume after halt
      - `strategy:promote` — promote strategy version
      - `prompt-policy:promote` — promote prompt-policy version
      - `treasury:convert` — manually trigger treasury conversion
- [ ] **P5-02** Implement authentication: OpenClaw API key validation and action scope
      enforcement; unknown scopes return 403
- [ ] **P5-03** Implement event push to OpenClaw: cycle started, cycle completed, HITL gate
      opened, HITL approved, SAE rejected, fill received, treasury conversion triggered

#### HITL Engine
- [ ] **P5-04** Implement HITL gate evaluation in Orchestrator: after `ExecutionApproval`,
      before SAE, evaluate active `HITLRuleSet` — if any rule matches, pause cycle and emit
      `hitl_gate_open` event to OpenClaw; write pending state to `decision_traces`
- [ ] **P5-05** Implement `POST /governance/hitl-rules/:rule/approve` handler: resumes
      paused cycle with human identity, approval timestamp, and notes logged to
      `human_approvals` table
- [ ] **P5-06** Implement HITL timeout handler: on timeout, apply `on_timeout` policy
      (`reject` or `approve` per ruleset); log timeout event to `governance_events`
- [ ] **P5-07** Load initial ruleset from `config/hitl-rulesets/default_v1.json` per
      SPEC.md §6.6 including the `treasury_large_conversion` rule

#### Governance Actions
- [ ] **P5-08** Implement strategy version promotion: requires HITL approval in live mode;
      swaps active strategy atomically; old version remains queryable in `strategy_versions`
      registry
- [ ] **P5-09** Implement prompt-policy promotion: same pattern; version is immutable once
      promoted; only new version IDs may be created
- [ ] **P5-10** Implement `POST /governance/prompt-policies/promote` and
      `POST /governance/strategies/promote` endpoints
- [ ] **P5-11** Write all governance actions to `governance_events` table:
      promotions, approvals, halts, resumes, sign-offs, policy reloads

#### Dashboard Governance View
- [ ] **P5-12** Build HITL approval queue in dashboard: shows open gates, approval/reject
      buttons, timeout countdown, rule that triggered, cycle context
- [ ] **P5-13** Build governance audit log view: all events from `governance_events` table,
      filterable by type and date range
- [ ] **P5-14** Build treasury approval queue: shows pending large-conversion HITL gates
      with conversion amount, trigger reason, and current BTC/USDC price context

### Exit Gate

✅ Paper cycle with `notional_pct >= 0.05` correctly opens HITL gate and pauses until
   approval or timeout
✅ Strategy promotion in paper mode rejected without HITL approval when live ruleset is active
✅ Treasury large-conversion HITL gate fires when simulated conversion exceeds threshold
✅ All governance actions appear in `governance_events` within 1 second of completion
✅ `make chaos-hitl-timeout` test passes: timed-out HITL gate correctly rejects cycle and
   logs timeout event

---

## Phase 6 — Optimizer Agent (Off-Path)

**Goal:** Autonomous AI optimizer agent operational, submitting prompt-policy and strategy
recommendations for human review via the governance queue — never auto-promoting.

### Tasks

- [ ] **P6-01** Implement `apps/agents/optimizer/optimizer_agent.py` as a long-running
      background process that reads from Postgres `decision_traces` and `ablation_results`
- [ ] **P6-02** Implement pattern detection: correlate prompt-policy versions, analyst
      configurations, and strategy parameters with improved metrics (Sharpe, drawdown,
      hit rate) using statistical significance thresholds
- [ ] **P6-03** Implement candidate proposal generator: creates versioned prompt-policy
      candidates in `packages/prompt-policies/` with a `status: candidate` field
- [ ] **P6-04** Implement auto-submission to `prompt_policy_scorer.py` evaluation harness;
      score results written to `optimizer_runs` table
- [ ] **P6-05** Implement governance queue poster: writes approved recommendations to
      `governance_events` with `event_type: optimizer_recommendation`; triggers OpenClaw
      notification to human operator
- [ ] **P6-06** Add invariant test: verify optimizer agent has **zero ability** to call
      `POST /governance/prompt-policies/promote` directly; all promotions require human
      sign-off through HITL flow
- [ ] **P6-07** Build optimizer recommendations view in dashboard: pending recommendations,
      scoring evidence, one-click promote button (triggers HITL gate for human approval)

### Exit Gate

✅ Optimizer runs for 24h without crash, producing at least one recommendation in
   `optimizer_runs`
✅ P6-06 invariant test passes (optimizer cannot self-promote)
✅ Optimizer recommendation visible in dashboard with scoring evidence
✅ Operator can approve recommendation via dashboard → HITL gate → promotion flow end-to-end

---

## Phase 7 — Live Execution and Recovery Hardening

**Goal:** HyperLiquid live execution enabled under strict operator-controlled conditions, with
full recovery state machine, live treasury conversions, chaos testing passing, and incident
playbooks verified before any unattended live trading.

### Tasks

#### Live Executor
- [ ] **P7-01** Implement `HyperLiquidLiveExecutor` in `apps/executors/hyperliquid_live.py`:
      real order submission using `ExecutionDecision.staged_requests`
- [ ] **P7-02** Implement second-line live position limit enforcement at executor level
      (redundant with SAE; belt-and-suspenders)
- [ ] **P7-03** Implement live order status polling and partial fill handling with
      configurable polling interval
- [ ] **P7-04** Implement emergency close: `POST /control/emergency-close` triggers
      immediate FLAT of all open positions via reduce-only market orders on HL live

#### Live Treasury
- [ ] **P7-05** Enable real spot conversion in `TreasuryManager` for live mode: submits
      BTC/USDC spot orders via HL live executor
- [ ] **P7-06** Treasury conversions > threshold require HITL approval before order
      submission (per ruleset `treasury_large_conversion` rule)
- [ ] **P7-07** Write fill receipts from treasury conversions to `treasury_events` with
      `mode: live` and actual fill prices/amounts

#### Recovery State Machine
- [ ] **P7-08** Implement `recovery_state` table heartbeat: each service writes last known
      safe state every 30s
- [ ] **P7-09** Implement recovery coordinator: on restart after crash, reads
      `recovery_state` per service, reconciles against actual HL position (REST query),
      resolves any drift before resuming cycles
- [ ] **P7-10** Implement split-brain detection: if two Orchestrator instances are detected
      (via Postgres advisory lock), both halt immediately and alert via OpenClaw

#### Chaos and Hardening Tests
- [ ] **P7-11** `make chaos-agent-kill` — kill agents service mid-cycle; verify no orphaned
      `ExecutionRequest` reaches executor
- [ ] **P7-12** `make chaos-sae-kill` — kill SAE mid-cycle; verify executor receives no
      requests (SAE is required in pipeline)
- [ ] **P7-13** `make chaos-stale-data` — inject 120s stale market snapshot; verify SAE
      rejects on `stale_data` check and cycle emits `FLAT`
- [ ] **P7-14** `make chaos-position-drift` — manually modify HL paper position out-of-band;
      verify reconciler detects drift and alerts
- [ ] **P7-15** `make chaos-prompt-injection` — inject adversarial text into news feed;
      verify SAE hard gates are not bypassable by narrative content alone
- [ ] **P7-16** Write and verify all runbooks in `docs/runbooks/`:
      - `halt-and-resume.md`
      - `emergency-close.md`
      - `position-drift-recovery.md`
      - `prompt-policy-rollback.md`
      - `stale-data-incident.md`
      - `treasury-conversion-failure.md`

#### Production Readiness Gate
- [ ] **P7-17** Two-person sign-off: independent review of SAE policy YAML, HITL ruleset
      JSON, and live strategy config; both identities logged in `governance_events` with
      `event_type: production_signoff`
- [ ] **P7-18** 30-day continuous paper trading run with no unhandled crashes and no
      manual interventions required
- [ ] **P7-19** Full ablation results available in MLflow for current `strategy_live` version
      showing `full_system` outperforms `single_agent` on Sharpe with acceptable drawdown
- [ ] **P7-20** All chaos tests passing (P7-11 through P7-15)

### Exit Gate

✅ All P7-11 through P7-15 chaos tests pass
✅ 30-day paper run complete with no unhandled crashes (P7-18)
✅ P7-17 two-person sign-off complete and logged in `governance_events`
✅ Live executor correctly flat-closes all positions via
   `POST /control/emergency-close`
✅ Treasury live mode converts correctly and is blocked by HITL gate on amounts above
   threshold
✅ All runbooks written and reviewed

---

## Implementation Defaults

### Language Choices

| Service | Language | Rationale |
|---|---|---|
| `agents` | Python | TradingAgents framework is Python-native; ML/AI ecosystem |
| `jobs` | Python | Pandas/NumPy/MLflow ecosystem |
| `executors` | Python | HL Python SDK is most complete |
| `treasury` | Python | Shares portfolio state types with executors |
| `orchestrator-api` | TypeScript/Node | Strict API discipline, low-latency coordination |
| `sae-engine` | TypeScript/Node | Deterministic rules, zero LLM runtime dependency |
| `dashboard` | Next.js (TypeScript) | React ecosystem, fast iteration on governance UI |

### Non-Negotiable Engineering Rules

1. **No LLM output is executable trading authority on its own** — all agent outputs are
   typed artifacts consumed by downstream deterministic services
2. **All adaptation happens off the hot path** — prompt-policy changes, strategy upgrades,
   and evaluation results are promoted through explicit versioned gates requiring human
   approval
3. **SAE has zero LLM dependency** — it is a pure rule engine; any attempt to add LLM calls
   to `apps/sae-engine/` requires an architecture review and SPEC.md update before
   implementation
4. **DecisionTrace is immutable once written** — no in-place updates; corrections only via
   append-only `DecisionTraceAmendment` records with operator identity
5. **Live mode always requires HITL** — the ruleset rule `live_always_requires_human`
   may not be removed without a two-person governance sign-off logged in `governance_events`
6. **Chaos tests must pass before live** — no exceptions to P7-11 through P7-15
7. **Optimizer agent never self-promotes** — P6-06 invariant test must remain in CI
   permanently; failure blocks merge

---

## Milestone Summary

| Phase | Name | Exit Gate Summary | Est. Duration |
|---|---|---|---|
| 0 | Scaffolding | All services boot, contracts compile, DB migrates | 1 week |
| 1 | Analysts | ResearchPacket persisted with real data, 5 analyst types | 2 weeks |
| 2 | Debate + Trader | Full TradeIntent trace retrievable, strategy files migrated | 2 weeks |
| 3 | Risk + SAE | Architecture invariants pass, no LLM in SAE | 2 weeks |
| 4 | Paper + Eval + Treasury | 48h paper run, ablations in MLflow, treasury simulating | 3 weeks |
| 5 | Governance + HITL | HITL gates enforced, promotions logged, treasury HITL working | 2 weeks |
| 6 | Optimizer Agent | Recommendations flowing, cannot self-promote | 2 weeks |
| 7 | Live + Recovery | All chaos tests, 30d paper, two-person sign-off | 4+ weeks |

---

## Open Questions

- [ ] **Submodule vs vendor:** Will `TauricResearch/TradingAgents` be a git submodule (keeps
      upstream updates accessible) or fully vendored copy (simpler CI, no submodule
      sync issues)? Recommend submodule with a pinned commit SHA.
- [ ] **HL mainnet vs testnet:** Target HyperLiquid mainnet or testnet for initial paper
      trading in Phase 4? Testnet recommended until Phase 5 HITL is operational.
- [ ] **IntelliClaw feed:** Is the existing API key and field schema documented? Required
      before Phase 1 P1-02 can be completed.
- [ ] **Treasury threshold:** What USD-equivalent triggers BTC → USDC conversion? Required
      before Phase 4 P4-08. Recommended starting default: $500 min, $10,000 HITL threshold.
- [ ] **Two-person sign-off identities:** Identify both signatories for the P7-17
      production readiness gate before Phase 6 begins.
- [ ] **Optimizer statistical threshold:** What minimum statistical significance (p-value
      or effect size) is required before optimizer generates a recommendation? Define before
      Phase 6 P6-02.
- [ ] **Model routing keys:** Which model providers (OpenAI, Anthropic, local) and which
      specific model versions map to each routing tier in `config/model-routing/`? Define
      before Phase 1 P1-07 to ensure prompt policies are written for the correct backbone.
