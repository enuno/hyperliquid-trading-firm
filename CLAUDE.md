# CLAUDE.md — OpenClaw / HyperLiquid Trading Firm

> Authoritative guidance for **Claude Code** operating in this repository.
> Read this file fully before making any edits. This file complements
> [`AGENTS.md`](./AGENTS.md); when both files address the same topic,
> this file takes precedence for Claude-specific behaviour.

---

## 1. Project Snapshot

| Field | Value |
|:--|:--|
| **Project name** | OpenClaw — HyperLiquid Trading Firm |
| **Active spec** | [`SPEC-v2.md`](./SPEC-v2.md) |
| **Agent guide** | [`AGENTS.md`](./AGENTS.md) |
| **Status** | Experimental — not audited for large-capital use |
| **Primary languages** | Python 3.11+, TypeScript 5.x |
| **Runtime** | Docker Compose (dev), Kubernetes (prod) |
| **Key integrations** | HyperLiquid perps, IntelliClaw, MultiClaw-MLFlow, Hummingbot |

---

## 2. Recent Changes (Context for Claude)

These are the meaningful additions since the initial scaffold. Claude should
treat all of these as **implemented and authoritative**.

### 2.1 IntelliClaw Integration (most recent)

`apps/agents/src/tools/intelliclaw_client.py` and
`apps/agents/src/types/intel.py` are now **fully implemented**.

**`intelliclaw_client.py`** exposes four public functions:

| Function | Purpose |
|:--|:--|
| `get_intel_snapshot(asset, window_hours, bypass_cache)` | Fetch normalised `IntelSnapshot`; TTL-cached in-process |
| `search_events(asset, window, limit, importance)` | Historical event search (news, exploits, protocol changes) |
| `iter_alert_stream(asset, poll_interval, max_alerts)` | Polling generator yielding live `IntelAlert` objects |
| `get_multi_snapshot(assets, window_hours)` | Convenience batch wrapper over `get_intel_snapshot` |

Configuration is via environment variables only:

```bash
INTELLICLAW_URL=http://intelliclaw:8080    # required
INTELLICLAW_API_KEY=<bearer-token>          # optional
INTELLICLAW_CACHE_TTL=60                   # seconds, default 60
```

The client uses a `requests.Session` with a `Retry` adapter
(`total=3, backoff_factor=0.5, status_forcelist=[429,500,502,503,504]`).
All public functions raise `IntelliClawError` (a `RuntimeError` subclass)
on non-retryable failures. Never swallow this exception silently.

**`apps/agents/src/types/intel.py`** defines the full `IntelSnapshot` schema:

```
IntelSnapshot
  ├── asset, as_of, window_hours
  ├── overall_sentiment: SentimentLabel  (bullish|bearish|mixed|neutral)
  ├── confidence: float [0.0–1.0]
  ├── sentiment_score: float [-1.0–+1.0]
  ├── key_points: List[str]
  ├── narrative_summary: Optional[str]
  ├── headlines: List[IntelHeadline]
  ├── onchain: Optional[IntelOnChain]
  ├── fundamental: Optional[IntelFundamental]
  └── alerts: List[IntelAlert]
```

Key helpers on `IntelSnapshot`:
- `.has_critical_alerts` → `bool`
- `.high_importance_headlines` → `List[IntelHeadline]`
- `.to_analyst_context()` → compact string for LLM prompt injection

`IntelAlert.from_dict()` handles both legacy plain-string alerts and
the current `v1+` dict format transparently.

### 2.2 Analyst Stubs (agent layer)

`apps/agents/src/agents/` contains stub files for all firm roles:

```
bullish_researcher.py    bearish_researcher.py
fund_manager.py          fundamental_analyst.py
market_analyst.py        news_analyst.py
onchain_analyst.py       risk_agent_aggressive.py
risk_agent_conservative.py  risk_agent_neutral.py
sentiment_analyst.py     trader_agent.py
```

`sentiment_analyst.py` is the **only non-empty stub** and serves as the
reference implementation pattern:

```python
from ..tools.intelliclaw_client import get_intel_snapshot

class SentimentAnalystAgent:
    def generate_report(self, asset: str):
        intel = get_intel_snapshot(asset)
        # Use intel.overall_sentiment / headlines to build AnalystReport
```

