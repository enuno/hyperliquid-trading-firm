# AGENTS.md — OpenClaw / HyperLiquid Trading Firm

> This file provides authoritative guidance for AI coding agents (Claude Code,
> GitHub Copilot, Cursor, ChatGPT Code Interpreter, etc.) working inside this
> repository. Read it fully before making any changes.

---

## 1. Project Identity

**Project:** OpenClaw — HyperLiquid Autonomous Trading Firm  
**Purpose:** A modular, multi-agent trading system running production-grade
strategies on HyperLiquid perpetual futures, with extensions for DEX arbitrage
and treasury flows. The "firm" can run standalone or be orchestrated remotely by
an OpenClaw controller via a clean REST/WS API surface.

**Status:** Experimental research software. Not audited. Not suitable for
large-capital trading without additional hardening and monitoring.

**Active Spec:** [`SPEC-v2.md`](./SPEC-v2.md) — all implementation decisions
must conform to v2 unless a newer spec file supersedes it.

---

## 2. Repository Layout

```
apps/
  orchestrator-api/   # Node/TypeScript REST+WS API and agent coordination
  sae-engine/         # TypeScript Survivability-Aware Execution policy engine
  agents/             # Python LLM agents, analysts, strategy plugins
  executors/          # Python venue adapters (HyperLiquid, Hummingbot, DEX)
  dashboard/          # React/Next.js web UI
  jobs/               # Offline backtests, RL training, prompt updates

infra/
  k8s/                # Kubernetes manifests and overlays
  terraform/          # Optional infra provisioning
  helm/               # Optional Helm charts

config/               # Environment, logging, DB, queues, strategy configs
strategy/             # Dual-file strategy architecture (see §4)
agent/                # Core runtime: paper bot, live bot, iteration loop
logs/                 # SQLite experiments DB + JSONL event log
tests/                # Unit and integration tests per service
prompts/              # LLM system and user prompt templates
```

---

## 3. Agent Scope and Boundaries

### 3.1 Files Agents MAY Edit

| Path | Notes |
|:--|:--|
| `strategy/strategy_paper.py` | Primary agent-editable strategy; changes flow to paper bot |
| `strategy/strategy_vault.py` | Vault **rate** only (`vault_take_pct`); vault address is locked |
| `apps/agents/**` | LLM agent logic, analyst microservices, prompt builders |
| `apps/orchestrator-api/**` | Orchestration logic, cycle triggers, config endpoints |
| `apps/dashboard/**` | UI views, charting, metrics display |
| `apps/jobs/**` | Backtesting harness, RL training scripts, OPRO prompt updates |
| `apps/executors/**` | Venue adapter implementations |
| `config/**` | Non-secret configuration (env templates, strategy YAML) |
| `prompts/**` | LLM system prompts and prompt templates |
| `tests/**` | Test coverage for any of the above |
| `infra/**` | K8s manifests, Terraform, Helm — with care (see §6) |

### 3.2 Files Agents MUST NOT Edit

| Path | Reason |
|:--|:--|
| `strategy/strategy_live.py` | Written only by promotion logic; never direct agent writes |
| `strategy/strategy_base.py` | Locked interface; changes break both bots |
| `agent/safety.py` | Kill switches and recovery triggers; human-only |
| `agent/live_bot.py` | Real-fund execution path; human-only |
| `agent/paper_bot.py` | Locked orchestration; strategy swap handled via configmap |
| `agent/rl_buffer.py` | Reinforcement data schema; changes break experiment continuity |
| `agent/recovery.py` | Recovery state machine; human-only |
| `agent/exchange.py` | HL SDK auth and rate-limit wrapper; human-only |
| `agent/harness.py` | Backtest scoring; must remain deterministic |
| `k8s/secret-template.yaml` | Never write secrets to files |
| `.env` / any `*.env` | Never write secrets to files |

> **Hard rule:** The agent has **no write path** to `VAULT_SUBACCOUNT_ADDRESS`,
> `HL_PRIVATE_KEY`, or any K8s Secret value. These are injected at runtime by
> the human operator.

---

