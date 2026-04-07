# CLAUDE.md — OpenClaw / HyperLiquid Trading Firm

> Authoritative guidance for **Claude Code** in this repository.
> Read fully before making any changes. When this file and `AGENTS.md`
> conflict, this file takes precedence for Claude-specific behaviour.
>
> **Navigation:** Core rules live here. Detailed specs are in referenced docs.
> Follow `@`-links rather than re-deriving facts from first principles.

---

## 1. Project Snapshot

| Field | Value |
|:--|:--|
| **Project** | OpenClaw — HyperLiquid Autonomous Trading Firm |
| **Active spec** | [`SPEC-v2.md`](./SPEC-v2.md) |
| **Agent guide** | [`AGENTS.md`](./AGENTS.md) — file edit boundaries, strategy rules, safety |
| **Status** | Experimental — not audited for large-capital use |
| **Languages** | Python 3.11+, TypeScript 5.x, Node.js LTS (22.x) |
| **Runtime** | Docker Compose (dev) · Kubernetes (prod) |
| **Key integrations** | HyperLiquid perps, IntelliClaw, MultiClaw-MLFlow, ResearchClaw, Hummingbot |

---

## 2. What Has Changed — Context Delta

Treat all items below as **implemented and authoritative**.

### 2.1 IntelliClaw Integration
`apps/agents/src/tools/intelliclaw_client.py` and
`apps/agents/src/types/intel.py` are fully implemented.
Four public functions: `get_intel_snapshot()`, `search_events()`,
`iter_alert_stream()`, `get_multi_snapshot()`.
Configuration via env vars only (`INTELLICLAW_URL`, `INTELLICLAW_API_KEY`,
`INTELLICLAW_CACHE_TTL`). All failures raise `IntelliClawError` — never
swallow silently.
→ Full schema, retry policy, and usage rules: `@docs/intelliclaw.md`

### 2.2 Analyst Stubs
All firm-role stubs live in `apps/agents/src/agents/`.
`sentiment_analyst.py` is the only non-empty stub and is the canonical
implementation pattern — call IntelliClaw, return a typed `AnalystReport`.
→ Implementation guide and code pattern: `@docs/analysts.md`

### 2.3 MultiClaw-MLFlow
`multiclaw/mlflow/` is the experiment tracking stack (MLflow + Postgres + MinIO).
All backtests, RL training, and OPRO jobs must log here.
→ Schema, required fields, and operational runbook:
  `@multiclaw/mlflow/docs/EXPERIMENT_STANDARD.md`
  `@multiclaw/mlflow/docs/runbook.md`

### 2.4 MultiClaw-Tools
`multiclaw/tools/` contains agentic reasoning specs and PDF export utilities.
→ Agent control-flow reference: `@multiclaw/tools/agentic-reasoning-framework.md`

### 2.5 ResearchClaw (multiclaw tier)
`multiclaw/AutoResearchClaw/` + `multiclaw/researchclaw-skill/` +
`multiclaw/research-bridge/` implement the semi-manual research layer.
Prompt templates live in `prompts/research/` (`market_structure.yaml`,
`crypto_project_scan.yaml`, `strategy_evaluation.yaml`).
ResearchAgent outputs are READ-ONLY proposals until
`HypothesisSet.approved = true` is set by a human via the dashboard.
→ Integration design, gate matrix, and isolation rules: `@docs/research.md`
→ Agent boundary rules for research paths: `@AGENTS.md §3, §9`

### 2.6 Environment Variables

```bash
# .env.example (canonical template — never commit actual values)
MLFLOW_TRACKING_URI=http://multiclaw-mlflow:5000
INTELLICLAW_URL=http://intelliclaw:8080
INTELLICLAW_API_KEY=<bearer-token>          # optional
INTELLICLAW_CACHE_TTL=60

# Runtime secrets — K8s Secrets only, never in code or .env commits
HL_PRIVATE_KEY=<hyperliquid-private-key>
VAULT_SUBACCOUNT_ADDRESS=<hl-vault-addr>
TRADE_MODE=paper|live
LLM_PROVIDER=<openai|anthropic|etc>
LLM_API_KEY=<provider-key>
```

---

## 3. Architecture

```
 OpenClaw Controller (external, optional)
         │ REST / WS
 apps/orchestrator-api (Node/TS)
  Analysts → Debate → Trader → Risk Council → Fund Manager → SAE
         │                                              │
  apps/agents (Python)                        apps/sae-engine (TS)
   └─ IntelliClaw client                        └─ leverage/drawdown/staged exec
         │                                              │
         └─────────────────────────────────► apps/executors (HyperLiquid / Hummingbot / DEX)

 multiclaw/mlflow        ── experiment tracking (all ML/RL/OPRO jobs)
 multiclaw/research-*    ── ResearchClaw: user-directed, non-execution path
 agent/iteration_loop    ── Karpathy-style overnight autoresearch
```

**Pipeline order is enforced.** Agents never call executors directly.
All orders pass through the SAE engine. ResearchAgent is outside this
pipeline entirely — it has no write path to any execution-path file.

---

## 4. File Edit Rules

> Full boundary table: `@AGENTS.md §3`

**Quick reference — NEVER edit these:**

| File | Reason |
|:--|:--|
| `strategy/strategy_live.py` | Promotion logic only |
| `strategy/strategy_base.py` | Locked interface |
| `agent/safety.py` | Kill switches — human-only |
| `agent/live_bot.py` | Real-fund execution — human-only |
| `agent/paper_bot.py` | Locked orchestration |
| `agent/rl_buffer.py` | DB schema stability |
| `agent/recovery.py` · `exchange.py` · `harness.py` | Human-only or determinism-locked |
| `logs/research/artifacts/**` | Read-only ResearchClaw outputs |
| `.env` / `*.env` / `k8s/secret-template.yaml` | Secrets never in tracked files |