All other analysts should follow this same pattern: call the appropriate
IntelliClaw function, build a typed `AnalystReport` dataclass, and return
it for downstream pipeline consumption.

### 2.3 MultiClaw-MLFlow Library

`multiclaw/mlflow/` contains the **MultiClaw-MLFlow** experiment tracking
stack (MLflow + Postgres + MinIO). This is the model lifecycle and
experiment governance system for all ML/RL training runs in this project.

Key files:

| Path | Purpose |
|:--|:--|
| `multiclaw/mlflow/infra/docker-compose.yml` | Runs `mlflow-db`, `mlflow-minio`, `mlflow-tracking` |
| `multiclaw/mlflow/infra/.env.example` | MinIO and Postgres credentials template |
| `multiclaw/mlflow/docs/EXPERIMENT_STANDARD.md` | Required schema for all MLflow runs |
| `multiclaw/mlflow/docs/architecture.md` | Service topology |
| `multiclaw/mlflow/docs/runbook.md` | Operational runbook |

Tracking URI default: `http://multiclaw-mlflow:5000` (set via
`MLFLOW_TRACKING_URI` env var). All backtests, RL training runs, and
prompt optimization (OPRO) jobs **must** log to MLflow using the standard
defined in `EXPERIMENT_STANDARD.md`.

### 2.4 MultiClaw-Tools Library

`multiclaw/tools/` contains agentic reasoning documentation and PDF/print
utilities. Key files:

- `agentic-reasoning-framework.md` — Technical specification of the
  Cursor-style agentic thought process (intent → plan → tool loop →
  reply). Use this as the reference when designing new agent control-flow.
- `AGENTIC-THOUGHT-PROCESS.md` — Condensed version for quick reference.
- `session-reasoning-template.md` — Template for recording per-session
  reasoning traces.
- `build-pdf.sh` + `pdf-header.tex` — Pandoc-based PDF export with
  tight margins and page numbers.

### 2.5 Environment Variables

`.env.example` (project root) is the canonical template:

```bash
MLFLOW_TRACKING_URI=http://multiclaw-mlflow:5000
INTELLICLAW_URL=http://intelliclaw:8080
INTELLICLAW_API_KEY=<your-token>   # optional
INTELLICLAW_CACHE_TTL=60           # seconds
```

Additional vars from SPEC-v2 (required at runtime, never in code):

```bash
HL_PRIVATE_KEY=<hyperliquid-private-key>     # K8s Secret only
VAULT_SUBACCOUNT_ADDRESS=<hl-vault-addr>     # K8s Secret only
TRADE_MODE=paper|live                        # per-pod flag
LLM_PROVIDER=<openai|anthropic|etc>
LLM_API_KEY=<provider-key>
```

---

## 3. Architecture Quick Reference

```
┌─────────────────────────────────────────────────────────┐
│  OpenClaw Controller  (external, optional)              │
│  Triggers cycles via Orchestrator API                   │
└───────────────────────┬─────────────────────────────────┘
                        │ REST / WS
┌───────────────────────▼─────────────────────────────────┐
│  apps/orchestrator-api  (Node/TS)                       │
│  Decision cycle: Analysts → Debate → Trader →           │
│                  Risk Council → Fund Manager → SAE       │
└─────┬──────────────────────────────────────┬────────────┘
      │                                      │
┌─────▼──────────────┐             ┌─────────▼──────────┐
│  apps/agents       │             │  apps/sae-engine   │
│  (Python)          │             │  (TypeScript)      │
│  • Analysts ←──────┤IntelliClaw  │  • Leverage caps   │
│  • Researchers     │  client     │  • Drawdown rules  │
│  • Trader Agent    │             │  • Staged exec     │
│  • Risk Council    │             └─────────┬──────────┘
│  • Fund Manager    │                       │
└────────────────────┘             ┌─────────▼──────────┐
                                   │  apps/executors    │
                                   │  • HyperLiquid     │
                                   │  • Hummingbot      │
                                   │  • DEX gateway     │
                                   └────────────────────┘
┌─────────────────────────────────────────────────────────┐
│  multiclaw/mlflow   Experiment tracking for all ML/RL   │
│  MLflow + Postgres + MinIO                              │
└─────────────────────────────────────────────────────────┘
```

---

## 4. File Edit Rules

