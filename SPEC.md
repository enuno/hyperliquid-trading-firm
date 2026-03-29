# hyperliquid-trading-firm — System Specification

> **Version:** 2.0.0-draft
> **Last updated:** 2026-03-29
> **Status:** Active development — paper trading target
> **Repo:** https://github.com/enuno/hyperliquid-trading-firm

---

## 1. Purpose and Scope

`hyperliquid-trading-firm` is an **auditable, modular, multi-agent trading system** targeting
HyperLiquid perpetuals. It is modeled after the organizational structure of a real trading firm,
implementing the architecture described in the
[TradingAgents paper (arXiv 2412.20138)](https://arxiv.org/pdf/2412.20138) and the
[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) open-source
framework, extended with:

- A **Safety Approval Engine (SAE)** for deterministic, non-bypassable pre-execution policy
  enforcement
- An **OpenClaw control plane** adapter for operator governance, HITL, and strategy lifecycle
  management
- A **Clawvisor HITL ruleset** system for operator-defined approval requirements
- A **treasury management** module for automated BTC-to-stablecoin conversion and risk exposure
  control
- Full **DecisionTrace** persistence so every trade decision is replayable and attributable

This system treats **live execution as safety-critical**. No LLM output is ever executable trading
authority on its own. All adaptation happens off the hot path through versioned artifacts and
explicit promotion gates.

---

## 2. Design Principles

| Principle | Implementation |
|---|---|
| Role specialization over monolithic agents | Separate analyst, debate, trader, risk, fund-manager agents per TradingAgents |
| Structured state over prompt chaining | Typed JSON/protobuf artifacts at every handoff |
| Adversarial challenge before commitment | Bull/bear debate rounds before TradeIntent |
| Hard safety gates | SAE enforces policy; cannot be bypassed by any agent or operator API call |
| Full auditability | Every artifact keyed on `cycle_id`; DecisionTrace persisted immutably |
| Adaptation off the hot path | Prompt-policy changes, strategy upgrades require explicit versioned promotion |
| No-trade is a first-class outcome | HOLD/FLAT emitted when consensus is weak or risk objects unresolved |
| Live execution requires human approval | Clawvisor HITL ruleset gates all live-mode cycles |

---

## 3. Repository Structure

```text
hyperliquid-trading-firm/
├─ README.md
├─ SPEC.md                          ← this file
├─ DEVELOPMENT_PLAN.md
├─ LICENSE
├─ Makefile
├─ docker-compose.yml
├─ docker-compose.paper.yml
├─ docker-compose.live.yml
├─ .env.example
│
├─ proto/
│  ├─ common.proto                  # Meta, Direction, TradeMode, shared enums
│  ├─ decisioning.proto             # ResearchPacket, DebateOutcome, TradeIntent
│  ├─ risk.proto                    # RiskVote, RiskReview, ExecutionApprovalRequest, ExecutionApproval
│  ├─ execution.proto               # ExecutionRequest, ExecutionDecision, FillReport
│  └─ controlplane.proto            # OpenClaw API types, HITLRuleSet, GovernanceEvent
│
├─ apps/
│  ├─ orchestrator-api/             # TypeScript/Node — cycle coordinator, public API, event bus
│  ├─ agents/                       # Python — TradingAgents-based analyst/debate/trader/risk/fund-mgr
│  │  ├─ tradingagents/             # git submodule or vendored copy of TauricResearch/TradingAgents
│  │  ├─ adapters/                  # HL-specific adapters wrapping TradingAgents interfaces
│  │  ├─ analysts/
│  │  │  ├─ fundamental.py
│  │  │  ├─ sentiment.py
│  │  │  ├─ news.py
│  │  │  ├─ technical.py
│  │  │  └─ onchain.py
│  │  ├─ researchers/
│  │  │  ├─ bull.py
│  │  │  └─ bear.py
│  │  ├─ debate/
│  │  │  └─ facilitator.py
│  │  ├─ trader/
│  │  │  └─ trader_agent.py
│  │  ├─ risk/
│  │  │  ├─ aggressive.py
│  │  │  ├─ neutral.py
│  │  │  └─ conservative.py
│  │  └─ fund_manager/
│  │     └─ fund_manager_agent.py
│  ├─ sae-engine/                   # TypeScript/Node — policy engine, hard gates, staged requests
│  ├─ executors/                    # Python — HyperLiquid paper + live venue adapters
│  │  ├─ hyperliquid_paper.py
│  │  ├─ hyperliquid_live.py
│  │  └─ fill_reconciler.py
│  ├─ jobs/                         # Python — backtests, ablations, prompt scoring, eval harness
│  │  ├─ backtest_runner.py
│  │  ├─ ablation_runner.py
│  │  └─ prompt_policy_scorer.py
│  └─ dashboard/                    # Next.js — decision traces, governance, experiments UI
│
├─ packages/
│  ├─ schemas/                      # Generated JSON schemas + TS/Python shared models (from proto)
│  ├─ prompt-policies/              # Versioned prompt templates with metadata
│  │  ├─ analyst/
│  │  ├─ trader/
│  │  ├─ risk-aggressive/
│  │  ├─ risk-neutral/
│  │  ├─ risk-conservative/
│  │  └─ fund-manager/
│  └─ strategy-sdk/                 # Plugin API for strategy modules
│
├─ config/
│  ├─ env/                          # Per-environment .env overlays
│  ├─ policies/                     # SAE policy YAML files
│  ├─ strategies/                   # Strategy configuration JSON
│  ├─ hitl-rulesets/                # Clawvisor HITL JSON rulesets
│  └─ model-routing/                # LLM model routing tables
│
├─ strategy/
│  ├─ strategy_paper.py             # Paper trading strategy plugin
│  ├─ strategy_live.py              # Live trading strategy plugin
│  └─ trading_program.md            # Human-readable strategy intent document
│
├─ infra/
│  ├─ k8s/                          # Kubernetes manifests
│  ├─ argocd/                       # GitOps application definitions
│  ├─ terraform/                    # Cloud infrastructure
│  └─ observability/                # Prometheus, Grafana, Loki configs
│
├─ docs/
│  ├─ architecture.md
│  ├─ api-contracts.md
│  ├─ protobuf.md
│  ├─ tradingagents-integration.md  # How TauricResearch/TradingAgents is adopted
│  └─ runbooks/
│
└─ tests/
   ├─ contract/                     # Proto/schema contract tests
   ├─ integration/                  # Service-to-service integration tests
   ├─ simulation/                   # Paper trade simulation tests
   └─ chaos/                        # Fault injection and recovery tests
```


---

## 4. TradingAgents Framework Integration

### 4.1 Adoption Strategy

The [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) framework is
incorporated as a **vendored dependency** (or git submodule) under `apps/agents/tradingagents/`.
Its internal agent graph, analyst roles, debate workflow, and backbone LLM routing are used
directly, **wrapped by HL-specific adapters** that:

1. Replace TradingAgents' generic data feeds with HyperLiquid + IntelliClaw + onchain sources
2. Enforce typed output schemas (JSON matching the proto contracts) instead of free-form text
3. Route outputs into the Orchestrator API's typed state store rather than a local in-memory graph
4. Add the `onchain` analyst role (not in the base framework) for HL-specific DeFi signals

### 4.2 What Is Used Unchanged

- Analyst agent class hierarchy (fundamental, sentiment, news, technical)
- Bull/bear researcher pattern and debate facilitator
- Trader agent synthesis pattern
- Backbone LLM routing concept (fast models for retrieval, strong models for synthesis/debate)
- Risk management team structure (mapped to aggressive/neutral/conservative profiles)


### 4.3 What Is Extended or Replaced

| TradingAgents Component | This Repo Extension |
| :-- | :-- |
| In-process agent graph | Distributed services via Orchestrator API event bus |
| Free-form string outputs | Typed protobuf/JSON artifact outputs |
| Single-process execution | SAE non-bypassable approval layer |
| Generic data sources | HL-specific: HyperLiquid REST/WS, IntelliClaw, Pyth, onchain |
| No operator governance | OpenClaw adapter + Clawvisor HITL rulesets |
| No audit trail | Immutable DecisionTrace per cycle in Postgres |
| No post-trade reflection | Jobs service: offline evaluation, prompt-policy scoring |

### 4.4 Model Routing

Following the backbone-model routing concept from the paper:


| Stage | Model Class | Rationale |
| :-- | :-- | :-- |
| Data normalization, entity extraction | Fast/cheap (GPT-4o-mini, Haiku) | High volume, low reasoning requirement |
| Analyst synthesis | Mid-tier (GPT-4o, Sonnet) | Domain reasoning on structured inputs |
| Bull/bear debate rounds | Strong reasoning (o3, Opus) | Adversarial argument quality matters |
| Trader synthesis | Strong reasoning | Final intent formulation |
| Risk committee | Mid-tier × 3 profiles | Parallel profile evaluation |
| Fund manager | Strong reasoning | Portfolio-level constraint enforcement |
| SAE | Deterministic rule engine | No LLM — hard policy only |


---

## 5. Runtime Architecture

### 5.1 Service Map

```
┌─────────────────────────────────────────────────────────┐
│                    OpenClaw Control Plane                │
│  (cycle trigger, HITL approval, policy governance,       │
│   service halt/resume, strategy lifecycle)               │
└────────────────────────┬────────────────────────────────┘
                         │ REST + WebSocket
┌────────────────────────▼────────────────────────────────┐
│                   Orchestrator API                       │
│  (cycle coordinator, shared typed state store,           │
│   event bus, HITL gate query, audit log writer)          │
└──────┬──────────┬──────────────┬────────────────────────┘
       │          │              │
┌──────▼──────┐  ┌▼────────────┐ ┌▼────────────────────┐
│  Agents Svc │  │  SAE Engine │ │    Executors Svc     │
│  (TradingAg │  │  (policy,   │ │  (HL paper/live,     │
│  + adapters)│  │  hard gates,│ │   fill reconciler)   │
└──────┬──────┘  │  staged     │ └──────────┬───────────┘
       │         │  requests)  │            │
       │         └──────┬──────┘            │
       │                │                   │
       └────────────────▼───────────────────▼
                  Postgres / MLflow / Object Store
                  (DecisionTraces, fills, policies,
                   prompt history, experiments)
                         │
               ┌─────────▼──────────┐
               │   Dashboard / UI   │
               │  (traces, govern., │
               │   experiments)     │
               └────────────────────┘
```


### 5.2 Decision Cycle Flow

```
1. INGEST        Market snapshot (HL OHLCV + OB + funding)
                 + IntelliClaw intel feed
                 + Sentiment/news ingestion
                 + Onchain signals

2. ANALYZE       5 specialist analysts → ResearchPacket
                 [fundamental, sentiment, news, technical, onchain]

3. DEBATE        Bull researcher thesis + Bear researcher thesis
                 → Facilitator debate (N rounds)
                 → DebateOutcome [consensus_strength, open_risks]

4. TRADE         Trader agent synthesizes ResearchPacket + DebateOutcome
                 → TradeIntent [action, confidence, notional_pct, rationale]

5. RISK          3 risk profiles evaluate TradeIntent in parallel
                 → RiskVote × 3 → RiskReview [committee_result, net_size_cap]

6. FUND MGR      Fund manager applies portfolio constraints
                 → ExecutionApprovalRequest → ExecutionApproval

7. HITL GATE     Clawvisor HITL ruleset evaluated
                 → If required: pause for human approval via OpenClaw

8. SAE           Deterministic policy checks (position limits, drawdown,
                 correlation, liquidity, stale data, leverage caps)
                 → ExecutionDecision [allowed, checks_passed/failed, staged_requests]

9. EXECUTE       Executor submits staged requests to HyperLiquid
                 → FillReport(s)

10. RECONCILE    Fill reconciler updates portfolio state

11. PERSIST      DecisionTrace written to Postgres with all artifacts

12. REFLECT      Post-trade jobs: scoring, ablation contribution,
                 prompt-policy evaluation (off hot path)
```


### 5.3 No-Trade Conditions

The system **must** emit `action: FLAT` and skip execution when any of the following are true:

- `debate_outcome.consensus_strength < config.min_consensus_threshold`
- `risk_review.committee_result == "reject"` and `config.require_unanimous_for_live == true`
- `sae_decision.allowed == false`
- `execution_approval.approved == false`
- Any analyst report has `data_gap: true`
- Any required condition in `trade_intent.required_conditions` is not satisfied
- HITL gate is open (awaiting human approval) and timeout has not expired

---

## 6. Data Contracts

### 6.1 Core Types (common.proto)

```protobuf
syntax = "proto3";
package tradingfirm.common;

message Meta {
  string cycle_id              = 1;
  string correlation_id        = 2;
  string strategy_version      = 3;
  string prompt_policy_version = 4;
  string market_snapshot_id    = 5;
  int64  created_at_ms         = 6;
  string operator_identity     = 7;
}

enum Direction {
  DIRECTION_UNSPECIFIED = 0;
  LONG  = 1;
  SHORT = 2;
  FLAT  = 3;
}

enum TradeMode {
  TRADE_MODE_UNSPECIFIED = 0;
  BACKTEST  = 1;
  PAPER     = 2;
  LIVE      = 3;
  RECOVERY  = 4;
}

enum MarketRegime {
  REGIME_UNSPECIFIED = 0;
  TREND_UP    = 1;
  TREND_DOWN  = 2;
  RANGE       = 3;
  EVENT_RISK  = 4;
  HIGH_VOL    = 5;
}
```


### 6.2 Decisioning (decisioning.proto)

```protobuf
message AnalystScore {
  string            analyst       = 1;
  double            score         = 2;
  double            confidence    = 3;
  repeated string   key_points    = 4;
  repeated string   evidence_refs = 5;
  bool              data_gap      = 6;
}

message ResearchPacket {
  tradingfirm.common.Meta         meta              = 1;
  string                          asset             = 2;
  tradingfirm.common.MarketRegime regime            = 3;
  repeated AnalystScore           analyst_scores    = 4;
  bool                            has_macro_event   = 5;
  bool                            has_data_gap      = 6;
  bool                            has_liq_warning   = 7;
  double                          volatility_zscore = 8;
  double                          funding_rate      = 9;
}

message DebateOutcome {
  tradingfirm.common.Meta meta               = 1;
  double                  bull_score         = 2;
  double                  bear_score         = 3;
  string                  bull_thesis        = 4;
  string                  bear_thesis        = 5;
  double                  consensus_strength = 6;
  repeated string         open_risks         = 7;
  string                  facilitator_summary = 8;
  uint32                  debate_rounds      = 9;
}

message TradeIntent {
  tradingfirm.common.Meta  meta                  = 1;
  string                   asset                 = 2;
  tradingfirm.common.Direction action            = 3;
  double                   thesis_strength       = 4;
  double                   confidence            = 5;
  double                   target_notional_pct   = 6;
  double                   preferred_leverage    = 7;
  uint32                   max_slippage_bps      = 8;
  string                   time_horizon          = 9;
  repeated string          required_conditions   = 10;
  string                   rationale             = 11;
}
```


### 6.3 Risk (risk.proto)

```protobuf
message RiskVote {
  tradingfirm.common.Meta meta         = 1;
  string                  profile      = 2;
  bool                    approve      = 3;
  double                  size_cap_pct = 4;
  repeated string         objections   = 5;
}

message RiskReview {
  tradingfirm.common.Meta meta              = 1;
  repeated RiskVote       votes             = 2;
  string                  committee_result  = 3;
  double                  net_size_cap_pct  = 4;
  repeated string         unresolved_risks  = 5;
}

message ExecutionApprovalRequest {
  tradingfirm.common.Meta              meta                   = 1;
  tradingfirm.decisioning.TradeIntent  trade_intent           = 2;
  RiskReview                           risk_review            = 3;
  double                               portfolio_exposure_pct = 4;
  double                               daily_pnl_pct          = 5;
  double                               drawdown_pct           = 6;
  double                               correlation_to_book    = 7;
}

message ExecutionApproval {
  tradingfirm.common.Meta meta               = 1;
  bool                    approved           = 2;
  string                  rejection_reason   = 3;
  double                  final_notional_pct = 4;
  double                  final_leverage     = 5;
  string                  execution_algo     = 6;
}
```


### 6.4 Execution (execution.proto)

```protobuf
message ExecutionRequest {
  tradingfirm.common.Meta      meta             = 1;
  string                       asset            = 2;
  tradingfirm.common.Direction action           = 3;
  double                       notional_usd     = 4;
  double                       leverage         = 5;
  string                       algo             = 6;
  uint32                       max_slippage_bps = 7;
  bool                         reduce_only      = 8;
  string                       tif              = 9;
}

message ExecutionDecision {
  tradingfirm.common.Meta      meta              = 1;
  bool                         allowed           = 2;
  string                       policy_version    = 3;
  repeated string              checks_passed     = 4;
  repeated string              checks_failed     = 5;
  repeated ExecutionRequest    staged_requests   = 6;
  string                       rejection_reason  = 7;
}

message FillReport {
  tradingfirm.common.Meta meta             = 1;
  string                  venue_order_id   = 2;
  string                  asset            = 3;
  double                  filled_qty       = 4;
  double                  avg_price        = 5;
  double                  fees_usd         = 6;
  double                  slippage_bps     = 7;
  string                  status           = 8;
}
```


### 6.5 DecisionTrace (JSON — stored in Postgres)

```json
{
  "cycle_id": "cyc_01JQ...",
  "asset": "BTC-PERP",
  "mode": "paper",
  "market_snapshot_id": "ms_01JQ...",
  "strategy_version": "paper/v17",
  "prompt_policy_versions": {
    "fundamental":        "fundamental/v4",
    "sentiment":          "sentiment/v3",
    "news":               "news/v5",
    "technical":          "technical/v6",
    "onchain":            "onchain/v2",
    "bull":               "bull/v3",
    "bear":               "bear/v3",
    "trader":             "trader/v9",
    "risk_aggressive":    "risk-aggressive/v2",
    "risk_neutral":       "risk-neutral/v3",
    "risk_conservative":  "risk-conservative/v2",
    "fund_manager":       "fund-manager/v4"
  },
  "research_packet":           {},
  "debate_outcome":            {},
  "trade_intent":              {},
  "risk_review":               {},
  "execution_approval_req":    {},
  "execution_approval":        {},
  "hitl_gate": {
    "required": false,
    "approved_by": null,
    "approved_at_ms": null
  },
  "sae_decision":              {},
  "fill_reports":              [],
  "final_state": {
    "result": "filled|no_fill|rejected_sae|rejected_risk|rejected_hitl|flat",
    "halt_flags": [],
    "total_latency_ms": 2140,
    "agent_latencies_ms": {}
  }
}
```


### 6.6 Clawvisor HITL Ruleset (JSON)

```json
{
  "ruleset_id": "hitl_default_v1",
  "enabled": true,
  "rules": [
    {
      "name": "live_always_requires_human",
      "when": { "mode": ["live"] },
      "require_approval": true,
      "timeout_seconds": 300,
      "on_timeout": "reject"
    },
    {
      "name": "large_notional",
      "when": { "notional_pct_gte": 0.05 },
      "require_approval": true,
      "timeout_seconds": 120,
      "on_timeout": "reject"
    },
    {
      "name": "risk_committee_not_unanimous",
      "when": { "committee_result": ["approve_with_modification", "reject"] },
      "require_approval": true,
      "timeout_seconds": 180,
      "on_timeout": "reject"
    },
    {
      "name": "strategy_promotion",
      "when": { "event_type": ["strategy_version_change", "prompt_policy_promotion"] },
      "require_approval": true,
      "timeout_seconds": 3600,
      "on_timeout": "reject"
    }
  ]
}
```


---

## 7. Orchestrator API

### 7.1 Endpoints

| Method | Path | Description |
| :-- | :-- | :-- |
| `POST` | `/cycles/trigger` | Trigger a new decision cycle |
| `GET` | `/cycles/:id` | Get cycle status |
| `GET` | `/traces/:id` | Get full DecisionTrace |
| `GET` | `/traces` | List traces (paginated, filterable) |
| `POST` | `/control/halt` | Emergency halt all cycles |
| `POST` | `/control/resume` | Resume after halt |
| `POST` | `/governance/hitl-rules` | Update HITL ruleset |
| `POST` | `/governance/hitl-rules/:rule/approve` | Human approval for open HITL gate |
| `POST` | `/governance/prompt-policies/promote` | Promote prompt-policy version |
| `POST` | `/governance/strategies/promote` | Promote strategy version |
| `POST` | `/sae/policies/reload` | Hot-reload SAE policy |
| `GET` | `/status` | System health |
| `GET` | `/metrics` | Prometheus scrape endpoint |

### 7.2 Cycle Trigger Request

```json
{
  "asset": "BTC-PERP",
  "mode": "paper",
  "requested_by": "openclaw",
  "reason": "scheduled_cycle",
  "constraints": {
    "max_notional_pct": 0.10,
    "require_hitl": false,
    "require_risk_unanimity": false,
    "force_flat": false
  }
}
```


---

## 8. Safety Architecture

### 8.1 Invariants

These invariants **must** hold in all modes, verified by architecture tests:

1. No `ExecutionRequest` reaches an Executor without a passing `ExecutionDecision` from SAE
2. No `ExecutionDecision` is issued without an `ExecutionApproval` from Fund Manager
3. No live-mode cycle completes without HITL approval when the active ruleset requires it
4. All DecisionTrace artifacts are written atomically before fill reconciliation
5. SAE has no LLM dependency; it is a deterministic rule engine only
6. Strategy version changes require Clawvisor HITL approval before taking effect in live mode
7. Prompt-policy versions are immutable once promoted; only new versions may be created

### 8.2 SAE Policy Checks

SAE evaluates the following checks in order; first failure stops evaluation and rejects:


| Check | Threshold (default) | Configurable |
| :-- | :-- | :-- |
| `position_limit` | Max notional per asset ≤ 15% of portfolio | Yes |
| `portfolio_drawdown` | Portfolio drawdown ≤ 8% | Yes |
| `daily_loss_limit` | Daily PnL ≤ -3% | Yes |
| `leverage_cap` | Leverage ≤ 3× paper, ≤ 2× live | Yes |
| `liquidity_gate` | 24h volume ≥ 10× trade notional | Yes |
| `correlation_gate` | New position correlation to book ≤ 0.7 | Yes |
| `stale_data` | Market snapshot age ≤ 60s | Yes |
| `funding_rate` | Funding rate ≤ 0.1% per 8h | Yes |
| `event_blackout` | No active macro event flag | Yes |


---

## 9. Storage Schema

### 9.1 Key Postgres Tables

| Table | Primary Key | Purpose |
| :-- | :-- | :-- |
| `decision_traces` | `cycle_id` | Full DecisionTrace JSON blobs |
| `analyst_reports` | `(cycle_id, analyst)` | Individual analyst outputs |
| `risk_reviews` | `cycle_id` | Committee results |
| `execution_decisions` | `cycle_id` | SAE decisions |
| `fills` | `venue_order_id` | Fill records |
| `prompt_policies` | `(role, version)` | Versioned prompt templates |
| `prompt_history` | `(cycle_id, role)` | Rendered prompts per cycle |
| `strategy_versions` | `(name, version)` | Strategy plugin registry |
| `hitl_rulesets` | `ruleset_id` | HITL rule definitions |
| `human_approvals` | `(cycle_id, rule_name)` | Human approval records |
| `recovery_state` | `service_name` | Last known safe state per service |
| `ablation_results` | `(run_id, variant)` | Ablation experiment outputs |


---

## 10. Observability

### 10.1 Metric Categories

**Trading metrics:** cumulative return, annualized return, Sharpe ratio, max drawdown,
hit rate, turnover, exposure concentration, avg holding period, slippage bps

**Process metrics:** cycle latency P50/P95/P99, analyst latency per role, debate duration,
debate rounds per cycle, veto frequency, no-trade frequency, HITL approval time

**Safety metrics:** SAE rejection frequency per check, stale-data incident count,
risk committee disagreement rate, human override count, recovery entry count,
prompt-policy rollback count

### 10.2 Alerting Thresholds

| Alert | Condition |
| :-- | :-- |
| `trading.drawdown.critical` | Portfolio drawdown > 6% |
| `safety.stale_data` | Market snapshot age > 90s in live mode |
| `safety.sae_rejection_spike` | SAE rejection rate > 30% over 10 cycles |
| `process.cycle_latency` | Cycle P95 latency > 8s |
| `infra.agent_service_down` | Agent service health check fails > 30s |


---

## 11. Limitations and Scope Constraints

The following items are **explicitly out of scope** for this specification:

- Cross-exchange arbitrage or multi-venue execution
- Equity, options, or non-perpetual instruments
- Fully autonomous live trading without HITL approval (always required in v1 live)
- Self-modifying strategy logic (all strategy changes require explicit promotion)
- Any AI-generated reasoning placed directly in an execution path without SAE review

The TradingAgents paper's reported performance (26–27% cumulative return, Sharpe 6–8) was
measured over a narrow 2024 simulation window on selected US equities. These results should be
treated as design validation evidence, **not as live trading performance targets**. All
performance claims for this system require independent walk-forward validation in paper mode
before any live deployment decision.

---

## 12. References

- TradingAgents paper: https://arxiv.org/pdf/2412.20138
- TauricResearch/TradingAgents: https://github.com/TauricResearch/TradingAgents
- HyperLiquid API: https://hyperliquid.gitbook.io/hyperliquid-docs
- This repo: https://github.com/enuno/hyperliquid-trading-firm