**Strategy edits (`strategy/strategy_paper.py`):**
≤ 3 `StrategyConfig` param changes per iteration · rationale required ·
reference RL buffer evidence · prefer `entry_order_type = "limit"`.
→ Full promotion tiers and config constraints: `@AGENTS.md §4`

---

## 5. Code Quality Gates

Verify before marking any task complete:

- [ ] `ruff check apps/` — zero errors
- [ ] `black --check apps/` — passes
- [ ] `pytest tests/` — passes; new modules maintain ≥ 80% coverage
- [ ] `gitleaks detect` (or equivalent) — zero secrets in tracked files
- [ ] All new public functions and classes have docstrings
- [ ] No blocking calls in async functions (`time.sleep` → `asyncio.sleep`;
  `requests.get` → `aiohttp`)
- [ ] All external data validated through a pydantic model or `from_dict()`
  before being trusted
- [ ] ResearchClaw topics composed via `_format_*_topic()` bridge methods;
  never hardcoded strings in agent code

→ Testing standards and fixture rules: `@AGENTS.md §7`

---

## 6. Security Checklist

Run before every commit touching `apps/`, `config/`, or `infra/`:

- [ ] No `HL_PRIVATE_KEY` or `VAULT_SUBACCOUNT_ADDRESS` in any tracked file
- [ ] No API keys, tokens, or DB passwords in code
- [ ] No `print()` / `logger.*` emitting a secret value at any log level
- [ ] `INTELLICLAW_API_KEY` read exclusively from `os.environ`
- [ ] All HyperLiquid calls go through `exchange.py`; all IntelliClaw calls
  go through `intelliclaw_client.py` — no raw `requests.get()` to either
- [ ] `VAULT_SUBACCOUNT_ADDRESS` is read-only at runtime; no agent code path
  can write it
- [ ] ResearchClaw outputs never appear in `strategy/` or `agent/` paths

→ Full security rules: `@AGENTS.md §8`

---

## 7. Commit Format

```
type(scope): short description

[optional body: rationale — required for strategy_paper.py changes]
```

Types: `feat` · `fix` · `docs` · `refactor` · `test` · `chore` · `perf`

Scope examples: `intelliclaw` · `sentiment-analyst` · `sae-engine` ·
`orchestrator` · `dashboard` · `mlflow` · `strategy` · `research-bridge`

---

## 8. Quick Start (Dev)

```bash
git clone https://github.com/enuno/hyperliquid-trading-firm.git
cd hyperliquid-trading-firm

cp .env.example .env
# Edit .env: LLM_PROVIDER, LLM_API_KEY, INTELLICLAW_URL,
#            MLFLOW_TRACKING_URI, testnet HL keys

docker-compose up -d
# Starts: orchestrator-api, sae-engine, agents, HL executor (paper),
#         Postgres, Redis, dashboard → http://localhost:3000

# MultiClaw-MLFlow (separate stack)
cd multiclaw/mlflow/infra && cp .env.example .env
docker compose up -d   # MLflow UI → http://localhost:5000

# ResearchClaw smoke test
/researchclaw:setup && /researchclaw:validate   # expect 58/58 tests pass
```

---

## 9. Do / Don't

| ✅ DO | ❌ DON'T |
|:--|:--|
| Use `get_intel_snapshot()` / `search_events()` for all analyst data | Raw HTTP calls to IntelliClaw from agent classes |
| Implement analysts following the `SentimentAnalystAgent` pattern | Leave `generate_report()` as `NotImplementedError` in production |
| Log all ML/backtest runs to MLflow per `EXPERIMENT_STANDARD.md` | Use local-filesystem MLflow backend in production |
| Use `IntelSnapshot.to_analyst_context()` for LLM prompt injection | Serialise raw dataclasses into prompts |
| Surface `IntelliClawError` to the orchestrator | Silently swallow it inside analyst classes |
| Keep secrets in `.env` (dev) or K8s Secrets (prod) | Hardcode tokens, keys, or addresses anywhere |
| Write tests before marking implementation tasks complete | Ship untested analyst or tool code to `main` |
| Follow SPEC-v2 promotion rules for `strategy_paper.py` | Write `strategy_live.py` directly |
| Compose ResearchClaw topics via `_format_*_topic()` bridge methods | Hardcode topic strings or write artifacts to execution paths |
| Require `HypothesisSet.approved = true` before iter loop consumption | Set `HypothesisSet.approved` from `ResearchAgent` code |

---

## 10. Reference Index

| Topic | File |
|:--|:--|
| File edit boundaries, strategy rules, agent pipeline | `@AGENTS.md` |
| Detailed system specification | `@SPEC-v2.md` |
| IntelliClaw schema, retry policy, usage rules | `@docs/intelliclaw.md` |
| Analyst implementation guide and patterns | `@docs/analysts.md` |
| MLflow experiment schema and required fields | `@multiclaw/mlflow/docs/EXPERIMENT_STANDARD.md` |
| MLflow operational runbook | `@multiclaw/mlflow/docs/runbook.md` |
| ResearchClaw integration design and gate matrix | `@docs/research.md` |
| Agentic reasoning and control-flow reference | `@multiclaw/tools/agentic-reasoning-framework.md` |
| ResearchClaw prompt templates | `@prompts/research/` |