### 4.1 Always Allowed

- `apps/agents/src/agents/*.py` — Implement the stub agents; follow the
  `SentimentAnalystAgent` pattern
- `apps/agents/src/tools/` — Extend or add new tool clients
- `apps/agents/src/types/` — Add new type schemas; never break existing
  `from_dict()` contracts
- `apps/agents/src/atlas/`, `apps/agents/src/memory/`,
  `apps/agents/src/strategies/`, `apps/agents/src/config/`
- `apps/orchestrator-api/`, `apps/dashboard/`, `apps/executors/`,
  `apps/jobs/`
- `multiclaw/tools/` — Documentation and utility scripts
- `multiclaw/mlflow/` — MLflow stack configuration and training scripts
- `config/` — Non-secret YAML config files
- `prompts/` — LLM prompt templates
- `tests/` — Unit and integration tests
- `infra/` — K8s, Terraform, Helm (no `apply`; human review required)
- `strategy/strategy_paper.py` — With max 3 param changes and rationale
- `strategy/strategy_vault.py` — Rate field only

### 4.2 Never Edit

| File | Reason |
|:--|:--|
| `strategy/strategy_live.py` | Written by promotion logic only |
| `strategy/strategy_base.py` | Locked interface |
| `agent/safety.py` | Kill switches — human-only |
| `agent/live_bot.py` | Real-fund execution — human-only |
| `agent/paper_bot.py` | Locked orchestration |
| `agent/rl_buffer.py` | DB schema stability |
| `agent/recovery.py` | Recovery state machine — human-only |
| `agent/exchange.py` | HL SDK auth wrapper — human-only |
| `agent/harness.py` | Deterministic backtest scoring |
| `.env` / `*.env` | Secrets must never be in tracked files |
| `k8s/secret-template.yaml` | Secrets must never be in tracked files |

---

## 5. Implementing an Analyst Agent

All analyst stubs in `apps/agents/src/agents/` are empty except for
`sentiment_analyst.py`. When implementing any analyst, follow this
pattern:

```python
# apps/agents/src/agents/news_analyst.py
from ..tools.intelliclaw_client import get_intel_snapshot, search_events
from ..types.intel import IntelSnapshot, IntelHeadline
from dataclasses import dataclass
from typing import List

@dataclass
class NewsAnalystReport:
    asset: str
    headline_count: int
    high_importance: List[IntelHeadline]
    summary: str
    raw_snapshot: IntelSnapshot

class NewsAnalystAgent:
    def generate_report(self, asset: str, window_hours: int = 24) -> NewsAnalystReport:
        intel = get_intel_snapshot(asset, window_hours=window_hours)
        high = intel.high_importance_headlines
        summary = intel.to_analyst_context()  # LLM-ready text block
        return NewsAnalystReport(
            asset=asset,
            headline_count=len(intel.headlines),
            high_importance=high,
            summary=summary,
            raw_snapshot=intel,
        )
```

Onchain analysts should additionally call `search_events()` with
`importance="high"` for recent protocol/exchange events. Sentiment
analysts can use `iter_alert_stream()` for live monitoring.

---

## 6. MLflow Experiment Logging

All jobs in `apps/jobs/` (backtests, RL training, OPRO prompt updates)
**must** log runs to MultiClaw-MLFlow per the standard in
`multiclaw/mlflow/docs/EXPERIMENT_STANDARD.md`.

Minimal required fields per run:

```python
import mlflow

with mlflow.start_run(run_name="backtest_ema_cross_v42"):
    mlflow.log_params({"strategy": "ema_cross", "ema_fast": 9, "ema_slow": 21})
    mlflow.log_metrics({"sharpe": 1.72, "max_dd": 0.063, "win_rate": 0.51})
    mlflow.log_artifact("strategy/strategy_paper.py")
```

Set `MLFLOW_TRACKING_URI` to `http://multiclaw-mlflow:5000` (already in
`.env.example`). Do not use the default local-filesystem tracking
location in production.

---

## 7. IntelliClaw Client Usage Rules

- **Always use `get_intel_snapshot()` via the module**; do not construct
  raw HTTP calls to IntelliClaw from agent code.
- **Prefer cached calls** (default). Only pass `bypass_cache=True` when
  freshness is required (e.g. live trading decision cycle).
