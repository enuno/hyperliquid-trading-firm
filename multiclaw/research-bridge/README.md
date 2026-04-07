# research-bridge

> **Multiclaw module** · Semi-manual research intelligence adapter for the HyperLiquid Autonomous Trading Firm

`research-bridge` is the integration adapter that connects the [AutoResearchClaw](../AutoResearchClaw/) autonomous research pipeline and its [researchclaw-skill](../researchclaw-skill/) wrapper to the rest of the trading firm. It translates internal trading system context — RL buffer aggregates, backtest histories, strategy configs — into structured research topics, invokes AutoResearchClaw's 23-stage pipeline, and routes the resulting artifacts (synthesis reports, hypothesis sets, literature citations, experiment CSVs) back into the firm's `apps/jobs/`, `prompts/`, and dashboard layers.

**This module is never in the live trading path.** It is a supplemental, user-directed research tool. No output from `research-bridge` is written directly to `strategy_live.py`, `safety.py`, or any execution-critical file. All outputs are proposals or read-only artifacts subject to human review.

---

## Table of Contents

- [Architecture Position](#architecture-position)
- [Trigger Modes](#trigger-modes)
- [Module Structure](#module-structure)
- [Configuration](#configuration)
- [ACP Mode — No Separate API Key](#acp-mode--no-separate-api-key)
- [Output Artifacts & Routing](#output-artifacts--routing)
- [Integration Points](#integration-points)
  - [Iteration Loop](#iteration-loop)
  - [Dashboard Research Panel](#dashboard-research-panel)
  - [Prompt Templates](#prompt-templates)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [ResearchMode Reference](#researchmode-reference)
- [Security & Isolation Invariants](#security--isolation-invariants)
- [Risks & Known Limitations](#risks--known-limitations)
- [Development & Testing](#development--testing)

---

## Architecture Position

```
┌─────────────────────────────────────────────────────────┐
│                 multiclaw/ (OpenClaw tier)               │
│                                                         │
│  ┌──────────────────────┐   ┌────────────────────────┐  │
│  │  AutoResearchClaw/   │   │  researchclaw-skill/   │  │
│  │  (upstream pipeline) │   │  (skill + hooks)       │  │
│  └──────────┬───────────┘   └──────────┬─────────────┘  │
│             │                          │                 │
│             └──────────┬───────────────┘                 │
│                        ▼                                 │
│            ┌─────────────────────┐                      │
│            │   research-bridge/  │  ◄── YOU ARE HERE    │
│            │  context_injector   │                      │
│            │  output_parser      │                      │
│            │  research_registry  │                      │
│            └────────┬────────────┘                      │
└─────────────────────┼───────────────────────────────────┘
                      │  read-only proposals & artifacts
          ┌───────────┼────────────────────────────────┐
          ▼           ▼                                 ▼
   apps/jobs/    prompts/research/           apps/dashboard/
   (backtests)   (strategy prompts)          (research panel)
          │
          ▼
   agent/iteration_loop.py   ← Karpathy-style autoresearch
   (reads proposed hypotheses; humans approve promotion)
```

`research-bridge` sits exclusively in the **multiclaw** tier. The trading firm's execution plane — `agent/iteration_loop.py`, `strategy/strategy_paper.py`, `agent/live_bot.py`, the SAE engine, and all executors — remains untouched by this module.

---

## Trigger Modes

Five `ResearchMode` values control pipeline behavior and gate configuration:

| Mode | Who Triggers | Experiment Mode | Gates Active | Primary Output |
|---|---|---|---|---|
| `DEEP` | User via dashboard UI or `/researchclaw:run` | `simulated` or `sandbox` | All 3 (Stages 5, 9, 20) | Full PDF paper + synthesis JSON → `logs/research/artifacts/` |
| `STRATEGY_SCAN` | User provides a strategy class or paper title | `simulated` | Stage 5 only | Hypothesis set + param ranges → `prompts/research/` |
| `PROJECT_AUDIT` | User inputs a ticker, whitepaper URL, or protocol name | `simulated` | All 3 | Structured due-diligence report → dashboard research panel |
| `COMPETITIVE_BACKTEST` | User triggers against a known strategy family | `sandbox` | Stage 9 (review generated code) | Comparison CSV → `apps/jobs/` |
| `NIGHTLY_DIGEST` | Scheduled cron in `apps/jobs/` | `simulated` | None (fully automated) | Literature summary JSON → dashboard |

> **Gate invariant:** Human gates at Stages 5, 9, and 20 are **mandatory** for `DEEP` and `PROJECT_AUDIT` modes. Never pass `--auto-approve` to these modes in production. Use `--auto-approve` only in dev/test environments.

---

## Module Structure

```
multiclaw/research-bridge/
├── README.md                          # This file
├── config.trading-firm.yaml           # Default bridge config (ACP mode)
├── config.trading-firm.example.yaml   # Annotated reference config
│
├── context_injector.py                # Translates firm context → RC topic strings
├── output_parser.py                   # Parses RC artifacts → typed proposal objects
├── research_registry.py               # SQLite registry of all research jobs
├── research_agent.py                  # ResearchAgent class (drops into apps/agents/)
├── research_modes.py                  # ResearchMode enum and mode config structs
│
├── prompt_templates/
│   ├── strategy_evaluation.yaml       # Strategy class → research query
│   ├── crypto_project_scan.yaml       # Ticker + on-chain metrics → audit query
│   └── market_structure.yaml          # Volatility/funding snapshot → micro-structure query
│
├── scripts/
│   ├── nightly_digest.sh              # Cron wrapper for NIGHTLY_DIGEST mode
│   └── validate_bridge.sh             # Pre-flight check (AutoResearchClaw installed, DB writable, config valid)
│
└── tests/
    ├── test_context_injector.py        # Unit: mock RL buffer → topic string
    ├── test_output_parser.py           # Unit: fixture paper JSON → HypothesisSet
    ├── test_research_registry.py       # Unit: SQLite read/write
    └── test_isolation.py              # Integration: verify no RC artifacts land in strategy/ or agent/
```

---

## Configuration

Copy and edit the example config before first use:

```bash
cp multiclaw/research-bridge/config.trading-firm.example.yaml \
   multiclaw/research-bridge/config.trading-firm.yaml
```

Key fields in `config.trading-firm.yaml`:

```yaml
llm:
  provider: "acp"                  # ACP mode: use the agent (OpenClaw) as LLM backend
  acp:
    agent: "openclaw"
    cwd: "."

experiment:
  mode: "simulated"                # Default. Use "sandbox" only for COMPETITIVE_BACKTEST
  max_concurrent_stages: 4

output:
  format: "json+pdf"
  directory: "../../logs/research/artifacts"   # relative to repo root

quality:
  min_score: 3.5                   # Relaxed from upstream default of 2.0; crypto research is noisier

search:
  sources:
    - arxiv
    - semantic_scholar
    - openAlex
  # Crypto-native sources (Messari, DeFiLlama, Token Terminal) are not
  # natively supported by AutoResearchClaw v0.3.x. Pre-process those
  # data sources using context_injector.py before pipeline invocation.

bridge:
  rl_buffer_export_path: "../../logs/rl_buffer_export.json"
  backtest_history_path: "../../logs/experiments.sqlite"
  registry_path: "../../logs/research/research_registry.db"
  max_context_tokens: 4000         # Budget for injected firm context per research job
  artifact_guard: true             # Block any artifact write outside logs/research/
```

---

## ACP Mode — No Separate API Key

`research-bridge` defaults to **ACP (Agent Client Protocol) mode**, which routes all 23 AutoResearchClaw pipeline stages through the already-running OpenClaw agent. No separate OpenAI, Anthropic, or DeepSeek API key is required for research jobs.

```yaml
llm:
  provider: "acp"
  acp:
    agent: "openclaw"
    cwd: "."
```

In ACP mode, the agent maintains a **persistent session** across all stages, so context established during literature review (Stage 4–6) is available when generating experiment code (Stage 10) and drafting the paper (Stage 17). This is the recommended mode for all crypto strategy and project research topics.

To use a dedicated LLM instead (e.g., for Nightly Digest jobs running off-peak), switch to:

```yaml
llm:
  provider: "anthropic"             # or "openai", "deepseek"
  api_key_env: "RESEARCH_LLM_KEY"  # injected via K8s Secret, never hardcoded
  model: "claude-sonnet-4-20250514"
```

---

## Output Artifacts & Routing

Every completed research job writes into `logs/research/artifacts/<job-id>/` and registers an entry in `logs/research/research_registry.db`.

| Artifact | File | Routed To |
|---|---|---|
| Full research paper | `paper.pdf` / `paper.tex` | Dashboard artifact browser |
| Synthesis JSON | `synthesis.json` | `output_parser.py` → `HypothesisSet` |
| Hypothesis set | `hypotheses.json` | `prompts/research/` (human review before use in iteration loop) |
| Literature citations | `citations.bib` | Dashboard literature cache |
| Experiment data | `experiments/*.csv` | `apps/jobs/` (as backtest seed data) |
| Visualizations | `charts/*.png` | Dashboard research panel |

**No artifact is ever written to:**
- `strategy/` — any strategy file
- `agent/` — any agent runtime file
- `apps/executors/` — any execution adapter
- `.env` or K8s secret files

The `artifact_guard: true` config flag enforces this at runtime via the same `pre-delete-guard.sh` pattern used in `researchclaw-skill`.

---

## Integration Points

### Iteration Loop

The Karpathy-style autoresearch loop in `agent/iteration_loop.py` can optionally consume **hypothesis proposals** produced by `research-bridge`. The flow is one-way and human-gated:

```
research-bridge
  └── output_parser → HypothesisSet (JSON)
        └── prompts/research/<topic>/hypotheses.json
              └── [HUMAN REVIEW]
                    └── iteration_loop.py reads approved hypotheses
                          as additional proposal context alongside
                          RL buffer + backtest history
```

An approved `HypothesisSet` entry provides:
- Suggested entry/exit signal modifications (within the approved signal enum)
- Supported parameter ranges for `StrategyConfig` fields
- Source paper citations for audit trail

No hypothesis is consumed by the iteration loop unless a human explicitly moves the approved file into the iteration loop's context path. This is by design.

### Dashboard Research Panel

The `apps/dashboard/` research panel (agent-editable, per `AGENTS.md §3.1`) should expose:

- **Research Queue** — pending, running, and completed jobs with `Stage X/23` progress
- **Artifact Browser** — rendered PDFs and charts from `logs/research/artifacts/`
- **Hypothesis Feed** — parsed hypothesis statements from completed runs, linkable to backtest jobs in `apps/jobs/`
- **Literature Cache** — de-duplicated citations across all runs, searchable by topic and strategy class

The orchestrator API exposes bridge data via:

```
GET /research/jobs             → list jobs from research_registry.db
GET /research/jobs/:id         → job detail + stage progress
GET /research/jobs/:id/artifacts  → artifact file listing
GET /research/hypotheses       → approved hypothesis proposals
```

### Prompt Templates

The `prompt_templates/` directory contains YAML-format templates that `context_injector.py` uses to build ResearchClaw topic strings from structured trading firm data:

| Template | Input Data | Generated Topic Scope |
|---|---|---|
| `strategy_evaluation.yaml` | Strategy class, current Sharpe, max DD, regime label | Academic literature on improvements and failure modes for that strategy type |
| `crypto_project_scan.yaml` | Ticker, TVL, 30d volume, protocol type, whitepaper URL | Tokenomics analysis, competitive landscape, DeFi integration risk |
| `market_structure.yaml` | Volatility regime, funding rate snapshot, OI concentration | Microstructure and basis-trading research relevant to HyperLiquid perps |

---

## Prerequisites

`research-bridge` requires AutoResearchClaw to be installed in the environment running the bridge. The `researchclaw-skill` wrapper handles setup detection:

```bash
# From repo root
cd multiclaw/research-bridge
bash scripts/validate_bridge.sh
```

This script checks:
- `researchclaw` Python package installed and importable
- `config.trading-firm.yaml` present and valid YAML
- `logs/research/` writable
- `rl_buffer_export.json` or `experiments.sqlite` reachable (warns if absent, does not block)
- Docker available (warns if absent; only required for `sandbox` experiment mode)

Full AutoResearchClaw installation:

```bash
# Recommended: install from source for latest fixes
git clone https://github.com/aiming-lab/AutoResearchClaw.git multiclaw/AutoResearchClaw
cd multiclaw/AutoResearchClaw
pip install -e ".[all]"
```

**System requirements** (inherited from AutoResearchClaw):

| Component | Required | Notes |
|---|---|---|
| Python | 3.11+ | |
| LLM API key | Only if not using ACP mode | Inject via K8s Secret or `.env` (gitignored) |
| Docker | `sandbox` mode only | Not needed for `simulated` mode |
| LaTeX | PDF output only | `texlive-full` recommended |
| RAM | 16 GB minimum | 32 GB+ recommended for full pipeline |
| Disk | 10 GB free | 50 GB+ for large Docker-mode runs |

---

## Quick Start

```bash
# 1. Install the researchclaw skill (if not already installed)
npx skills add OthmanAdi/researchclaw-skill --skill researchclaw -g

# 2. Copy and configure the bridge config
cp multiclaw/research-bridge/config.trading-firm.example.yaml \
   multiclaw/research-bridge/config.trading-firm.yaml
# Edit: set experiment.mode, output.directory, and bridge.* paths

# 3. Validate prerequisites
bash multiclaw/research-bridge/scripts/validate_bridge.sh

# 4. Run a STRATEGY_SCAN (fastest mode — Stage 5 gate only, simulated)
/researchclaw:run "EMA crossover failure modes in high-funding-rate perpetual futures regimes"

# 5. Check job status
/researchclaw:status

# 6. On completion, inspect artifacts
ls logs/research/artifacts/

# 7. Review generated hypotheses before approving for iteration loop
cat logs/research/artifacts/<job-id>/hypotheses.json
```

---

## ResearchMode Reference

```python
class ResearchMode(str, Enum):
    DEEP               = "deep"                # Full 23-stage pipeline, all human gates
    STRATEGY_SCAN      = "strategy_scan"       # Literature + hypothesis only, Stage 5 gate
    PROJECT_AUDIT      = "project_audit"       # Crypto project due diligence, all gates
    COMPETITIVE_BACKTEST = "competitive_backtest"  # Quant comparison, Stage 9 gate
    NIGHTLY_DIGEST     = "nightly_digest"      # Scheduled, simulated, no gates
```

The `ResearchAgent` class (in `research_agent.py`, deployed to `apps/agents/`) exposes:

```python
class ResearchAgent:
    """
    User-directed research agent for the HyperLiquid Trading Firm.
    Composes ResearchClaw topic prompts from internal firm context,
    invokes the 23-stage pipeline, and routes parsed outputs to
    prompts/, apps/jobs/, and the dashboard.

    NEVER called from the live order path.
    All outputs are read-only proposals subject to human review.
    """

    async def run_deep_research(
        self,
        topic: str,
        mode: ResearchMode = ResearchMode.DEEP,
        auto_approve_stages: list[int] | None = None,
    ) -> ResearchJob: ...

    async def get_strategy_evaluation(
        self,
        strategy_class: str,
        current_metrics: StrategyMetrics,
    ) -> HypothesisSet: ...

    async def scan_crypto_project(
        self,
        ticker: str,
        whitepaper_url: str | None = None,
        on_chain_context: dict | None = None,
    ) -> ProjectReport: ...

    async def get_pending_jobs(self) -> list[ResearchJob]: ...

    async def resume_job(self, job_id: str) -> ResearchJob: ...
```

---

## Security & Isolation Invariants

These invariants are non-negotiable and enforced at multiple layers:

1. **No write path to execution files.** `research-bridge` and all AutoResearchClaw artifacts are prohibited from writing to `strategy/`, `agent/`, `apps/executors/`, `.env`, or any K8s Secret file. The `artifact_guard` runtime check and `pre-delete-guard.sh` hook enforce this.

2. **No secrets in research jobs.** The research pipeline must never receive `HL_PRIVATE_KEY`, `VAULT_SUBACCOUNT_ADDRESS`, or any live API token as input. The `context_injector.py` scrubs all env vars before building topic prompts.

3. **Human gate at Stage 5 (literature).** The anti-fabrication guard in AutoResearchClaw v0.3.x is active, but citation quality in crypto topics is variable. The Stage 5 human approval gate is mandatory for all `DEEP` and `PROJECT_AUDIT` mode runs — never bypass with `--auto-approve` in production.

4. **Hypothesis proposals are not strategy changes.** A `HypothesisSet` output from `research-bridge` is a _proposal_, not a committed strategy modification. It must be manually reviewed and explicitly placed in the iteration loop's context path by a human operator before `agent/iteration_loop.py` can read it.

5. **API keys for non-ACP mode are secrets.** If using a dedicated LLM key (`RESEARCH_LLM_KEY`), inject it via K8s Secret or `.env` (gitignored). Never hardcode or log the value.

---

## Risks & Known Limitations

| Risk | Severity | Mitigation |
|---|---|---|
| Stage 10 code generation fails for abstract crypto topics | Medium | Default `simulated` mode avoids code execution; use `sandbox` only for `COMPETITIVE_BACKTEST` |
| arXiv / Semantic Scholar rate limits (429) slow pipeline | Low | Nightly digest jobs run off-peak; ad-hoc jobs retry via `/researchclaw:resume` |
| LLM fabrication in literature synthesis | High | Mandatory Stage 5 human gate; never bypass for production research |
| Research outputs mistaken for authoritative strategy parameters | Critical | All outputs route through `research_registry` as read-only proposals; no direct write path to strategy files |
| Crypto-native sources not natively supported (arXiv/Semantic Scholar/OpenAlex only in v0.3.x) | Medium | Pre-process Messari, DeFiLlama, Token Terminal data in `context_injector.py` before pipeline invocation |
| Docker `sandbox` mode conflicts with K8s pod constraints | Low | Use `simulated` in production pods; run `sandbox` mode on a dedicated research worker node outside the trading cluster |
| Long pipeline runtime (23 stages, up to several hours for DEEP mode) | Low | Run async; `research_registry` tracks progress; dashboard shows `Stage X/23` |

---

## Development & Testing

```bash
# Run unit tests
cd multiclaw/research-bridge
pytest tests/ -v

# Run the full test suite for researchclaw-skill
bash ../researchclaw-skill/tests/test-skill.sh
# Expected: 58/58 tests passing

# Smoke test: validate bridge config and prereqs without running a full pipeline
bash scripts/validate_bridge.sh

# Isolation test: run a simulated STRATEGY_SCAN and verify no artifacts
# land outside logs/research/
pytest tests/test_isolation.py -v
```

**Test coverage target:** 80% on all new modules in `research-bridge/`, consistent with the project-wide standard in `AGENTS.md §7`.

---

## References

- [AutoResearchClaw](https://github.com/aiming-lab/AutoResearchClaw) — upstream 23-stage autonomous research pipeline by aiming-lab
- [researchclaw-skill](https://github.com/OthmanAdi/researchclaw-skill) — skill wrapper adding setup automation, slash-commands, and Claude Code hooks
- [`AGENTS.md`](../../AGENTS.md) — agent scope, file boundaries, coding standards, and security rules for this repository
- [`SPEC.md`](../../SPEC.md) — authoritative architecture specification for the HyperLiquid Trading Firm
- [`apps/agents/`](../../apps/agents/) — the agent-editable Python services tier where `research_agent.py` is deployed
- [`agent/iteration_loop.py`](../../agent/) — Karpathy-style autoresearch loop that consumes approved hypothesis proposals
