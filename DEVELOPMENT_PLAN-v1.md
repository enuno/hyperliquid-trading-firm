# DEVELOPMENT_PLAN.md — HyperLiquid Autonomous Trading Firm

**Plan Version:** 1.0.0  
**Tracks:** SPEC.md v0.3.0  
**Updated:** 2026-03-26  
**Deployment target:** Kubernetes / ServerDomes edge cluster via ArgoCD GitOps  
**Status:** Active development

---

## Overview

This plan translates SPEC.md v0.3.0 into an ordered, dependency-respecting build sequence.
Work is organised into six phases that each produce a runnable, testable system boundary:

| Phase | Name | Outcome |
|---|---|---|
| 0 | Foundation & Scaffolding | Repo, CI, secrets, docker-compose, empty stubs compile and lint |
| 1 | Core Data & Intelligence Layer | IntelliClaw client live, IntelSnapshot flowing to analyst stubs |
| 2 | Agent Firm — Decision Pipeline | All 12 agents implemented; full cycle runs in paper mode |
| 3 | Strategy Iteration & Autoresearch | Paper bot + overnight loop + promotion gate operational |
| 4 | Live Execution & Vault | SAE engine, executors, vault, live bot, recovery state machine |
| 5 | Observability, MLflow & Governance | Dashboard complete, MultiClaw-MLFlow wired, data governance page |
| 6 | Control Plane & Production Hardening | OpenClaw integration, K8s GitOps, load/chaos testing, audits |

Each phase has a **Gate** — a minimum set of passing automated checks before the next phase begins.

---

## Phase 0 — Foundation & Scaffolding

**Goal:** Every service builds, lints, and starts without errors. No business logic yet.

### 0.1 Repository Hygiene

- [ ] Confirm branch protection on `main` (require PR + 1 review)
- [ ] Add `CODEOWNERS` for locked files (`agent/`, `strategy/strategy_base.py`,
      `apps/agents/src/strategies/base_strategy.py`, `apps/sae-engine/`)
- [ ] Set up `.env.example` with all required vars from SPEC §11.1
- [ ] Add pre-commit hooks: `ruff`, `mypy`, `eslint`, `prettier`
- [ ] Add `Makefile` targets: `dev`, `test`, `lint`, `build`, `migrate`

### 0.2 Service Stubs

- [ ] `apps/orchestrator-api` — Express/Fastify skeleton, health endpoint `/healthz`
- [ ] `apps/sae-engine` — TypeScript skeleton, health endpoint `/healthz`
- [ ] `apps/agents` — Python package, `main.py` with startup banner
- [ ] `apps/executors` — Python package skeleton
- [ ] `apps/dashboard` — Next.js `create-next-app` scaffold
- [ ] `apps/jobs` — Python package skeleton

### 0.3 Infrastructure

- [ ] `docker-compose.yml` — all services start and reach healthy state
- [ ] K8s base manifests in `infra/k8s/base/` for all pods (SPEC §11.2)
- [ ] ArgoCD ApplicationSet pointing at `main` branch (SPEC §11.3)
- [ ] `multiclaw/mlflow/infra/docker-compose.yml` — MLflow + Postgres + MinIO starts
      (`make mlflow-up`)
- [ ] K8s Secrets template for `HL_PRIVATE_KEY`, `VAULT_SUBACCOUNT_ADDRESS`,
      `INTELLICLAW_API_KEY`, `LLM_API_KEY`

### 0.4 Database Migrations

- [ ] SQLite schema for `logs/experiments.db` (SPEC §8, §4.2):
  - `experiments` table
  - `paper_outcomes` table
  - `rl_aggregates` table
- [ ] Postgres schema for dashboard performance store (SPEC §10.3):
  - `candles` table
  - `bot_performance` table

### Phase 0 Gate

```
✓ docker compose up --wait  → all services healthy
✓ make lint                 → zero errors
✓ make test                 → (empty suite passes)
✓ ArgoCD sync               → all deployments green
```

---

## Phase 1 — Core Data & Intelligence Layer

**Goal:** `IntelSnapshot` flows end-to-end from IntelliClaw through the client to analyst stubs.
All analysts can be instantiated and called; they log structured output even if not yet LLM-backed.

### 1.1 IntelliClaw Service Deployment

> **Prerequisite:** IntelliClaw repo cloned from `https://github.com/AIML-Solutions/IntelliClaw.git`
> and deployed as `intelliclaw` service in the cluster.