## 4. Strategy Architecture

The system uses a **dual-file strategy architecture** governed by a three-tier
promotion lifecycle.

### 4.1 Promotion Tiers

```
BACKTEST  →  Sharpe ≥ 1.5, max_dd < 8%, n_trades ≥ 10
    ↓
PAPER TRADE  →  Sharpe ≥ 1.5, win_rate ≥ 45%, 48h real-time window
    ↓
LIVE TRADE  →  Real funds, vault active, drawdown guards armed
    ↓ (on equity ≤ 50% of session start)
RECOVERY MODE  →  Live halted, accelerated research (200 iter/night),
                  raised bar: Sharpe ≥ 2.0, win_rate ≥ 50%, 72h paper
```

### 4.2 Strategy Config Constraints

When proposing a new `strategy_paper.py`, an agent MUST:

- Implement the `BaseStrategy` interface defined in `strategy/strategy_base.py`
- Change **at most 3** `StrategyConfig` parameters per iteration from the
  current paper config
- Justify each change referencing recent paper trade outcomes from the RL buffer
- Prefer `limit` order types (`entry_order_type = "limit"`)
- Keep `vault_take_pct` within `[0.10, 0.20]`
- Keep `position_size_pct ≤ 0.20` (safety layer will clamp, but stay within range)

### 4.3 Supported Entry/Exit Signals

**Entry:** `ema_cross`, `rsi_reversal`, `breakout`, `bb_squeeze`,
`vwap_reversion`, `hybrid`  
**Exit:** `atr_trail`, `fixed_tp_sl`, `time_exit`, `signal_flip`

Do not introduce signal types outside this enum without updating
`strategy_base.py` in a separate, human-reviewed PR.

---

## 5. Multi-Agent Firm Structure

The orchestrator drives a sequential decision cycle on each trigger:

1. **Analyst Agents** — Market, News, Fundamental, On-chain, Sentiment
2. **Research Debate** — Bull researcher vs. Bear researcher + facilitator
3. **Trader Agent** — Proposes a trade decision using strategy plugins
4. **Risk Council** — Three profiles (aggressive / neutral / conservative) vote
5. **Fund Manager** — Applies portfolio-level constraints
6. **SAE Engine** — Non-bypassable guardrail: validates leverage, size,
   drawdown rules; builds staged execution plans (TWAP/VWAP/POV/Iceberg)
7. **Executor** — Venue adapter places real orders on HyperLiquid (or Hummingbot/DEX)

When implementing or extending any agent in `apps/agents/`, preserve this
pipeline order. Agents must not call executors directly; all trades MUST pass
through the SAE engine.

---

## 6. Infrastructure and Deployment Rules

- **Kubernetes:** All runtime secrets (`HL_PRIVATE_KEY`,
  `VAULT_SUBACCOUNT_ADDRESS`) are mounted from K8s Secrets. Never hardcode or
  log these values.
- **Paper and Live bots** run as separate pods (`deployment-paper.yaml` vs
  `deployment-live.yaml`) with `TRADE_MODE=paper` / `TRADE_MODE=live`.
- **Strategy updates** reach the paper bot via ConfigMap update (ArgoCD picks
  up the `strategy/strategy_paper.py` git commit). Do not hot-patch running
  pods directly.
- **Terraform / Helm changes** must be reviewed by a human before `apply`.
  Agents may generate or modify these files but must not trigger applies.

---

## 7. Coding Standards

### Language Versions
- Python: **3.11+** (type hints required, `dataclass` preferred over raw dicts)
- TypeScript: **5.x**, strict mode enabled
- Node.js: **LTS** (currently 22.x)

### Python Style
- Follow **PEP 8**; use `ruff` for linting and `black` for formatting
- All public functions and classes require docstrings
- Async-first: use `asyncio` / `aiohttp`; avoid blocking calls in the event loop
- Use `pydantic` v2 for data validation and config models

### TypeScript Style
- ESLint with the project's `.eslintrc` config
- Strict null checks enabled
- Prefer `zod` for runtime validation of external data

