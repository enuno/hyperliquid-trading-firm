# MEMORY_IMPLEMENTATION.md
# Supermemory.ai — Semantic Memory Subsystem
## hyperliquid-trading-firm

> **Version:** 1.0.0
> **Status:** Design — Pre-implementation
> **Scope:** Semantic memory subsystem only. RAG and document knowledge base integration is covered in `RAG_IMPLEMENTATION.md`.
> **Related specs:** [`SPEC-v2.1.md`](./SPEC-v2.1.md) · [`AGENTS.md`](./AGENTS.md)
> **Service:** [Supermemory.ai Pro](https://supermemory.ai) — hosted cloud memory API
> **MCP Endpoint:** `https://mcp.supermemory.ai/mcp`

---

## 1. Purpose and Scope

This document defines how Supermemory.ai's semantic memory API is used as the **per-agent memory subsystem** for the hyperliquid-trading-firm. It covers:

- Separation of concerns between memory, RAG, and hard trading state
- The `containerTag` namespace schema — one container per agent
- What qualifies as a memory artifact (and what does not)
- MCP configuration, authentication, and agent integration pattern
- Memory lifecycle: write, recall, forget, and context injection
- Failure isolation and degradation policy
- Security and data residency constraints

This document does **not** cover document ingestion, knowledge base search, or OpenClaw autoresearch RAG. Those are covered in `RAG_IMPLEMENTATION.md`.

---

## 2. Service Separation

The trading firm uses three distinct storage layers, each with a clearly bounded responsibility. These layers must not be substituted for one another.

| Layer | Service | Stores | Does NOT store |
|---|---|---|---|
| **Time-series / market data** | TimescaleDB | OHLCV, order book snapshots, funding rates, open interest history | Semantic text, agent memory |
| **Relational / hard state** | PostgreSQL | Positions, PnL, fills, risk state, DecisionTraces, audit log, governance events, treasury events | Time-series ticks, agent memory |
| **Semantic memory** | Supermemory.ai Pro | Trade rationales, regime observations, failure patterns, operator heuristics, persistent agent context | Positions, balances, PnL, execution records, live order state |

This separation is a **hard architectural invariant**. Routing position state or execution records to Supermemory, or routing semantic memory into TimescaleDB, violates this boundary.

---

## 3. Service Architecture Placement

Supermemory's semantic memory layer attaches to the existing agent pipeline as a **context enrichment and learning surface** — entirely off the execution hot path.

```
┌──────────────────────────────────────────────────────────────┐
│                     OpenClaw Control Plane                   │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│                       Orchestrator API                       │
│  (cycle coordinator, typed state store, event bus)           │
└─────────┬────────────────────┬────────────────────┬──────────┘
          │                    │                    │
┌─────────▼──────────┐ ┌──────▼──────┐ ┌──────────▼──────────┐
│    Agents Service  │ │ SAE Engine  │ │    Executors Svc     │
│  (TradingAgents +  │ │ (hard gates,│ │  (HL paper/live,     │
│   adapters)        │ │  no LLM)    │ │   fill reconciler)   │
└─────────┬──────────┘ └─────────────┘ └──────────┬───────────┘
          │                                        │
          │  ← memory enrichment (pre-planning)    │
          │  → memory write (post-trade, off-path) │
          │                                        │
┌─────────▼────────────────────────────────────────────────────┐
│              Supermemory.ai — Semantic Memory Layer           │
│  MCP: https://mcp.supermemory.ai/mcp                         │
│  SDK: pip install supermemory / npm install supermemory       │
│  Scoped by containerTag per agent                            │
└──────────────────────────────────────────────────────────────┘
          │
          │  (never blocking execution path)
          ▼
┌─────────────────────────────────────┐
│  PostgreSQL / TimescaleDB           │
│  (positions, PnL, fills, OHLCV)     │
└─────────────────────────────────────┘
```

Memory reads (recall, context injection) occur **before** the agent planning phase, not during SAE evaluation or execution. Memory writes occur **after** cycle completion, off the hot path, in the reflect/persist phase (step 13 of the decision cycle).

---

## 4. containerTag Namespace Schema

Each agent is assigned exactly one `containerTag`. This namespace is immutable at runtime and must be set in config, not derived dynamically from agent state.

### 4.1 Assigned Namespaces

| Agent / Role | `containerTag` | Entity Context Summary |
|---|---|---|
| Technical Analyst | `analyst_technical` | Technical analysis observations, signal quality notes, indicator failure patterns for HL perp markets |
| Fundamental Analyst | `analyst_fundamental` | Macro regime notes, on-chain structural observations, persistent fundamental views |
| Sentiment Analyst | `analyst_sentiment` | Sentiment model calibration notes, crowding indicators, known noise patterns |
| News Analyst | `analyst_news` | Recurrent news event patterns, source reliability notes, market reaction heuristics |
| On-chain Analyst | `analyst_onchain` | HL vault flow patterns, whale behavior heuristics, liquidation map lessons |
| Bull Researcher | `researcher_bull` | Bull thesis patterns that performed, regimes where bull cases held, recurring bull signal clusters |
| Bear Researcher | `researcher_bear` | Bear thesis patterns that performed, regimes where bear cases held, recurring bear signal clusters |
| Trader Agent | `agent_trader` | Trade decision rationale archive, entry/exit timing lessons, market regime–strategy match notes |
| Risk Engine (all profiles) | `risk_engine` | Risk event patterns, SAE rejection reasons, recurring risk committee objections, operator risk overrides |
| Fund Manager | `agent_fund_manager` | Portfolio-level constraint heuristics, correlation management lessons, treasury-interaction patterns |
| Optimizer Agent | `agent_optimizer` | Off-path performance analysis, prompt-policy improvement patterns, experiment outcome summaries |
| Execution Router | `agent_executor` | Venue quirks, slippage patterns, TWAP/VWAP execution lessons, retry behavior notes |

### 4.2 Shared / Firm-Wide Namespace

One additional container serves cross-agent firm-wide memory that applies to all agents:

| `containerTag` | Purpose |
|---|---|
| `firm_memory` | Operator-approved heuristics, incident postmortems, system-wide behavioral constraints, cross-agent lessons |

Agents may **read** from `firm_memory` but only the Orchestrator API or human operator may **write** to it.

### 4.3 Container Entity Context

Each container must be initialized with a `entityContext` string via the Supermemory container settings API. This improves memory extraction quality by telling the system what kind of information belongs in the namespace.

Example entity context strings:

```python
CONTAINER_ENTITY_CONTEXTS = {
    "agent_trader": (
        "Semantic memory for the HyperLiquid Trading Firm's Trader Agent. "
        "Contains trade decision rationale summaries, market regime-to-strategy match "
        "observations, entry/exit timing lessons, and historical confidence calibration notes. "
        "Does not contain positions, balances, fills, or execution records."
    ),
    "risk_engine": (
        "Semantic memory for the Risk Engine across all three risk profiles "
        "(aggressive, neutral, conservative). Contains recurring risk event patterns, "
        "SAE rejection reason history, unresolved risk objections, operator-approved risk "
        "overrides, and lessons from drawdown events. Does not contain live exposure or PnL."
    ),
    "analyst_technical": (
        "Semantic memory for the Technical Analyst agent operating on HyperLiquid "
        "perpetual futures. Contains indicator quality observations, signal failure patterns "
        "under specific volatility regimes, VWAP/EMA behavior notes, and funding rate "
        "interaction lessons. Does not contain raw price data or OHLCV history."
    ),
    "firm_memory": (
        "Firm-wide semantic memory for the HyperLiquid Trading Firm. Contains "
        "operator-approved behavioral heuristics, incident postmortems, cross-agent "
        "lessons, system-wide constraints, and approved strategy evolution notes. "
        "Write access restricted to human operator via Orchestrator API."
    ),
}
```

---

## 5. What Qualifies as a Memory Artifact

Memory artifacts are **high-signal semantic summaries** — not raw data, not structured records.

### 5.1 Write: Qualifying Content

| Agent | Write-eligible memory content |
|---|---|
| Trader Agent | Post-trade rationale summary: direction taken, regime descriptor, key signals weighted, outcome relative to intent |
| Risk Engine | Recurring objection patterns; situations where a risk profile voted against consensus and was later proven correct; operator override rationale |
| Analyst agents | Calibration notes: which signals fired correctly in which regime; known false-positive patterns; source quality degradation events |
| Fund Manager | Portfolio constraint lessons: when correlation gate blocked a correct trade; treasury conversion timing observations |
| Optimizer Agent | Performance pattern summaries: which prompt-policy versions correlated with improved Sharpe/drawdown across ablation runs |
| Executor | Venue-specific execution lessons: fill latency under high-OI conditions; slippage patterns during funding window resets |

### 5.2 Do NOT Write to Supermemory

The following **must never** be written to Supermemory memory:

- Live or historical positions, balances, fills, or PnL values
- HL private key material, API credentials, vault addresses, or any secret
- Raw market data: OHLCV candles, order book snapshots, tick data
- DecisionTrace JSON blobs (these belong in PostgreSQL)
- Active SAE policy rules (these belong in `config/policies/`)
- Prompt policy templates (these belong in `packages/prompt-policies/`)
- Any personally identifiable information about operators

### 5.3 Memory Artifact Format

Memory artifacts should be written as **concise, self-contained semantic statements** in natural language. Each artifact should be meaningful without requiring additional context from the same session.

**Good examples:**

```
"Under high-funding crowded-long regimes (funding > 0.05%, OI +20% in 24h),
 the momentum strategy produced false breakout signals in 3 of 4 observed cases.
 Reducing net long exposure and tightening leverage to ≤2x was consistently correct."

"The conservative risk profile correctly objected to trades in RANGE regime when
 bull/bear consensus_strength was between 0.5–0.65. These trades had negative
 expected value. The objection threshold should remain active in ranging markets."

"TWAP execution across the funding rate reset window (00:00 UTC) introduced
 significant mark price noise. Prefer limiting TWAP windows to avoid ±15 minutes
 around the 8-hour funding settlement."
```

**Poor examples (do not write):**

```
"BTC was at 95400 and we made a trade."   ← raw numeric state, no semantic value
"Risk rejected."                           ← no context, not useful for recall
"session_id=abc123, cycle=cyc_01JQ..."    ← structured record, belongs in Postgres
```

---

## 6. MCP Configuration

The Supermemory MCP server at `https://mcp.supermemory.ai/mcp` is the primary integration surface for agent-facing memory access. MCP v1 (`supermemory-mcp` standalone repo) is deprecated and must not be used.

### 6.1 Authentication

API keys are injected via Kubernetes Secrets and never hardcoded. One API key is used per deployment environment (paper, live). The key must have read/write access to all agent containers defined in §4.

```json
{
  "mcpServers": {
    "supermemory": {
      "url": "https://mcp.supermemory.ai/mcp",
      "headers": {
        "Authorization": "Bearer ${SUPERMEMORY_API_KEY}"
      }
    }
  }
}
```

In Kubernetes, mount the key as:

```yaml
env:
  - name: SUPERMEMORY_API_KEY
    valueFrom:
      secretKeyRef:
        name: supermemory-credentials
        key: api_key
```

Never log `SUPERMEMORY_API_KEY` at any log level.

### 6.2 MCP Tool Surface

The MCP endpoint exposes three tools. All accept an optional `containerTag` parameter; it must always be explicitly provided — never rely on the server-side default.

| MCP Tool | When to call | `containerTag` |
|---|---|---|
| `memory` (save) | After cycle completion, off hot path, in the reflect/persist step | Agent's own container |
| `recall` | Before planning phase, to surface relevant past context | Agent's own container + optionally `firm_memory` |
| `context` | At conversation/session start, to inject full profile | Agent's own container |

### 6.3 Python SDK Usage Pattern

The Python SDK (`pip install supermemory`) is available as an alternative to MCP for background jobs, batch memory writes, and the optimizer agent's off-path analysis.

```python
import asyncio
from supermemory import AsyncSupermemory
from supermemory.types import AddMemoryParams, SearchMemoriesParams

client = AsyncSupermemory(api_key=os.environ["SUPERMEMORY_API_KEY"])

async def write_trade_memory(container_tag: str, narrative: str) -> None:
    """Write a post-trade semantic narrative to the agent's memory container."""
    await client.add(
        AddMemoryParams(
            content=narrative,
            container_tag=container_tag,
        )
    )

async def recall_agent_context(
    container_tag: str,
    query: str,
    limit: int = 10,
) -> list[str]:
    """Recall semantically relevant memories for a given agent query."""
    results = await client.search.memories(
        SearchMemoriesParams(
            q=query,
            container_tag=container_tag,
            search_mode="memories",
            limit=limit,
        )
    )
    return [r.content for r in results.results]
```

---

## 7. Agent Integration Pattern

Memory operations are **never in the critical execution path**. They are wrappers around the agent's planning and reflection phases.

### 7.1 Pre-Planning: Memory Recall

Before an agent begins its planning phase, it calls `recall` to surface relevant historical context from its container. This is injected into the agent's system prompt as an enrichment block.

```python
async def build_agent_system_prompt(
    base_prompt: str,
    container_tag: str,
    query_context: str,
    timeout_seconds: float = 2.0,
) -> str:
    """
    Enriches an agent's base system prompt with semantically recalled memory.
    Falls back to base prompt only on timeout or Supermemory unavailability.
    """
    try:
        memories = await asyncio.wait_for(
            recall_agent_context(container_tag, query_context, limit=10),
            timeout=timeout_seconds,
        )
        if memories:
            memory_block = "\n".join(f"- {m}" for m in memories)
            return (
                f"{base_prompt}\n\n"
                f"## Relevant Prior Context (Semantic Memory)\n"
                f"{memory_block}\n"
            )
    except (asyncio.TimeoutError, Exception):
        # Supermemory unavailability must NEVER block agent execution
        pass
    return base_prompt
```

### 7.2 Post-Cycle: Memory Write

After cycle completion, each relevant agent writes a concise memory artifact describing what happened and what was learned. This runs in the reflect/persist phase (step 13), fully off the hot path.

```python
async def persist_cycle_memory(
    container_tag: str,
    cycle_id: str,
    narrative: str,
) -> None:
    """
    Persists a post-cycle semantic memory artifact.
    Failures are logged but never raise — memory write failure is non-fatal.
    """
    try:
        await asyncio.wait_for(
            write_trade_memory(container_tag, narrative),
            timeout=5.0,
        )
        logger.info(
            "memory_write_ok",
            container=container_tag,
            cycle_id=cycle_id,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "memory_write_timeout",
            container=container_tag,
            cycle_id=cycle_id,
        )
    except Exception as exc:
        logger.error(
            "memory_write_failed",
            container=container_tag,
            cycle_id=cycle_id,
            error=str(exc),
        )
```

### 7.3 Narrative Generation

Each agent is responsible for generating its own post-cycle narrative. Narratives should be generated by the agent itself (or a lightweight summarizer), not assembled from raw structured data. The trader agent narrative template is:

```python
def build_trader_memory_narrative(
    trade_intent,
    debate_outcome,
    fill_report,
    market_regime: str,
) -> str:
    action = trade_intent.action.name
    confidence = trade_intent.confidence
    rationale = trade_intent.rationale
    consensus = debate_outcome.consensus_strength
    result = fill_report.status if fill_report else "no_fill"
    return (
        f"Cycle outcome: {action} with confidence={confidence:.2f} "
        f"in {market_regime} regime. Consensus strength={consensus:.2f}. "
        f"Result: {result}. Rationale: {rationale}"
    )
```

### 7.4 Firm Memory Write (Operator Only)

Writes to `firm_memory` are restricted. Only the Orchestrator API's `/governance/memory` endpoint may write to this container, and only after human approval via the Clawvisor HITL system. Agent code must not call `client.add()` with `container_tag="firm_memory"` directly.

```python
# PROHIBITED in agent code:
# await client.add(AddMemoryParams(content=..., container_tag="firm_memory"))

# CORRECT: route through Orchestrator API governance endpoint
# POST /governance/memory  {narrative: "...", requires_hitl: true}
```

---

## 8. Memory Lifecycle

### 8.1 Write

Triggered post-cycle in the reflect phase. See §7.2.

- Timeout: 5 seconds
- Failure: log and continue; never raise
- Rate: one write per agent per cycle (maximum)
- Content gate: only write if the cycle produced a meaningful outcome (filled, flat-by-risk, SAE-rejected). Skip on no-trade / stale-data exits.

### 8.2 Recall

Triggered pre-planning. See §7.1.

- Timeout: 2 seconds (strict — agent planning must not be blocked)
- Failure: fall back to base system prompt without memory enrichment
- Limit: 10 memories per recall call
- Frequency: every cycle
- Dual-container pattern: agent's own container + `firm_memory` recall (two async calls, both wrapped with `asyncio.wait_for`)

### 8.3 Context Injection

Triggered at agent session or conversation start (not every cycle). Used to inject the agent's full semantic profile into the session-level system prompt.

- Call: `context` MCP tool or `client.profile()` SDK call
- Expected latency: ~50ms (Supermemory documented)
- Timeout: 3 seconds
- Failure: fall back to base system prompt

### 8.4 Forget

The `memory` MCP tool supports a forget/delete operation. Forgetting is triggered in two cases:

1. **Operator-initiated**: via OpenClaw CLI (`openclaw supermemory forget <query>`) or the `supermemory_forget` tool in the OpenClaw plugin
2. **Automated invalidation**: when a strategy version promotion occurs and prior regime observations for the old strategy become stale, the Orchestrator may batch-delete affected memories

Forget operations against `firm_memory` require HITL approval.

---

## 9. Failure Isolation

Supermemory is a **cloud dependency** on the enrichment path only. Its failure must never propagate to the execution or risk paths.

### 9.1 Invariants

1. No execution path (`SAE`, `Executor`, `FillReconciler`) calls Supermemory at any point
2. All Supermemory calls are wrapped with `asyncio.wait_for` with explicit timeouts
3. All Supermemory call failures are caught, logged, and silently degraded — never raised
4. Agent planning proceeds with base system prompt only when Supermemory is unavailable
5. Memory write failures are logged at `WARNING` level and recorded in the cycle's `DecisionTrace.final_state.halt_flags` as `memory_write_degraded` (non-blocking flag)

### 9.2 Circuit Breaker

A lightweight in-process circuit breaker wraps the Supermemory client for the agents service. After 3 consecutive failures within 60 seconds, the circuit opens and all memory calls return empty results immediately for the next 120 seconds before attempting reset.

```python
# Implemented in apps/agents/memory/circuit_breaker.py
# Tracks: consecutive_failures, last_failure_ts, state: CLOSED | OPEN | HALF_OPEN
```

### 9.3 Observability

Memory operations are instrumented with Prometheus counters and histograms:

| Metric | Type | Labels |
|---|---|---|
| `supermemory_recall_duration_seconds` | Histogram | `container_tag`, `status` |
| `supermemory_write_duration_seconds` | Histogram | `container_tag`, `status` |
| `supermemory_circuit_breaker_state` | Gauge | `state` (0=closed, 1=open) |
| `supermemory_recall_fallback_total` | Counter | `container_tag`, `reason` |

Alert threshold: `supermemory_recall_fallback_total` rate > 20/min triggers `infra.supermemory_degraded` alert (non-critical; does not trigger trading halt).

---

## 10. Security and Data Residency

### 10.1 What Is Transmitted to Supermemory

Only natural-language semantic narratives are transmitted. The following constraints are enforced at the narrative-generation layer before any `client.add()` call:

- No HL private key material, API keys, or wallet addresses
- No raw numeric position sizes, balances, or USD PnL values
- No exchange order IDs, fill IDs, or venue-internal identifiers
- No personally identifiable information about human operators
- No `cycle_id` references (these belong in internal audit logs, not external memory)

### 10.2 API Key Scope

The `SUPERMEMORY_API_KEY` is a **write + read** key scoped to all agent containers. It must be treated as a high-value credential:

- Rotated on any suspected exposure event
- Never logged, printed, or included in error messages
- Mounted via Kubernetes Secret only; never in ConfigMap, environment overlay files, or source code
- Stored in the project's secrets manager (Bitwarden or equivalent); never in `.env` files committed to git

### 10.3 Data Residency Assumption

Supermemory.ai is a hosted cloud service. All memory artifacts are stored on Supermemory's infrastructure. Before enabling live-mode memory writes containing any production trading firm semantic data, the operator must:

1. Review Supermemory's current data processing agreement and privacy policy
2. Confirm data isolation guarantees for Pro-tier containerTag namespaces
3. Confirm encryption-at-rest and in-transit standards meet operational requirements
4. Document the data residency decision in the firm's security runbook

Until this review is complete, restrict Supermemory writes to paper-mode and research contexts only.

---

## 11. Validation Plan

Before enabling Supermemory memory writes in live mode, execute the following tests:

### Phase 1 — Namespace Isolation (paper environment)

1. Create `agent_trader` and `risk_engine` containers with entity context strings
2. Write 10 synthetic trade narratives to `agent_trader`
3. Write 10 synthetic risk event narratives to `risk_engine`
4. Query each container and confirm zero cross-container leakage
5. Query `agent_trader` with a risk-specific query — confirm no risk memories are returned

### Phase 2 — Recall Quality

1. Ingest 50 synthetic trade narratives spanning five market regimes into `agent_trader`
2. Query with regime-specific prompts (e.g., "high funding crowded long") and validate that the top-5 recalled memories are semantically relevant to the query
3. Measure recall latency p50/p95 from the paper environment's cloud region
4. Confirm latency p95 < 1.5 seconds (required for 2-second timeout budget)

### Phase 3 — Failure Isolation

1. Simulate Supermemory API unavailability (block DNS or revoke key temporarily)
2. Trigger 5 paper cycles and confirm all complete successfully with base system prompt
3. Confirm `supermemory_recall_fallback_total` metric increments correctly
4. Confirm no cycle is blocked, delayed, or produces a different error type

### Phase 4 — Memory Write Integration

1. Run 20 paper cycles with memory write enabled
2. Review generated narratives for content quality and policy compliance (no secrets, no raw data)
3. Query each container and confirm narratives are retrievable with semantically appropriate queries
4. Review `supermemory_write_duration_seconds` histogram for latency profile

### Acceptance Criteria

| Test | Pass condition |
|---|---|
| Namespace isolation | Zero cross-container leakage in 100 queries |
| Recall latency | p95 < 1.5s from production region |
| Failure isolation | All cycles complete under simulated outage |
| Content policy | Zero narratives contain secrets, raw numeric state, or cycle IDs |
| Write latency | p95 < 4.0s for post-cycle writes |

---

## 12. File Layout

```
apps/agents/
  memory/
    client.py              # Supermemory SDK client wrapper (singleton, configured from env)
    circuit_breaker.py     # In-process circuit breaker for Supermemory calls
    containers.py          # Container tag constants and entity context definitions
    recall.py              # Pre-planning recall helper: build_agent_system_prompt()
    write.py               # Post-cycle write helper: persist_cycle_memory()
    narratives/
      trader.py            # build_trader_memory_narrative()
      risk.py              # build_risk_memory_narrative()
      analyst.py           # build_analyst_memory_narrative()
      executor.py          # build_executor_memory_narrative()
      optimizer.py         # build_optimizer_memory_narrative()

config/
  memory/
    containers.yaml        # Entity context strings per containerTag (non-secret)

infra/k8s/
  secrets/
    supermemory-credentials.yaml  # K8s Secret template (values injected at deploy time)

tests/
  unit/
    memory/
      test_circuit_breaker.py
      test_recall_fallback.py
      test_narrative_content_policy.py
  integration/
    memory/
      test_namespace_isolation.py
      test_recall_latency.py
      test_failure_isolation.py
```

---

## 13. Open Questions

| Question | Owner | Resolution path |
|---|---|---|
| Data residency review: does Supermemory Pro meet operational security requirements for production trading firm data? | Human operator | Review DPA and privacy policy before live-mode enablement |
| Should `firm_memory` writes require Supermemory Pro team-level isolation, or is container-tag scoping sufficient? | Architecture | Review Supermemory Pro container isolation docs |
| What is the right cadence for memory compaction / pruning of low-quality or stale memories? | Engineering | Implement automated quality scoring and TTL after Phase 2 validation |
| Should the optimizer agent's memory container be read by other agents, or kept fully isolated for off-path analysis only? | Architecture | Decide before optimizer agent is activated in live mode |

---

*Supermemory.ai service: [supermemory.ai](https://supermemory.ai) · Docs: [supermemory.ai/docs](https://supermemory.ai/docs) · MCP endpoint: `https://mcp.supermemory.ai/mcp`*