- [ ] Add `intelliclaw` entry to `docker-compose.yml` (image or build from source)
- [ ] Add `infra/k8s/base/intelliclaw-deploy.yaml` + `Service`
- [ ] Verify `GET http://intelliclaw:8080/intel/snapshot?asset=BTC` returns valid JSON
- [ ] Document expected response schema in `docs/intelliclaw-api-contract.md`

### 1.2 IntelSnapshot Schema (`apps/agents/src/types/intel.py`) ✅ DONE

All dataclasses implemented and committed:
- `IntelHeadline`, `IntelOnChain`, `IntelFundamental`, `IntelAlert`, `IntelSnapshot`
- `from_dict()` deserializers on each class
- `.has_critical_alerts`, `.high_importance_headlines`, `.to_analyst_context()` helpers
- Legacy plain-string alert backwards-compatibility path

Remaining:
- [ ] Unit tests: `tests/unit/test_intel_schema.py`
  - Valid full payload deserialises without error
  - Legacy plain-string alerts are promoted to `IntelAlert`
  - `to_analyst_context()` output matches expected format
  - `has_critical_alerts` returns correct bool

### 1.3 IntelliClaw Client (`apps/agents/src/tools/intelliclaw_client.py`) ✅ DONE

Full client implemented and committed:
- `get_intel_snapshot()` — cached (TTL), retried (3× exp. backoff)
- `search_events()` — historical event lookup
- `iter_alert_stream()` — polling alert generator
- `get_multi_snapshot()` — batch wrapper
- `IntelliClawError` exception class

Remaining:
- [ ] Unit tests: `tests/unit/test_intelliclaw_client.py`
  - Mock HTTP 200: returns valid `IntelSnapshot`
  - Mock HTTP 500 × 3: raises `IntelliClawError` after retries
  - Cache hit path: second call does not make HTTP request
  - `bypass_cache=True` path: always fetches
  - `get_multi_snapshot`: partial failure skips failed asset and logs warning
- [ ] Integration test: `tests/integration/test_intelliclaw_live.py`
  - Marked `@pytest.mark.integration` — requires live IntelliClaw service
  - Assert `IntelSnapshot.asset == "BTC"` and `confidence` in `[0.0, 1.0]`

### 1.4 Analyst Agent Stubs — IntelliClaw Wiring

All analysts in `apps/agents/src/agents/` must follow SPEC §2.3:

```python
from ..tools.intelliclaw_client import get_intel_snapshot

class <Role>AnalystAgent:
    def generate_report(self, asset: str) -> <Role>AnalystReport:
        intel = get_intel_snapshot(asset)
        ...
```

- [ ] `sentiment_analyst.py` — reference implementation (IntelliClaw sentiment + headlines)
- [ ] `news_analyst.py` — consumes `intel.headlines` + `intel.key_points`
- [ ] `onchain_analyst.py` — consumes `intel.onchain`; enriches with Glassnode/Dune if available
- [ ] `fundamental_analyst.py` — consumes `intel.fundamental`; fetches macro data
- [ ] `market_analyst.py` — primary from HL candles; uses `intel.alerts` for context

All stubs must:
- Return a typed `*AnalystReport` dataclass (define in `apps/agents/src/types/reports.py`)
- Log the `to_analyst_context()` string at DEBUG level
- Surface `IntelliClawError` upstream without swallowing

### 1.5 Market Data Ingestor

- [ ] `apps/jobs/src/market_ingestor.py` — polls HL `candleSnapshot` API, writes to
      `candles` table (SPEC §10.3)
- [ ] WebSocket `candle` stream subscription for live incremental updates
- [ ] Backfill job: loads 365-day rolling window of 1-minute candles on first start

### Phase 1 Gate

```
✓ make test tests/unit/test_intel_schema.py        → all pass
✓ make test tests/unit/test_intelliclaw_client.py  → all pass
✓ python -m apps.agents.src.agents.sentiment_analyst BTC
    → prints non-empty AnalystReport JSON without error
✓ Market ingestor writes at least 1 candle row to DB
```

---

## Phase 2 — Agent Firm Decision Pipeline

**Goal:** A complete `POST /cycles/trigger` request executes all 7 stages
(Analysts → Debate → Trader → Risk → Fund Manager → SAE → Executor stub)
and returns a structured decision trace in paper mode.

### 2.1 Report & Decision Type System (`apps/agents/src/types/reports.py`)

Define all typed dataclasses:

- [ ] `MarketAnalystReport` — OHLCV summary, vol regime, trend label
- [ ] `NewsAnalystReport` — top headlines, narrative summary from IntelliClaw
- [ ] `FundamentalAnalystReport` — macro regime, Fear/Greed, dominance
- [ ] `OnChainAnalystReport` — net flows, whale activity, reserve changes
- [ ] `SentimentAnalystReport` — overall_sentiment, score, confidence
- [ ] `ResearchSummary` — bull/bear case, facilitator synthesis
- [ ] `TradeDecision` — asset, direction (`long`/`short`/`flat`), size_pct, entry_type
- [ ] `RiskVote` — profile (`aggressive`/`neutral`/`conservative`), approve/veto, rationale
- [ ] `TradeOrder` — validated order with fund manager constraints applied
- [ ] `ExecutionPlan` — SAE staged plan with algo hints (TWAP/VWAP/POV/Iceberg)
- [ ] `DecisionTrace` — full audit record of one decision cycle (all above + timestamps)

### 2.2 Analyst Agents — LLM Implementation

- [ ] Implement LLM call pattern in each analyst using `apps/agents/src/atlas/` prompts:
  - System prompt from `prompts/` templates
  - User prompt built from `intel.to_analyst_context()` + market data
  - Response parsed into typed `*AnalystReport`
- [ ] `apps/agents/src/config/model_routing.yaml` — define which LLM model/provider
      handles each agent role
- [ ] LLM retry and fallback logic (structured output validation, max 2 retries)

### 2.3 Research Debate (`apps/agents/src/agents/debate/`)

- [ ] `bullish_researcher.py` — argues long case from analyst reports
- [ ] `bearish_researcher.py` — argues short/flat case from analyst reports
- [ ] `facilitator.py` — synthesises both into `ResearchSummary`

### 2.4 Trader Agent (`apps/agents/src/agents/trader.py`)

- [ ] Consumes `ResearchSummary` + all `*AnalystReport`s
- [ ] Selects a `BaseStrategy` plugin from `apps/agents/src/strategies/`
- [ ] Produces a `TradeDecision`

### 2.5 Risk Council (`apps/agents/src/agents/risk_council.py`)

- [ ] Three independent `RiskVote` calls (aggressive / neutral / conservative profiles)
- [ ] Majority rule: 2/3 approve → proceed; unanimous veto → halt
- [ ] Config flag: `require_unanimous_approve` for conservative deployments

### 2.6 Fund Manager (`apps/agents/src/agents/fund_manager.py`)

- [ ] Applies portfolio-level constraints:
  - Concentration cap (max % in single asset)
  - Daily loss limit guard (SPEC §6.1)
  - Correlation check (multi-asset future)
- [ ] Produces `TradeOrder` from approved `TradeDecision`

### 2.7 SAE Engine — Core Policy Validation (`apps/sae-engine/`)

> SAE is non-bypassable. All trade paths must route through it (SPEC §7).

- [ ] `POST /sae/validate` — validate `TradeOrder` against current policies
- [ ] `PUT /sae/policies` — update per-asset SAE policy (SPEC §15)
- [ ] Policy schema in `config/strategies/` YAML:
  - `max_leverage`, `max_size_usd`, `max_drawdown_pct`, `allowed_algos`
- [ ] Staged execution plan builder:
  - TWAP, VWAP, POV, Iceberg logic stubs (full implementation Phase 4)
- [ ] Regime detection: reads current `RecoveryState` to tighten caps in recovery
- [ ] SAE unit tests: `tests/unit/test_sae_engine.ts`

### 2.8 Strategy Plugins

- [ ] `apps/agents/src/strategies/grid_bot.py` — extend `BaseStrategy`
- [ ] `apps/agents/src/strategies/dca_bot.py` — extend `BaseStrategy`
- [ ] `apps/agents/src/strategies/rsi_reversion.py` — extend `BaseStrategy`
- [ ] `apps/agents/src/strategies/hyperliquid_perps_meta.py` — extend `BaseStrategy`
- [ ] Strategy plugin registry: load by name from `model_routing.yaml`

### 2.9 Executor Stub (Paper Mode)

- [ ] `apps/executors/src/paper_executor.py` — simulates fill at mid ± half-spread
- [ ] Writes `PaperTradeOutcome` row to `paper_outcomes` table
- [ ] No real orders; `TRADE_MODE=paper` guard

### 2.10 Orchestrator Decision Cycle

- [ ] `POST /cycles/trigger` — runs full 7-stage pipeline, returns `DecisionTrace`
- [ ] `GET /traces/:id` — retrieve stored `DecisionTrace` (SPEC §15)
- [ ] `GET /metrics` — live performance summary (SPEC §15)
- [ ] Decision traces persisted to Postgres

### Phase 2 Gate

