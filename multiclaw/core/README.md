# multiclaw/core

> **MultiClaw-Core** is the orchestration and control-plane layer of the HyperLiquid Autonomous Trading Firm.  
> It schedules agent decision cycles, routes tool calls across all `multiclaw` sub-systems, enforces governance gates, and maintains the global runtime state that every downstream service reads from.

---

## Table of Contents

1. [Role in the MultiClaw Architecture](#role-in-the-multiclaw-architecture)
2. [Responsibilities](#responsibilities)
3. [Directory Layout](#directory-layout)
4. [Data & Decision Flow](#data--decision-flow)
5. [Agent Team Model](#agent-team-model)
6. [OpenClaw Tool Registry](#openclaw-tool-registry)
7. [Safety & Kill-Switch Layer](#safety--kill-switch-layer)
8. [Configuration Reference](#configuration-reference)
9. [Environment Variables](#environment-variables)
10. [Running Locally](#running-locally)
11. [Kubernetes / ArgoCD Deployment](#kubernetes--argocd-deployment)
12. [Observability](#observability)
13. [Security Model](#security-model)
14. [Open Questions & TODOs](#open-questions--todos)
15. [Related Modules](#related-modules)

---

## Role in the MultiClaw Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        multiclaw/core  ◄──── YOU ARE HERE           │
│   Scheduler · Tool Router · GlobalAgentState · Governance API       │
└──────┬────────────────────────────────────────────────────┬─────────┘
       │  OpenClaw Tool calls                               │  State reads
       ▼                                                    ▼
┌──────────────────┐   ┌────────────────────┐   ┌────────────────────┐
│ multiclaw/       │   │ multiclaw/         │   │ multiclaw/         │
│ hyperliquid-claw │   │ intelliclaw        │   │ bankr              │
│ (Exchange + SAE  │   │ (Intel ETL /       │   │ (Treasury /        │
│  Execution)      │   │  Signal Scoring)   │   │  Risk Engine)      │
└──────────────────┘   └────────────────────┘   └────────────────────┘
       │                        │
       ▼                        ▼
┌──────────────────┐   ┌────────────────────┐
│ multiclaw/mlflow │   │ multiclaw/tools    │
│ (Experiment      │   │ (Shared Utilities/ │
│  Tracking)       │   │  CLI Helpers)      │
└──────────────────┘   └────────────────────┘
```

MultiClaw-Core is the **control plane**; the trading firm apps (`apps/orchestrator-api`, `apps/agents`, `apps/executors`) remain the **execution plane**. Core never places orders directly — it orchestrates, schedules, and governs.

---

## Responsibilities

| Concern | What Core Does |
|---|---|
| **Cycle scheduling** | Triggers short/medium/long-horizon decision cycles on a configurable cron or event-driven basis |
| **Tool routing** | Maintains the OpenClaw Tool Registry; dispatches calls to `hyperliquid-claw`, `intelliclaw`, `bankr`, and `mlflow` |
| **Global state** | Owns and publishes `GlobalAgentState` — the single source of truth for all analyst reports, regime classification, active positions, and prompt-policy versions |
| **Governance** | Exposes HTTP governance endpoints consumed by the dashboard; enforces HITL approval gates before promoting strategies to live |
| **Prompt-policy management** | Reads/writes `PromptPolicyStore` (Postgres); feeds per-role policies to the TradingAgents pipeline |
| **Credit assignment** | Enriches `FilledTrade` records with policy-version metadata so the `PromptOptimizer` can update per-role prompt hyperparams |
| **Experiment coordination** | Instructs `multiclaw/mlflow` to open/close runs; logs cycle-level metrics (Sharpe, drawdown, regime, policy versions) |

---

## Directory Layout

```
multiclaw/core/
├── README.md                  ← this file
├── config/
│   ├── default.toml           ← base config (all envs)
│   └── production.toml        ← production overrides
├── src/
│   ├── main.rs / main.py      ← entrypoint; starts scheduler + HTTP server
│   ├── scheduler.rs/.py       ← cron/event loop; emits CycleRequest events
│   ├── tool_router.rs/.py     ← OpenClaw Tool Registry; dispatches calls
│   ├── state_manager.rs/.py   ← GlobalAgentState; publishes to Redis pub/sub
│   ├── governance.rs/.py      ← HTTP governance API (/governance/*)
│   ├── prompt_policy.rs/.py   ← PromptPolicyStore client; fetch/write policies
│   ├── credit_assign.rs/.py   ← Enriches FilledTrade with decision metadata
│   └── types.rs/.py           ← Shared types: CycleRequest, GlobalAgentState, …
├── k8s/
│   ├── deployment.yaml
│   ├── service.yaml
│   └── configmap.yaml
├── Dockerfile
├── docker-compose.yml
└── tests/
    ├── scheduler_test.rs/.py
    ├── tool_router_test.rs/.py
    └── governance_test.rs/.py
```

> **Note:** Language choice (Rust vs. Python) is tracked as an open question — see [Open Questions](#open-questions--todos). The directory above uses dual suffixes as a placeholder.

---

## Data & Decision Flow

```
1. Scheduler  ──► CycleRequest { asset, horizon, mode }
2. Core       ──► intelliclaw.getIntelSnapshot(asset)
                   intelliclaw.getEventStream(asset, window=24h)
3. Core       ──► GlobalAgentState.update(intelReports)
4. Orchestrator-API ◄── POST /cycles/run { asset, horizon, mode, intelSummaryId }
                         (TradingAgents pipeline: Analysts → Debate → Trader → Risk → SAE)
5. SAE        ──► ExecutionDecision slices
6. hyperliquid-claw ──► FilledTrade records
7. Core.CreditAssigner ──► FilledTrade + { policyVersions, regimeAtDecision }
8. Core       ──► mlflow.logCycleMetrics(run_id, metrics)
9. PromptOptimizer (daily/weekly) ──► PromptPolicyStore.write(new versions)
```

---

## Agent Team Model

Core mediates between agent roles as defined in the TradingAgents + ATLAS architecture.  
Each role has a **PromptPolicy** (versioned, stored in Postgres) that Core fetches before handing off to the orchestrator.

| Role | Prompt Policy Key | Reports Produced |
|---|---|---|
| MarketAnalyst | `market_analyst_v{n}` | `MarketAnalystReport` (multi-timescale: 2y/6m/3m) |
| NewsAnalyst | `news_analyst_v{n}` | `NewsAnalystReport` |
| FundamentalAnalyst | `fundamental_analyst_v{n}` | `FundamentalAnalystReport` |
| SentimentAnalyst | `sentiment_analyst_v{n}` | `SentimentReport` |
| BullResearcher | `bull_researcher_v{n}` | `ResearchDebateReport` |
| BearResearcher | `bear_researcher_v{n}` | `ResearchDebateReport` |
| Trader | `trader_v{n}` | `TraderDecisionSignal` |
| RiskCouncil (×3) | `risk_{aggressive,neutral,conservative}_v{n}` | `RiskAssessmentReport` |
| FundManager | `fund_manager_v{n}` | `ExecutionRequest` |

Policy versions increment on every accepted `PromptOptimizer` update.  
Core **never** allows live trading with a policy version that has not passed the paper-trade acceptance threshold configured in `default.toml`.

---

## OpenClaw Tool Registry

Core exposes a catalog of typed tools that agents (and MultiClaw itself) can call.  
Each tool is a thin HTTP/subprocess wrapper over a downstream service.

```python
# tool_router.py — excerpt (illustrative)

TOOL_REGISTRY = {
    # --- Trading Firm (apps/orchestrator-api) ---
    "run_trading_cycle":      POST("/cycles/run"),
    "backtest_strategy":      CLI("apps/jobs/src/backtest_runner.py"),
    "update_sae_policy":      PUT("/sae/policies/{id}"),

    # --- hyperliquid-claw ---
    "hl_get_candles":         GET("/candles/{asset}/{interval}"),
    "hl_get_positions":       GET("/positions"),
    "hl_place_order":         POST("/orders"),           # SAE-gated

    # --- intelliclaw ---
    "intel_get_snapshot":     GET("/intel/snapshot?asset={asset}"),
    "intel_search_events":    GET("/intel/events?asset={asset}&window={window}"),
    "intel_alert_stream":     WS("/intel/alerts/{asset}"),

    # --- bankr ---
    "bankr_get_risk_summary": GET("/risk/summary"),
    "bankr_rebalance":        POST("/treasury/rebalance"),

    # --- mlflow ---
    "mlflow_log_metrics":     POST("/api/2.0/mlflow/runs/log-metric"),
    "mlflow_start_run":       POST("/api/2.0/mlflow/runs/create"),
    "mlflow_end_run":         POST("/api/2.0/mlflow/runs/update"),
    "eval_hypersignal_config": CLI("apps/jobs/src/hypersignal_eval.py"),
}
```

Tools that can affect live positions (`hl_place_order`, `bankr_rebalance`) require:
1. `mode != "paper"` assertion
2. SAE `ExecutionDecision.approved == true`
3. Drawdown guard: current DD < configured kill-switch threshold

---

## Safety & Kill-Switch Layer

Core implements a two-tier safety model on top of `apps/agents/src/safety.py` (locked file):

### Tier 1 — Per-Cycle Guards (enforced before `run_trading_cycle`)

| Guard | Default Threshold | Action on Breach |
|---|---|---|
| Max position size | $2,000 notional (live) | Block cycle; emit `SAFETY_HALT` event |
| Max concurrent positions | 1 | Block new entry |
| Daily loss limit | 2% of account equity | Halt trading for remainder of UTC day |
| Max drawdown kill-switch | 8% peak-to-trough | Full stop; page on-call; require HITL reset |
| Funding rate filter | >0.05%/8h adverse | Skip entry; log `FUNDING_SKIP` |

### Tier 2 — System-Level Circuit Breakers

- **Heartbeat monitor**: if `state_manager` misses two consecutive 30-second heartbeats from `hyperliquid-claw`, all pending execution is cancelled.
- **WS desync guard**: if the WebSocket reconnect counter exceeds 5 attempts within 60 seconds, Core switches to REST-only mode and reduces cycle frequency.
- **Stale state guard**: any `GlobalAgentState` older than `max_state_age_seconds` (default: 120) blocks the Trader role from producing a new signal.

---

## Configuration Reference

`config/default.toml`:

```toml
[scheduler]
horizons = ["short", "medium"]      # "long" disabled until >50 successful short iterations
short_interval_seconds  = 300       # 5-minute short-horizon cycle
medium_interval_seconds = 3600      # 1-hour medium-horizon cycle
paper_eval_hours        = 12        # paper-trade window before live promotion

[risk]
max_position_usd        = 2000
max_concurrent_positions = 1
daily_loss_limit_pct    = 2.0
max_drawdown_kill_pct   = 8.0
min_edge_bps            = 10        # skip trade if expected edge < 10 bps after fees
adverse_funding_threshold = 0.0005  # 0.05% per 8h

[prompt_optimizer]
update_schedule   = "0 3 * * *"    # 03:00 UTC daily
min_paper_trades  = 20             # minimum sample before policy update
sharpe_threshold  = 1.5            # acceptance threshold for paper eval
max_param_changes_per_iter = 3

[state]
redis_pub_sub_channel = "global_agent_state"
max_state_age_seconds = 120

[mlflow]
experiment_name       = "multiclaw_core_cycles"
tracking_uri_env      = "MLFLOW_TRACKING_URI"

[governance]
require_hitl_for_live = true        # HITL approval required before live promotion
approval_timeout_hours = 24
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `MULTICLAW_ENV` | Yes | `development` \| `staging` \| `production` |
| `ORCHESTRATOR_URL` | Yes | Base URL of `apps/orchestrator-api` |
| `INTELLICLAW_URL` | Yes | Base URL of `multiclaw/intelliclaw` service |
| `BANKR_URL` | Yes | Base URL of `multiclaw/bankr` service |
| `HL_CLAW_URL` | Yes | Base URL of `multiclaw/hyperliquid-claw` |
| `MLFLOW_TRACKING_URI` | Yes | URI of `multiclaw/mlflow` tracking server |
| `REDIS_URL` | Yes | Redis connection string for state pub/sub |
| `DATABASE_URL` | Yes | Postgres DSN for `PromptPolicyStore` and governance DB |
| `MULTICLAW_CORE_API_TOKEN` | Yes | Bearer token for downstream service auth; injected via K8s Secret |
| `TRADE_MODE` | Yes | `paper` \| `live` — gates live order placement |
| `LOG_LEVEL` | No | `debug` \| `info` \| `warn` \| `error` (default: `info`) |

**Security:** No secrets are committed to this repository. All tokens and DSNs are injected at runtime via Kubernetes Secrets or a compatible secret manager.

---

## Running Locally

```bash
# 1. Prerequisites
#    - Docker + Docker Compose
#    - Access to a HyperLiquid paper-trade wallet (HL_PAPER_WALLET env)
#    - .env file (copy .env.example, fill in values)

cp .env.example .env

# 2. Start the local stack (Redis, Postgres, MLflow, mock services)
docker compose up -d

# 3. Run Core in paper-trade mode
TRADE_MODE=paper cargo run   # Rust
# or
TRADE_MODE=paper python src/main.py   # Python
```

### Minimal .env.example

```dotenv
MULTICLAW_ENV=development
ORCHESTRATOR_URL=http://localhost:8080
INTELLICLAW_URL=http://localhost:8090
BANKR_URL=http://localhost:8091
HL_CLAW_URL=http://localhost:8092
MLFLOW_TRACKING_URI=http://localhost:5000
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=postgresql://multiclaw:multiclaw@localhost:5432/multiclaw
MULTICLAW_CORE_API_TOKEN=dev-token-replace-me
TRADE_MODE=paper
LOG_LEVEL=debug
```

---

## Kubernetes / ArgoCD Deployment

```
infra/k8s/base/
└── multiclaw-core-deploy.yaml   ← Deployment + Service + ConfigMap
infra/k8s/overlays/
├── staging/
└── production/
```

- Each accepted strategy commit triggers a new paper-trade evaluation pod via ArgoCD.
- `CODEOWNERS` prevents any LLM agent from modifying `k8s/`, `config/production.toml`, or the locked agent files.
- Horizontal scaling is **not** recommended for Core — it should run as a single replica with leader-election if HA is needed (to avoid duplicate cycle triggers).

---

## Observability

| Signal | Mechanism | Key Labels |
|---|---|---|
| Cycle start/end | Structured JSON log + MLflow run | `asset`, `horizon`, `mode`, `cycle_id` |
| Tool call latency | Prometheus histogram | `tool_name`, `status` |
| State publish lag | Prometheus gauge | `state_age_seconds` |
| Safety halts | Alert (PagerDuty / Alertmanager) | `halt_reason`, `asset` |
| Policy version changes | Postgres audit log + dashboard event | `role`, `old_version`, `new_version` |
| Kill-switch trigger | Critical alert + immutable audit log | `trigger_type`, `drawdown_pct` |

All logs must **never** contain secret material (API keys, private keys, DSNs).

---

## Security Model

- **Least-privilege API keys**: Core holds a read-write orchestrator token; it does **not** hold the HyperLiquid private key — that lives exclusively in `hyperliquid-claw`.
- **No agent-writable config**: `config/production.toml`, `k8s/`, and all `*_locked` files are protected by `CODEOWNERS`. Agent-generated diffs to these paths are rejected by CI.
- **Immutable audit log**: every `ExecutionRequest`, `FilledTrade`, and kill-switch event is appended to an append-only Postgres table.
- **Secret injection**: all credentials arrive via Kubernetes Secrets mounted as env vars at pod start. No `.env` files in production images.
- **Zero outbound except allowlist**: egress network policy allows only `orchestrator-api`, `intelliclaw`, `bankr`, `hyperliquid-claw`, `mlflow`, `redis`, and `postgres`.

---

## Open Questions & TODOs

| # | Question | Blocker For | Owner |
|---|---|---|---|
| 1 | Final language choice: Rust vs. Python for Core? | Phase 1 implementation | — |
| 2 | IntelliClaw deployment method (vendor Docker image vs. submodule) | Phase 1 intel pipeline | — |
| 3 | LLM provider for analyst roles (OpenAI / Anthropic / local) | Phase 2 agent loop | — |
| 4 | Redis vs. in-process state bus for `GlobalAgentState` at single-replica scale | Architecture | — |
| 5 | `PromptPolicyStore` schema finalization (Postgres vs. embedded SQLite for dev) | Prompt optimizer | — |
| 6 | Governance HITL UI approval flow (dashboard page spec) | Phase 3 live promotion | — |
| 7 | Short-horizon cycle frequency under HyperLiquid API rate limits | Phase 1 scheduler | — |

---

## Related Modules

| Module | Path | Role |
|---|---|---|
| **hyperliquid-claw** | `multiclaw/hyperliquid-claw/` | Exchange connectivity, SAE execution engine, vault contract |
| **intelliclaw** | `multiclaw/intelliclaw/` | Live intelligence ingestion, cross-source scoring, alert routing |
| **bankr** | `multiclaw/bankr/` | Treasury management, risk engine, BTC→stablecoin rebalancing |
| **mlflow** | `multiclaw/mlflow/` | Experiment tracking backend (Postgres + MinIO artifact store) |
| **tools** | `multiclaw/tools/` | Shared CLI utilities, data helpers, secret scanning scripts |
| **Orchestrator API** | `apps/orchestrator-api/` | TradingAgents decision pipeline entrypoint |
| **SAE Engine** | `apps/sae-engine/` | Survivability-Aware Execution; DG / ASFB / attack-aware gating |
| **Dashboard** | `apps/dashboard/` | Web UI: governance, experiment tracking, live position monitor |

---

*This README is an initial draft. Open a PR to expand sections marked with TODOs or to resolve open questions.*