### Testing
- Minimum **80% coverage** on new modules (`pytest` for Python, `vitest` / `jest`
  for TypeScript)
- Backtest harness tests must be deterministic (fixed seed, fixed candle data)
- Never mock `safety.py` or `rl_buffer.py` in integration tests — use test
  fixtures that exercise real logic

### Commits
- Format: `type(scope): short description` (Conventional Commits)
- Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`
- Strategy commits must include the proposal rationale as the commit body
  (the iteration loop does this automatically via `proposal.rationale`)

---

## 8. Security Rules

- **No secrets in code or config files.** Use environment variables injected
  via K8s Secrets or `.env` (gitignored).
- **Never log private keys, wallet addresses, or API tokens** at any log level.
- **Vault address is immutable at runtime.** Any code path that could allow an
  agent to change `VAULT_SUBACCOUNT_ADDRESS` is a critical security bug.
- **Rate-limit all external API calls.** The `exchange.py` wrapper handles HL
  rate limits; do not bypass it with raw HTTP calls.
- **Input validation on all external data** (HL WebSocket ticks, LLM responses,
  backtest scores). Use pydantic models or zod schemas before any value is
  trusted.
- Run `gitleaks` or equivalent secret scanning before pushing branches that
  touch config or infra files.

---

## 9. Autoresearch Iteration Loop Guidance

When working on `agent/iteration_loop.py` or related files, respect these
constraints:

- **Normal mode:** ≤ 100 backtest experiments per overnight run, 5-minute
  budget per experiment.
- **Recovery mode:** ≤ 200 experiments per run, same 5-minute budget.
- Proposal context MUST include: last 20 backtest experiments, 48h RL
  aggregates, last 50 paper trade outcomes, current live config, market
  snapshot (funding rate, vol regime), and recovery state.
- A proposal that fails `validate_strategy_module()` is logged and skipped; do
  not raise an exception that halts the loop.
- Backtest timeout (5 min) is enforced via `asyncio.wait_for`; handle
  `asyncio.TimeoutError` gracefully.

---

## 10. Dashboard Development

The research dashboard (`apps/dashboard/`) must:

- Display the last 365 days of 1-minute candles per market (sourced from HL
  `candleSnapshot` API + local time-series store)
- Show paper P/L, live P/L, vault balance, drawdown events, and promotion events
- Show current mode: `backtest | paper | live | recovery`
- **Never expose secrets, raw API keys, or HL private key material** in any
  API response or rendered UI
- Implement SSO or reverse-proxy auth before any production deployment

---

## 11. OpenClaw Integration Surface

External controllers (OpenClaw and others) interact with this system via the
Orchestrator API only:

| Endpoint Class | Description |
|:--|:--|
| `POST /cycles/trigger` | Kick off an analyst → debate → trader → risk → SAE cycle |
| `PUT /sae/policies` | Adjust SAE leverage, size, and drawdown policy parameters |
| `PUT /config/strategy` | Update strategy configuration for the paper bot |
| `GET /traces/:id` | Retrieve a full decision trace for audit / auto-research |
| `GET /metrics` | Pull live performance metrics for monitoring |

Do not add endpoints that expose private keys, vault addresses, or allow direct
order placement bypassing the SAE engine.

---

## 12. Quick Reference — Do / Don't

| ✅ DO | ❌ DON'T |
|:--|:--|
| Edit `strategy_paper.py` with ≤ 3 param changes and a rationale | Write `strategy_live.py` directly |
| Use `BaseStrategy` interface for all strategy classes | Bypass the SAE engine to place orders |
| Justify strategy changes with RL buffer evidence | Hardcode secrets, keys, or vault addresses |
| Write tests for every new module (≥ 80% coverage) | Modify `safety.py`, `live_bot.py`, or `rl_buffer.py` |
| Follow Conventional Commits for all commits | Trigger Terraform applies from agent code |
| Validate all external data before trusting it | Log private keys or API tokens at any level |
| Use async-first patterns throughout Python code | Hot-patch running pods directly |
| Use the `exchange.py` wrapper for all HL API calls | Add endpoints that bypass the SAE engine |