```
✓ POST /cycles/trigger {"asset":"BTC","mode":"paper"}
    → HTTP 200, DecisionTrace JSON with all 7 stages populated
    → paper_outcomes row written to DB
✓ make test tests/unit/  → all pass
✓ No executor call bypasses SAE (enforced by architecture test)
```

---

## Phase 3 — Strategy Iteration & Autoresearch

**Goal:** Overnight loop runs 100 iterations, scores strategies, commits accepted
candidates via git, ArgoCD picks up the diff, paper bot self-improves.

### 3.1 Evaluation Harness (`agent/harness.py`) (SPEC §8)

- [ ] `score()` function: Sharpe (annualised, 15-minute bars), max_drawdown,
      win_rate, profit_factor, n_trades
- [ ] Backtest runner: replays `candles` data against a `strategy_paper.py` instance
- [ ] 5-minute timeout enforced via `asyncio.wait_for`
- [ ] `should_keep()` logic (SPEC §4.5):
  - Hard reject: `max_drawdown > 0.08` or `n_trades < 10`
  - Accept: new Sharpe > best Sharpe AND new drawdown ≤ best × 1.1
- [ ] Unit tests: `tests/unit/test_harness.py` — deterministic fixture data

### 3.2 RL Buffer (`agent/rl_buffer.py`)

- [ ] Async write: `PaperTradeOutcome` → `paper_outcomes` SQLite table
- [ ] Rolling aggregate query: `get_aggregates(hours=48)` → `RLAggregate`
- [ ] `meets_promotion_criteria()` check: Sharpe ≥ 1.5, win_rate ≥ 0.45,
      n_trades ≥ 30, not in recovery
- [ ] Unit tests: `tests/unit/test_rl_buffer.py`

### 3.3 Paper Bot (`agent/paper_bot.py`) (SPEC §4.1)

- [ ] WebSocket subscription to HL live trades feed
- [ ] Candle buffer accumulation (15-minute bars)
- [ ] Signal generation via active `strategy_paper.py`
- [ ] Simulated fill at mid ± half-spread
- [ ] `PaperTradeOutcome` written to RL buffer on each close
- [ ] `_check_promotion_criteria()` async check after each close
- [ ] Paper bot never paused; runs 24/7

### 3.4 Agent Proposal Context (`agent/iteration_loop.py`) (SPEC §4.3)

- [ ] `build_proposal_context()` — assembles:
  - `trading_program.md` goals
  - Last 20 experiment records
  - Last 48-hour RL aggregates
  - Last 50 paper trade outcomes
  - Current live config (paper only at this stage)
  - Market snapshot (funding rate, vol regime from `get_intel_snapshot`)
  - `RecoveryState`
- [ ] Agent `propose_strategy()` — sends context to LLM; constrains to max 3
      `StrategyConfig` parameter changes; requires justification referencing
      paper trade outcomes (SPEC §4.4)

### 3.5 Strategy Validation (`agent/iteration_loop.py`)

- [ ] `validate_strategy_module(code: str) -> bool`:
  - AST parse: no `import` of executor, SAE, or exchange modules
  - No modification to `VAULT_SUBACCOUNT_ADDRESS`
  - Only `StrategyConfig` dataclass fields changed (max 3)
  - `strategy_paper.py` only; never writes `strategy_live.py`
- [ ] Security: `exec()` only in sandboxed subprocess (no network)

### 3.6 Overnight Loop (`agent/iteration_loop.py`) (SPEC §4.4)

- [ ] Scheduled: cron at 02:00 UTC (configurable)
- [ ] `max_iterations=100` (normal), `200` (recovery)
- [ ] Each iteration:
  1. Build proposal context
  2. LLM proposes strategy
  3. Validate module
  4. Run backtest (5 min timeout)
  5. `should_keep()` check
  6. Accept: write to `experiments`, `git commit`, `git push`
  7. Reject: log reason, continue
- [ ] `git_commit_strategy()`: commits `strategy/strategy_paper.py` with tag
      `paper/v{N}` and rationale message
- [ ] ArgoCD picks up push → rolling restart of paper-eval pod (SPEC §11.3)

### 3.7 MLflow Experiment Logging (SPEC §9)

- [ ] All backtest runs log to `multiclaw/mlflow` via `MLFLOW_TRACKING_URI`
- [ ] Required fields: model family, dataset id, all `StrategyConfig` params,
      Sharpe/max_dd/win_rate/profit_factor, artifact URI, operator role
- [ ] `mlflow.log_artifact("strategy/strategy_paper.py")` on each accepted run
- [ ] Integration test: `tests/integration/test_mlflow_logging.py`

### Phase 3 Gate