- **Multi-worker deployments**: The in-process `_snapshot_cache` dict is
  not shared across workers. Replace with a Redis-backed cache for
  multi-process agent deployments (noted in the module docstring).
- **Do not catch `IntelliClawError` silently.** Surface it to the
  orchestrator so the decision cycle can mark the analyst as degraded.
- `to_analyst_context()` on `IntelSnapshot` produces a compact, LLM-ready
  string; use this for prompt injection rather than serialising the raw
  dataclass.

---

## 8. Code Quality Gates

Before considering any task complete, verify:

- [ ] `ruff check apps/agents/` passes with zero errors
- [ ] `black --check apps/agents/` passes
- [ ] `pytest tests/` passes (or tests are added to maintain ≥ 80% coverage)
- [ ] No secrets in any tracked file (`gitleaks detect` or equivalent)
- [ ] New public functions and classes have docstrings
- [ ] Async functions do not contain blocking calls (no `time.sleep`,
  `requests.get` — use `asyncio.sleep` and `aiohttp`)
- [ ] All external data is validated through a pydantic model or
  `from_dict()` before being trusted

---

## 9. Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): short description

[optional body: rationale, especially for strategy changes]
```

| Type | Use for |
|:--|:--|
| `feat` | New functionality |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code change without behaviour change |
| `test` | Test additions or fixes |
| `chore` | Build, deps, tooling |
| `perf` | Performance improvement |

Scope examples: `intelliclaw`, `sentiment-analyst`, `sae-engine`,
`orchestrator`, `dashboard`, `mlflow`, `strategy`.

---

## 10. Security Checklist

Run through this before every commit touching `apps/`, `config/`, or
`infra/`:

- [ ] No `HL_PRIVATE_KEY` or `VAULT_SUBACCOUNT_ADDRESS` appears in any
  tracked file
- [ ] No API keys, bearer tokens, or database passwords appear in code
- [ ] No `print()` or `logger.*` call logs a private key or secret env var
- [ ] IntelliClaw `API_KEY` is read exclusively from `os.environ`
- [ ] Vault address is read exclusively from `os.environ`
  (`VAULT_SUBACCOUNT_ADDRESS`); no code path allows an agent to write it
- [ ] All HTTP calls to external services use the established wrapper
  (`exchange.py` for HyperLiquid, `intelliclaw_client.py` for
  IntelliClaw) — no raw `requests.get()` calls to these endpoints in
  agent code

---

## 11. Quick Start (Dev)

```bash
# 1. Clone and enter
git clone https://github.com/enuno/hyperliquid-trading-firm.git
cd hyperliquid-trading-firm

# 2. Set environment
cp .env.example .env
# Edit .env: set LLM_PROVIDER, LLM_API_KEY, INTELLICLAW_URL,
#             MLFLOW_TRACKING_URI, and testnet HL keys

# 3. Start core services
docker-compose up -d
# Brings up: orchestrator-api, sae-engine, agents, HL executor (paper),
#            Postgres, Redis, dashboard (http://localhost:3000)

# 4. Start MultiClaw-MLFlow (separate stack)
cd multiclaw/mlflow/infra
cp .env.example .env   # set MinIO / Postgres creds
docker compose up -d
# MLflow UI: http://localhost:5000
```

---

## 12. Do / Don't Summary

| ✅ DO | ❌ DON'T |
|:--|:--|
| Use `get_intel_snapshot()` / `search_events()` for all analyst data | Call IntelliClaw directly with raw HTTP from agent classes |
| Implement analyst stubs following the `SentimentAnalystAgent` pattern | Leave `generate_report()` raising `NotImplementedError` in production |
| Log all ML/backtest runs to MLflow with required fields | Use the local filesystem MLflow backend in production |
| Use `IntelSnapshot.to_analyst_context()` for LLM prompt injection | Serialise raw dataclasses directly into prompts |
| Handle `IntelliClawError` at the orchestrator level | Silently swallow `IntelliClawError` inside analyst classes |
| Keep all secrets in `.env` (dev) or K8s Secrets (prod) | Hardcode tokens, private keys, or addresses anywhere in code |
| Write tests before marking implementation tasks complete | Ship untested analyst or tool code to `main` |
| Follow SPEC-v2 promotion rules for `strategy_paper.py` | Write to `strategy_live.py` directly |
