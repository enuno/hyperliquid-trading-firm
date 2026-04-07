# `apps/agents` — Agent Overview

> **Package:** `hyperliquid-trading-firm/apps/agents`  
> **Language:** Python 3.11+  
> **Status:** Active development — Phase 1 (Analyst Layer)

This package implements the full multi-agent decision pipeline for the HyperLiquid Autonomous Trading Firm. The architecture is modeled after the [TradingAgents framework](https://github.com/TauricResearch/TradingAgents) (arXiv 2412.20138) and extended with HyperLiquid-specific adapters, pluggable data providers, strategy plugins, and the ATLAS Adaptive-OPRO prompt-optimization layer.

Every agent in this package produces a **typed artifact** (JSON / protobuf). No free-form prompt output ever becomes an executable trade instruction without passing through the downstream Risk Council → Fund Manager → SAE approval chain.

---

## Directory Structure

```
apps/agents/src/
├── agents/                  # All role agents
│   ├── market_analyst.py
│   ├── news_analyst.py
│   ├── fundamental_analyst.py
│   ├── onchain_analyst.py
│   ├── sentiment_analyst.py
│   ├── bullish_researcher.py
│   ├── bearish_researcher.py
│   ├── trader_agent.py
│   ├── risk_agent_aggressive.py
│   ├── risk_agent_neutral.py
│   ├── risk_agent_conservative.py
│   └── fund_manager.py
├── atlas/                   # Prompt optimizer & meta-prompts
│   ├── prompt_optimizer.py
│   └── meta_prompts.py
├── strategies/              # OpenTrader-style strategy plugins
│   ├── base_strategy.py
│   ├── rsi_reversion.py
│   ├── grid_bot.py
│   ├── dca_bot.py
│   └── hyperliquid_perps_meta.py
├── tools/                   # External data connectors
│   ├── intelliclaw_client.py
│   ├── market_data.py
│   ├── news.py
│   ├── onchain.py
│   ├── sentiment.py
│   └── rag.py
├── memory/                  # State and vector stores
│   ├── global_state_store.py
│   └── vector_store.py
├── types/                   # Shared dataclasses and typed contracts
│   ├── intel.py
│   ├── reports.py
│   ├── strategies.py
│   ├── atlas_prompt_optimizer_service.py
│   ├── atlas_window_scorer.py
│   └── prompt-policy.ts
├── config/
└── main.py
```

---

## Decision Pipeline (High-Level)

```
 Market / IntelliClaw / On-chain / News Data
                  │
                  ▼
 ┌──────────────────────────────────────────┐
 │  ANALYST LAYER  (parallel, deep models)  │
 │  Market · News · Fundamental · On-chain  │
 │  Sentiment (pluggable provider)          │
 └────────────────┬─────────────────────────┘
                  │ ResearchPacket (typed)
                  ▼
 ┌──────────────────────────────────────────┐
 │  RESEARCH LAYER                          │
 │  BullishResearcher ↔ BearishResearcher   │
 │  DebateFacilitator  (N rounds)           │
 └────────────────┬─────────────────────────┘
                  │ DebateOutcome (typed)
                  ▼
 ┌──────────────────────────────────────────┐
 │  TRADER AGENT                            │
 │  Consumes ResearchPacket + DebateOutcome │
 │  Emits TradeIntent (typed)               │
 └────────────────┬─────────────────────────┘
                  │
                  ▼
 ┌──────────────────────────────────────────┐
 │  RISK COUNCIL  (3 profiles, parallel)    │
 │  Aggressive · Neutral · Conservative     │
 │  3-way vote → RiskReview (typed)         │
 └────────────────┬─────────────────────────┘
                  │
                  ▼
 ┌──────────────────────────────────────────┐
 │  FUND MANAGER                            │
 │  Portfolio-level constraints → Approval  │
 └────────────────┬─────────────────────────┘
                  │ ExecutionApprovalRequest
                  ▼
            SAE / Execution
```

---

## 1. Analyst Agents

All four primary analysts follow the **ATLAS-style** pattern: they are invoked in parallel each cycle, each producing a narrow, domain-specific `AnalystReport` written into `GlobalAgentState`. Fast/cheap models handle data retrieval and normalization; stronger reasoning models generate the final report.

### 1.1 Market Analyst — `agents/market_analyst.py`

| Field | Detail |
|---|---|
| **Role** | Technical / price-action analyst |
| **Inputs** | OHLCV bars, order-book imbalance, perp-spot premium, liquidation heatmap |
| **Tools** | `tools/market_data.py` |
| **Output** | `AnalystReport` with `score ∈ [-1, 1]`, `confidence`, `keypoints`, `evidence_refs` |
| **Regime signals** | Rolling Sharpe, volatility z-score, trend direction, OI change rate |

The Market Analyst is responsible for identifying the current market regime (TREND_UP / TREND_DOWN / RANGE / HIGH_VOL / EVENT_RISK) and supplying the technical score to `ResearchPacket.regime`.

### 1.2 News Analyst — `agents/news_analyst.py`

| Field | Detail |
|---|---|
| **Role** | Real-time news and macro event analyst |
| **Inputs** | Headline feed (`tools/news.py`), IntelliClaw event stream |
| **Tools** | `tools/news.py`, `tools/intelliclaw_client.py` → `search_events()` |
| **Output** | `AnalystReport`; sets `has_macro_event` flag in `ResearchPacket` |
| **Event types** | Protocol upgrades, exchange listings, regulatory filings, macro calendars, exploit alerts |

The News Analyst classifies events by importance (`low / medium / high / critical`) and applies an **event-blackout** flag that downstream SAE enforces to prevent trading into known macro risk windows.

### 1.3 Fundamental Analyst — `agents/fundamental_analyst.py`

| Field | Detail |
|---|---|
| **Role** | Token fundamentals and on-chain protocol health analyst |
| **Inputs** | Exchange reserves, miner/validator flows, open interest history, funding-rate history, token emission schedules |
| **Tools** | `tools/market_data.py`, custom HL exchange-reserve adapter |
| **Output** | `AnalystReport` with protocol-health score and evidence references |

For HyperLiquid perps, the Fundamental Analyst replaces the equity-oriented tools of the base TradingAgents framework with crypto-native signals: CEX BTC/ETH reserve flows (Glassnode-style), OI across venues, and 7-day funding-rate trend.

### 1.4 On-chain Analyst — `agents/onchain_analyst.py`

| Field | Detail |
|---|---|
| **Role** | Fifth analyst — DeFi / on-chain flow specialist (crypto extension beyond base framework) |
| **Inputs** | Whale wallet transactions, DEX volume vs CEX volume ratio, protocol TVL changes, stablecoin mint/burn flows |
| **Tools** | `tools/onchain.py` |
| **Output** | `AnalystReport` with on-chain flow score; large-flow flag triggers `has_liquidity_warning` in `ResearchPacket` |

This agent is a **crypto-specific addition** not present in the base TradingAgents equities framework. It tracks whale movements, DEX-vs-CEX volume ratios, and stablecoin flows as macro indicators.

---

## 2. Sentiment Analyst

**File:** `agents/sentiment_analyst.py`

```python
class SentimentAnalystAgent:
    def generate_report(self, asset: str):
        intel = get_intel_snapshot(asset)
        # intel.overall_sentiment / headlines → SentimentAnalystReport
```

The Sentiment Analyst uses a **pluggable provider** architecture. The current default provider is **IntelliClaw** (`tools/intelliclaw_client.py`), but the provider can be swapped by replacing the `get_intel_snapshot` dependency.

### IntelliClaw Provider (`tools/intelliclaw_client.py`)

The IntelliClaw HTTP client is the primary sentiment data source. It exposes three call patterns:

| Method | Purpose |
|---|---|
| `get_intel_snapshot(asset, window_hours)` | Single-asset normalized `IntelSnapshot` with TTL cache |
| `search_events(asset, window, limit, importance)` | Historical events: news, protocol changes, exploits |
| `iter_alert_stream(asset, poll_interval)` | SSE/polling stream of live `IntelAlert` objects |
| `get_multi_snapshot(assets)` | Batch snapshot fetch for multi-asset cycles |

**Configuration** is via environment variables:

```
INTELLICLAW_URL        Base URL (required)
INTELLICLAW_API_KEY    Bearer token (optional)
INTELLICLAW_CACHE_TTL  Cache TTL in seconds (default 60)
```

Transient HTTP errors are retried with exponential back-off (max 3 attempts, status codes 429/500/502/503/504). The in-process TTL cache is suitable for single-worker deployments; swap for Redis in multi-worker environments.

**Plugging in alternative sentiment providers:** Replace `tools/sentiment.py` and update `SentimentAnalystAgent` to call your provider's normalized `SentimentSnapshot` interface. The rest of the pipeline only consumes the typed `AnalystReport` output.

---

## 3. Research Layer — Bull/Bear Debate

### 3.1 Bullish Researcher — `agents/bullish_researcher.py`

Receives the completed `ResearchPacket` (all analyst scores) and constructs the strongest possible long thesis. Provides scored claims with evidence references. Participates in N rounds of natural-language debate with the Bearish Researcher.

### 3.2 Bearish Researcher — `agents/bearish_researcher.py`

Mirror of the Bullish Researcher. Constructs the strongest possible short/flat thesis from the same `ResearchPacket`, then rebuts bullish arguments in each debate round.

### 3.3 Debate Facilitator (DebateOrchestrator)

The facilitator runs the debate loop, enforces a hard round limit (default: **2 rounds** for short-horizon perps; **3–5 rounds** for swing/medium strategies), and synthesizes a `DebateOutcome`:

```json
{
  "bull_score": 0.68,
  "bear_score": 0.55,
  "bull_thesis": "...",
  "bear_thesis": "...",
  "consensus_strength": 0.41,
  "open_risks": ["macro event tomorrow", "sentiment deterioration"],
  "facilitator_summary": "...",
  "debate_rounds": 2
}
```

**Key invariant:** If `consensus_strength < config.min_consensus_threshold`, the cycle short-circuits to a `FLAT` `TradeIntent` — the Trader Agent is never invoked. This is a hard no-trade condition.

The debate is the **only** pipeline stage where natural-language dialogue between agents is permitted. All other handoffs use structured typed artifacts.

---

## 4. Trader Agent

**File:** `agents/trader_agent.py`

The Trader Agent synthesizes the full `ResearchPacket` and `DebateOutcome` to emit a `TradeIntent`. It uses a **strong reasoning model** (e.g., Claude Opus / GPT-o3) for final intent formulation.

```json
{
  "action": "LONG | SHORT | FLAT",
  "thesis_strength": 0.64,
  "confidence": 0.58,
  "target_notional_pct": 0.12,
  "preferred_leverage": 2.0,
  "max_slippage_bps": 30,
  "time_horizon": "intraday | swing",
  "required_conditions": ["spread_ok", "vol_ok", "no_data_gap"],
  "rationale": "..."
}
```

The Trader Agent proposes a position and rationale — it does **not** authorize execution. Authorization sits exclusively with the Risk Council → Fund Manager → SAE chain.

**Strategy plugins** (see §6) are available to the Trader as building blocks: it can select and configure a `BaseStrategy` subclass to describe the desired execution pattern (e.g., RSI reversion, grid, DCA), which the Execution layer then validates and stages.

---

## 5. Risk Council (Three-Profile)

Three risk agents evaluate the `TradeIntent` **in parallel**, each applying a distinct profile's constraints.

### Profile Definitions

| Profile | Max Leverage | Max Symbol Notional | Max Drawdown Tolerance |
|---|---|---|---|
| **Aggressive** (`risk_agent_aggressive.py`) | 3.0× | 20% | 15% |
| **Neutral** (`risk_agent_neutral.py`) | 2.0× | 12% | 10% |
| **Conservative** (`risk_agent_conservative.py`) | 1.5× | 8% | 5% |

### Voting Logic

```
3/3 approve  → APPROVE   (effective profile: Aggressive)
2/3 approve  → APPROVE with modification (effective profile: Neutral — capped at median)
1/3 approve  → REDUCE    (effective profile: Conservative)
0/3 approve  → BLOCK
```

The result is a `RiskReview` with `committee_result`, `net_size_cap_pct`, `adjusted_leverage`, and `rationale` from each profile. This feeds directly into the Fund Manager and is also consumed by the SAE hard-policy engine as an upper bound on notional.

---

## 6. Fund Manager

**File:** `agents/fund_manager.py`

The Fund Manager applies **portfolio-level** constraints that individual risk profiles do not see:

- Portfolio concentration limits (total exposure across all open positions)
- Daily PnL drawdown gate
- Correlation-to-book check (new position correlation vs current portfolio ≤ 0.7)
- Treasury conversion trigger (realized BTC PnL → USDC conversion at configured threshold)

Emits an `ExecutionApprovalRequest` → `ExecutionApproval` with final `notional_pct`, `leverage`, and `execution_algo` (TWAP / VWAP / POVICE / ICEBERG / MARKET / LIMIT).

The Fund Manager is the **last LLM-reasoned gate** before the deterministic SAE engine. After approval, no LLM output touches the execution path.

---

## 7. Strategy Plugins (OpenTrader / Freqtrade-style)

Strategy plugins are **`BaseStrategy` subclasses** that the Trader Agent configures and that the Execution layer drives. They follow the OpenTrader interface pattern.

### 7.1 BaseStrategy Interface — `strategies/base_strategy.py`

```python
class BaseStrategy:
    name: str               # Displayed in UI / orchestrator
    description: str
    parameters_schema: dict # JSON-schema-like for UI/autogen

    def on_start(self, ctx) -> None: ...
    def on_stop(self, ctx) -> None: ...
    def on_bar(self, bar, ctx) -> None: ...
    def generate_signals(self, ctx) -> list[dict]:
        # Returns e.g. [{"action": "buy", "size": 0.1, "type": "market"}]
        # SAE / Execution layer validates before routing to venue adapter
        return []
```

### 7.2 Bundled Plugins

| Plugin | File | Strategy Type | Regime Fit |
|---|---|---|---|
| **RSI Reversion** | `rsi_reversion.py` | Mean reversion | Range-bound, low volatility |
| **Grid Bot** | `grid_bot.py` | Market making / grid | Ranging markets, tight spread |
| **DCA Bot** | `dca_bot.py` | Dollar-cost averaging | Long-horizon accumulation |
| **HyperLiquid Perps Meta** | `hyperliquid_perps_meta.py` | Meta-strategy orchestrator | All regimes (delegates to sub-plugins) |

### 7.3 Adding a Custom Plugin

1. Create `strategies/my_strategy.py` inheriting `BaseStrategy`.
2. Set `name`, `description`, and `parameters_schema`.
3. Implement `on_bar()` and `generate_signals()`.
4. Register in `strategies/__init__.py`.
5. The Trader Agent can now select and configure your plugin by name.

All `generate_signals()` outputs are **non-executable raw intents** — the SAE validates and transforms them into staged `ExecutionRequest` objects.

---

## 8. ATLAS Layer — Adaptive-OPRO Prompt Optimizer & RAG

The `atlas/` sub-package implements continuous, **off-hot-path** prompt evolution using an OPRO-style (Optimization by PROmpting) feedback loop. Prompt changes never affect a live cycle in progress; they are promoted explicitly through the governance layer.

### 8.1 AtlasPromptOptimizerService — `types/atlas_prompt_optimizer_service.py`

```python
class AtlasPromptOptimizerService:
    def optimize_role(self, role: AgentRole, window_data: WindowData):
        # 1. Fetch current prompt policy + last 5 history entries
        # 2. Render meta-prompt with current template, history, window score, summary
        # 3. Call deep LLM → parse {"new_prompt": ..., "change_summary": ...}
        # 4. Save new PromptPolicy version (immutable; increments version counter)
        # 5. Append PromptHistoryEntry for full audit trail
```

Each agent role has its own versioned `PromptPolicy`. Versions are **immutable** — a new version is created on every optimization run; old versions are preserved for rollback. Promotion to active requires explicit operator approval (Clawvisor HITL gate).

### 8.2 ATLAS Window Scorer — `types/atlas_window_scorer.py`

Evaluates agent performance over a rolling window of `WINDOW_K = 5` cycles and maps risk-adjusted performance to a `[0, 100]` score used as the feedback signal for OPRO:

```python
def compute_window_score(trades, portfolio_series):
    roi      = (portfolio_series[-1] / portfolio_series[0]) - 1.0
    max_dd   = max_drawdown(portfolio_series)
    sharpe   = rolling_sharpe(portfolio_series)
    # Reward return, penalize excess drawdown and low Sharpe
    raw = roi * 100 - max(0, max_dd - 0.05) * 100 - max(0, 0.5 - sharpe) * 50
    return max(0, min(100, raw + 50))   # clipped to [0, 100]
```

`build_window_summary()` generates the textual summary injected into the meta-prompt:
> *"Window ROI 3.21%, maxDD 1.45%, Sharpe 1.82. 14 trades, mean slippage 4.3 bps."*

### 8.3 Meta-Prompts — `atlas/meta_prompts.py`

Stores the OPRO meta-prompt templates (the prompts that generate improved prompts). Separate templates exist for each agent role. The `render_meta_prompt()` helper interpolates `current_prompt`, `history_text`, `score`, and `window_summary`.

### 8.4 Prompt Optimizer — `atlas/prompt_optimizer.py`

Orchestration entry-point. Invoked by the Jobs service (`apps/jobs`) on a configured schedule (e.g., after every 5 completed cycles or once daily). Iterates over all active agent roles, calls `AtlasPromptOptimizerService.optimize_role()`, and writes results to the `prompt_policies` and `prompt_history` Postgres tables.

### 8.5 RAG Utilities — `tools/rag.py`

Provides retrieval-augmented generation helpers backed by the `memory/vector_store.py` (Milvus / pgvector):

- `embed_and_store(text, metadata)` — persist analyst reports, debate transcripts, and trade outcomes as vector embeddings
- `retrieve_similar(query, k, filters)` — nearest-neighbor retrieval of past decision context
- `build_rag_context(asset, cycle_id)` — assemble a context block from the vector store for injection into analyst prompts

RAG context is injected into analyst prompts to give agents access to relevant historical decisions without unbounded conversation history (avoiding the "telephone effect" degradation).

---

## 9. Memory & State

| Module | Backend | Purpose |
|---|---|---|
| `memory/global_state_store.py` | Redis (short-term, 24h TTL) | In-flight cycle state; shared read/write for all agents in a cycle |
| `memory/vector_store.py` | Milvus / pgvector | Long-term semantic memory; RAG retrieval for analyst context |

Each agent **reads only its required fields** from `GlobalAgentState` and **writes only to its own output field**. No agent reads the full state object. This prevents the telephone-effect degradation documented in the TradingAgents paper.

---

## 10. Types & Contracts

| File | Contents |
|---|---|
| `types/intel.py` | `IntelSnapshot`, `IntelAlert`, `IntelHeadline` — IntelliClaw wire types |
| `types/reports.py` | `AnalystReport`, `ResearchPacket`, `DebateOutcome`, `TradeIntent` |
| `types/strategies.py` | `StrategyConfig`, `SignalIntent`, `BarContext` |
| `types/atlas_prompt_optimizer_service.py` | `AtlasPromptOptimizerService`, `PromptPolicy`, `PromptHistoryEntry` |
| `types/atlas_window_scorer.py` | `WindowData`, `compute_window_score()`, `build_window_summary()` |
| `types/prompt-policy.ts` | TypeScript mirror of `PromptPolicy` for Dashboard consumption |

---

## 11. No-Trade Conditions

The system emits `action: FLAT` and skips execution when any of the following are true:

- `debate_outcome.consensus_strength < config.min_consensus_threshold`
- `risk_review.committee_result == "reject"`
- `execution_approval.approved == false`
- Any `AnalystReport` has `data_gap: true`
- Any `required_condition` in `TradeIntent.required_conditions` is unsatisfied
- HITL gate is open (awaiting human approval) and timeout has not expired
- SAE `ExecutionDecision.allowed == false`

`FLAT` is a first-class output, not a fallback error state.

---

## 12. Model Routing

| Stage | Model Class | Rationale |
|---|---|---|
| Data normalization, ETL | Fast / cheap (GPT-4o-mini, Haiku) | High volume, low reasoning |
| Analyst synthesis | Mid-tier (GPT-4o, Sonnet) | Domain reasoning on structured input |
| Bull/Bear debate rounds | Strong reasoning (o3, Opus) | Adversarial argument quality |
| Trader synthesis | Strong reasoning | Final intent formulation |
| Risk committee | Mid-tier × 3 (parallel) | Profile evaluation |
| Fund manager | Strong reasoning | Portfolio-level constraint enforcement |
| SAE | **Deterministic rule engine** | No LLM — hard policy only |

---

## 13. Development Status

| Phase | Description | Status |
|---|---|---|
| 0 | Scaffolding, contracts, docker-compose | ✅ Complete |
| 1 | Analyst layer — ResearchPacket production | 🔄 In Progress |
| 2 | Debate, Trader, DecisionTrace persistence | ⏳ Planned |
| 3 | Risk Council, Fund Manager, SAE | ⏳ Planned |
| 4 | Paper executor, evaluation harness, MLflow | ⏳ Planned |
| 5 | OpenClaw governance, HITL | ⏳ Planned |
| 6 | Live execution, recovery hardening | ⏳ Planned |

---

## 14. References

- [TradingAgents: Multi-Agents LLM Financial Trading Framework](https://arxiv.org/abs/2412.20138) — Tauric Research
- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) — upstream framework
- [`SPEC.md`](../../SPEC.md) — system-level specification and architecture invariants
- [`DEVELOPMENTPLAN.md`](../../DEVELOPMENTPLAN.md) — phase-by-phase build plan and exit gates
- [`apps/sae-engine`](../sae-engine/) — Safety Approval Engine (deterministic, non-bypassable)
- [`apps/orchestrator-api`](../orchestrator-api/) — cycle coordinator and GlobalAgentState bus