```
✓ overnight_loop(max_iterations=5) completes without crash
✓ At least 1 experiment committed to git with tag paper/v{N}
✓ ArgoCD detects commit → paper pod restarts with new strategy
✓ make test tests/unit/test_harness.py  → all pass
✓ make test tests/unit/test_rl_buffer.py → all pass
✓ MLflow UI shows ≥ 1 run in experiment "backtest_*"
```

---

## Phase 4 — Live Execution & Vault

**Goal:** System can execute real orders on HyperLiquid perps under SAE guard,
deduct vault on profitable trades, and enter/exit recovery mode correctly.

> **Risk gate:** Phase 4 work is done exclusively in `TRADE_MODE=paper` until
> all Phase 4 gate checks pass. Live mode requires a manual K8s Secret patch
> (`TRADE_MODE=live`, `TRADE_MODE_CONFIRM=yes`).

### 4.1 HyperLiquid Executor (`apps/executors/src/hl_executor.py`)

- [ ] `hyperliquid-python-sdk` integration (SPEC §1.3)
- [ ] Order placement: `exchange.order()` for market and limit orders
- [ ] Order cancellation: `exchange.cancel()`, `exchange.cancel_all()`
- [ ] Position close: `exchange.market_close()`
- [ ] User state poll: `info.user_state()` at 1 Hz for reconciliation
- [ ] Rate limiter: token bucket, 3 req/s avg, burst 5 (SPEC §6.4)
- [ ] `TRADE_MODE` guard: raises `TradingModeError` if not `live` + `TRADE_MODE_CONFIRM`

### 4.2 SAE Engine — Execution Algorithms (SPEC §7)

- [ ] TWAP executor: splits order into N equal slices over T minutes
- [ ] VWAP executor: sizes slices proportional to historical volume profile
- [ ] POV executor: participates at X% of real-time market volume
- [ ] Iceberg executor: shows only Y% of order size at a time
- [ ] Algo selection: SAE policy YAML per asset specifies allowed algos

### 4.3 Live Bot (`agent/live_bot.py`) (SPEC §5)

- [ ] `LiveSession` dataclass (SPEC §5.1): tracks equity, peak, vault balance,
      halt reason
- [ ] `close_position_and_vault()` (SPEC §5.2):
  - Compute raw PnL and net PnL after fees
  - Deduct `vault_take_pct` (clamped 10–20%) from profitable trades only
  - Transfer vault amount to `VAULT_SUBACCOUNT_ADDRESS`
  - Update `LiveSession` state
- [ ] Vault rules enforced (SPEC §5.3):
  - Vault address read-only (K8s Secret)
  - No withdrawal automation
  - No vault re-deployment

### 4.4 Safety Layer (`agent/safety.py`) (SPEC §6)

- [ ] `SafetyGuard.check()` — raises `TradingHalt` on any limit breach
- [ ] `SafetyGuard.validate_order()` — raises `OrderRejected` if `size_usd >
      HARD_MAX_POSITION_USD`
- [ ] Configurable limits via env vars: `HARD_MAX_POSITION_USD`,
      `DAILY_LOSS_LIMIT_PCT`, `MAX_DRAWDOWN_PCT`
- [ ] Unit tests: `tests/unit/test_safety.py` — verify each kill switch fires

### 4.5 Recovery State Machine (`agent/recovery.py`) (SPEC §6.2, §6.3)

- [ ] `check_recovery_threshold(session)` — triggers if `equity ≤ 50% session start`
  - Cancels all open orders
  - Closes all positions
  - Sets `RecoveryState.active = True`
  - Sends halt alert
- [ ] Recovery mode effects:
  - Live bot: halted
  - Overnight loop: `max_iterations = 200`
  - Paper bot: continues 24/7
  - Promotion thresholds raised (Sharpe 2.0, win_rate 0.50, 72 h, 50 trades)
- [ ] Recovery exit:
  - All raised promotion criteria met
  - `session_start_equity` resets to current equity
  - `RecoveryState.active = False`
- [ ] Alert integration: Slack/Telegram/email on enter and exit (SPEC §10.4)
- [ ] Unit tests: `tests/unit/test_recovery.py`

### 4.6 Promotion Logic

- [ ] `promote_to_live(strategy)` in `paper_bot.py`:
  - Reads current `RecoveryState`
  - Checks all promotion criteria from RL buffer
  - Writes `strategy/strategy_live.py` (only this path may write that file)
  - Commits with tag `live/v{N}`
  - Sends promotion alert
- [ ] `strategy_live.py` guard: AST check in CI confirms only promotion logic
      modifies this file

### 4.7 Markets — BTC-PERP Primary

- [ ] Live executor configured for `BTC-PERP` only (Phase 4)
- [ ] `ETH-PERP` gated by `n_successful_btc_iterations >= 50` (SPEC §14)
- [ ] Funding rate check: skip entry if adverse funding > 0.05%/8 h (SPEC §13)

### Phase 4 Gate

```
✓ make test tests/unit/test_safety.py   → all kill switches fire correctly
✓ make test tests/unit/test_recovery.py → state transitions correct
✓ Paper mode live_bot runs 1 h with no errors; vault deductions logged
✓ Manually trigger recovery: live halts, paper continues, loop uses 200 iters
✓ Recovery exit: session_start_equity resets, RecoveryState.active = False
✓ HARD: TRADE_MODE=live requires manual K8s Secret patch confirmed by 2nd person
```

---

## Phase 5 — Observability, MLflow & Governance

**Goal:** Dashboard is fully operational. All experiments tracked in MLflow.
Governance page shows data source policies and Hypersignal approval state.

### 5.1 Dashboard — Core Pages (SPEC §10.2)

- [ ] **Market Research** (`/research`)
  - 365-day 1-minute candle chart (TradingView Lightweight Charts or Recharts)
  - Strategy entry/exit markers from `paper_outcomes`
  - Regime annotations from `intel.fundamental.regime`
- [ ] **Paper Trading Performance** (`/paper`)
  - Cumulative P/L, rolling Sharpe, max DD, win rate
  - Fees, funding, vault transfers chart
- [ ] **Live Trading Performance** (`/live`)
  - Same as paper + live equity curve vs. session start equity
  - Vault balance tracker
- [ ] **Strategy Experiments** (`/experiments`)
  - List: run_id, timestamp, Sharpe, max_dd, kept/rejected, rationale
  - MLflow run link per experiment
- [ ] **Risk & Halt Status** (`/status`)
  - Current mode badge: `BACKTEST | PAPER | LIVE | RECOVERY`
  - Kill switch state indicators
  - Recovery threshold gauge (current equity vs. 50% floor)

### 5.2 Dashboard API (`apps/dashboard/` FastAPI backend)

- [ ] `GET /api/candles?asset=BTC&interval=1m&from=&to=`
- [ ] `GET /api/performance?bot=paper|live`
- [ ] `GET /api/experiments?limit=50`
- [ ] `GET /api/status` — current mode, kill switch states, recovery flags
- [ ] `GET /api/vault` — vault balance, transfer history
- [ ] `GET /api/governance/hypersignal` — config IDs, latest MLflow metrics,
      SAE approval state per config
- [ ] `GET /api/governance/experiments` — MLflow experiment/run summaries
- [ ] `POST /api/governance/hypersignal/approve` — approve a config for live use

### 5.3 12-Hour Status Reporter (SPEC §10.4)

- [ ] Scheduled: every 12 hours
- [ ] Content: paper P/L, live P/L, account balance, vault balance,
      current drawdown, current state
- [ ] Delivery: Slack webhook (primary), Telegram bot (fallback), email (tertiary)
- [ ] Reporter failures logged + ops alert; trading never halted by reporter failure
- [ ] No secrets, keys, or wallet material in notification payloads

### 5.4 Hypersignal Accuracy Tracking (SPEC §9 + MultiClaw-MLFlow)

- [ ] `apps/jobs/src/hypersignal_eval.py`:
  - MLflow experiment: `hypersignal_accuracy`
  - Params: provider, config_id, dataset, window_hours
  - Metrics: accuracy, AUC, correlation, PnL uplift
  - `mlflow.log_artifact()` for evaluation dataset
- [ ] `evaluate_hypersignal_config` OpenClawTool wrapper
- [ ] `data_source_policies` Postgres table:
  - `id`, `name`, `type`, `status` (`experimental|approved|disabled`),
    `sae_regimes_enabled` (JSON), `last_evaluated_run_id`
- [ ] SAE engine reads `data_source_policies` at startup and on `PUT /sae/policies`

### 5.5 Governance Dashboard Page (`/governance`)

- [ ] `HypersignalGovernanceTable` component: config list, metrics, approval CTA
- [ ] `ExperimentList` component: MLflow runs with key metrics
- [ ] `PolicyDiffViewer` component: SAE policy change history
- [ ] Approval action: `POST /api/governance/hypersignal/approve` → updates
      `data_source_policies` + SAE policy reload

### 5.6 Dashboard Auth (SPEC §10.5)

- [ ] Deploy behind SSO or reverse-proxy auth (e.g., Authelia, Cloudflare Access)
- [ ] Confirm no API route exposes `HL_PRIVATE_KEY`, `VAULT_SUBACCOUNT_ADDRESS`,
      or `INTELLICLAW_API_KEY` in any response

### Phase 5 Gate

```
✓ All 6 dashboard pages render with real data (no mock)
✓ 12-hour status message delivered to Slack with correct P/L values
✓ hypersignal_eval.py run → MLflow experiment visible at :5000
✓ Governance page shows IntelliClaw config approval state
✓ Dashboard auth blocks unauthenticated access
```

---

## Phase 6 — Control Plane & Production Hardening

**Goal:** OpenClaw integration operational. System passes load testing, chaos
testing, and security review. Ready for continuous live operation.

### 6.1 OpenClaw Integration (SPEC §15)

- [ ] `POST /cycles/trigger` — validates OpenClaw caller token
- [ ] `PUT /sae/policies` — auth-gated; only OpenClaw controller and manual ops
- [ ] `PUT /config/strategy` — updates paper strategy config (not `strategy_paper.py`
      directly; must go through proposal + validation)
- [ ] `GET /traces/:id` — returns full `DecisionTrace` JSON
- [ ] `GET /metrics` — live performance summary
- [ ] MultiClaw OpenClawTools registration:
  - `run_trading_cycle` → `POST /cycles/trigger`
  - `backtest_strategy` → `apps/jobs/src/backtest_runner.py`
  - `evaluate_hypersignal_config` → `apps/jobs/src/hypersignal_eval.py`
  - `update_sae_policy` → `PUT /sae/policies`
  - `intel_get_snapshot` → `apps/agents/src/tools/intelliclaw_client.get_intel_snapshot`
  - `intel_search_events` → `apps/agents/src/tools/intelliclaw_client.search_events`

### 6.2 Multi-Worker Redis Cache

- [ ] Replace in-process `_snapshot_cache` dict in `intelliclaw_client.py`
      with Redis-backed TTL cache for multi-pod deployments (SPEC §2.1 note)
- [ ] Add Redis to `docker-compose.yml` and K8s manifests
- [ ] `INTELLICLAW_CACHE_BACKEND=redis` env var toggle (default: in-process)

### 6.3 Load & Chaos Testing

- [ ] Load test: `POST /cycles/trigger` at 10 req/min for 30 min — no errors,
      p99 latency < 30 s
- [ ] Chaos: kill `intelliclaw` pod mid-cycle — `IntelliClawError` surfaces
      correctly; trading cycle fails gracefully without placing orders
- [ ] Chaos: kill `sae-engine` pod — executor receives no orders; alert fires
- [ ] Chaos: kill `orchestrator-api` pod — ArgoCD restores in < 60 s
- [ ] Network partition: WS disconnect from HL feed — reconnect within 5 s;
      paper bot resumes without missed fills

### 6.4 Security Review

- [ ] Secret scanning: `git log` for any accidental key commits
- [ ] Confirm `VAULT_SUBACCOUNT_ADDRESS` has zero code write paths (grep audit)
- [ ] Confirm `strategy_live.py` has only one write path (promotion logic)
- [ ] Confirm no executor can be called without passing SAE validation
- [ ] Confirm dashboard API has no key-leaking routes
- [ ] Dependency audit: `pip audit`, `npm audit` — no critical CVEs
- [ ] Review Hypersignal / IntelliClaw prompt injection surface
      (per Hypersignal Accuracy Limitations research findings):
  - All IntelliClaw text injected into LLM prompts is passed through
    `to_analyst_context()` only — no raw external text in system prompts
  - `intel.alerts[].message` strings are HTML-escaped before prompt injection
  - SAE `has_critical_alerts` gate checked before any LLM-driven position increase

### 6.5 Operational Runbooks

- [ ] `docs/runbooks/live-enable.md` — step-by-step K8s Secret patch for live mode
- [ ] `docs/runbooks/recovery-manual-exit.md` — how to manually clear recovery state
- [ ] `docs/runbooks/vault-withdrawal.md` — manual vault withdrawal checklist
- [ ] `docs/runbooks/intelliclaw-outage.md` — degraded operation without IntelliClaw;
      analysts fall back to market-data-only mode
- [ ] `docs/runbooks/rollback-strategy.md` — git revert + ArgoCD force-sync

### 6.6 ETH-PERP Unlock

- [ ] Gate check: `n_successful_btc_iterations >= 50` in SQLite (SPEC §14)
- [ ] `get_multi_snapshot(["BTC", "ETH"])` used by analysts when ETH unlocked
- [ ] SAE policy YAML added for `ETH-PERP`
- [ ] Market ingestor extended to backfill ETH 1-minute candles

### Phase 6 Gate

```
✓ OpenClaw `run_trading_cycle` tool calls return valid DecisionTrace
✓ Load test: p99 < 30 s, zero 5xx errors over 30 min
✓ Chaos tests: all failure modes fail safely (no unguarded orders)
✓ Security: zero secrets in git history, zero key-leaking routes
✓ All runbooks reviewed by second engineer
✓ LIVE MODE: first trade executes; vault deduction confirmed on-chain
```

---

## Cross-Cutting Concerns

### Testing Strategy

| Layer | Tool | Location |
|---|---|---|
| Python unit tests | `pytest` | `tests/unit/` |
| TypeScript unit tests | `vitest` | `apps/*/src/__tests__/` |
| Integration tests | `pytest` (marked) | `tests/integration/` |
| E2E dashboard tests | `playwright` | `tests/e2e/` |
| Load testing | `k6` | `tests/load/` |
| Chaos testing | manual + `chaos-mesh` | `tests/chaos/` |

All unit tests must pass before any PR merges to `main`.
Integration tests run in CI with service containers (IntelliClaw mock).

### Locked Files (Never Agent-Editable)

The following files must not be modified by LLM agents under any circumstance.
CODEOWNERS enforces human review for all changes:

```
agent/main.py
agent/exchange.py
agent/safety.py
agent/harness.py
agent/iteration_loop.py
agent/paper_bot.py
agent/live_bot.py
agent/rl_buffer.py
agent/recovery.py
strategy/strategy_base.py
apps/agents/src/strategies/base_strategy.py
apps/sae-engine/
```

### Environment Progression

```
local dev → docker compose up
    ↓
CI/CD     → GitHub Actions (lint, test, build)
    ↓
paper K8s → ArgoCD paper environment (TRADE_MODE=paper)
    ↓
live K8s  → ArgoCD live environment (manual Secret patch required)
```

### Dependency Versions (pin in `requirements.txt` and `package.json`)

| Dependency | Version | Notes |
|---|---|---|
| `hyperliquid-python-sdk` | latest stable | Pin exact version |
| `requests` | ≥ 2.31 | For IntelliClaw client |
| `urllib3` | ≥ 2.0 | For `Retry` backoff |
| `mlflow` | ≥ 2.10 | For experiment tracking |
| `numpy` | ≥ 1.26 | For harness scoring |
| `pytest` | ≥ 8.0 | Test runner |
| `ruff` | ≥ 0.4 | Linter/formatter |
| `mypy` | ≥ 1.8 | Type checker |
| TypeScript | 5.x | Orchestrator + SAE |
| Next.js | 14.x | Dashboard |

---

## Progress Tracker

| Phase | Status | Completed | Outstanding |
|---|---|---|---|
| 0 — Foundation | 🟡 In Progress | Repo structure, service stubs, SPEC.md | CI/CD, full docker-compose, K8s manifests |
| 1 — Intelligence Layer | 🟡 In Progress | `intel.py` schema ✅, `intelliclaw_client.py` ✅ | Unit tests, analyst wiring, market ingestor |
| 2 — Agent Pipeline | 🔴 Not Started | — | All agent implementations, SAE core, orchestrator cycle |
| 3 — Autoresearch | 🔴 Not Started | — | Harness, RL buffer, paper bot, overnight loop, MLflow |
| 4 — Live Execution | 🔴 Not Started | — | HL executor, vault, recovery state machine, promotion |
| 5 — Observability | 🔴 Not Started | — | Dashboard pages, governance, status reporter |
| 6 — Production | 🔴 Not Started | — | OpenClaw tools, load/chaos tests, security review, runbooks |

---

## Open Questions / Decisions Needed

| # | Question | Owner | Priority |
|---|---|---|---|
| 1 | IntelliClaw deployment: run from source or pull image? What is the startup config? | Engineering | High |
| 2 | LLM provider selection for agents: OpenAI GPT-4o, Anthropic Claude, or local? | Engineering | High |
| 3 | Redis: deploy in cluster now (Phase 1) or defer to Phase 6? | Engineering | Medium |
| 4 | Dashboard auth: Cloudflare Access, Authelia, or Nginx basic-auth for dev? | Engineering | Medium |
| 5 | Status reporter: Slack webhook vs. Telegram bot — which is set up first? | Ops | Low |
| 6 | ETH-PERP timing: is 50 BTC iterations the right gate or should it be time-based? | Engineering | Low |
| 7 | MultiClaw-Core deployment: same cluster or separate? How are OpenClawTools auth tokens provisioned? | Engineering | Medium |
