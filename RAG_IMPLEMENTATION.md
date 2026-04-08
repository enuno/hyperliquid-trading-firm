# RAG_IMPLEMENTATION.md
# Supermemory.ai — RAG & Knowledge Base Subsystem
## hyperliquid-trading-firm

> **Version:** 1.0.0
> **Status:** Design — Pre-implementation
> **Scope:** RAG, document ingestion, semantic search, and knowledge base. Agent working memory is covered in [`MEMORY_IMPLEMENTATION.md`](./MEMORY_IMPLEMENTATION.md).
> **Related specs:** [`SPEC-v2.1.md`](./SPEC-v2.1.md) · [`AGENTS.md`](./AGENTS.md) · [`MEMORY_IMPLEMENTATION.md`](./MEMORY_IMPLEMENTATION.md)
> **Service:** [Supermemory.ai Pro](https://supermemory.ai) — hosted managed RAG platform
> **MCP Endpoint:** `https://mcp.supermemory.ai/mcp`
> **Plugin:** OpenClaw Supermemory Skill (`supermemoryai/openclaw-supermemory`)

---

## 1. Purpose and Scope

This document defines how the Supermemory.ai managed RAG platform is used as the **knowledge base and semantic search layer** for the hyperliquid-trading-firm. It covers:

- The architectural distinction between RAG (this document) and agent memory ([`MEMORY_IMPLEMENTATION.md`](./MEMORY_IMPLEMENTATION.md))
- Document ingestion pipelines: what gets indexed and when
- The `containerTag` namespace schema for knowledge collections
- OpenClaw `autoResearch` integration: how agents trigger RAG searches autonomously
- Direct SDK and MCP-based search patterns used outside of OpenClaw
- The four AI tools exposed by the OpenClaw Supermemory skill
- Chunking, metadata filtering, and hybrid search configuration
- Failure isolation, circuit breaking, and degradation policy
- Security constraints on what content may be indexed
- Validation plan before enabling live-mode document ingestion

This document does **not** cover per-agent working memory, temporal fact evolution, user profiles, or the memory write/recall lifecycle. Those are covered in `MEMORY_IMPLEMENTATION.md`.

---

## 2. Memory vs. RAG: Architectural Distinction

Supermemory provides both a Memory API and a RAG API that share the same underlying context pool per `containerTag`. These are distinct surfaces with different semantics, and the trading firm uses them for different purposes.

| Dimension | Memory (MEMORY_IMPLEMENTATION.md) | RAG (this document) |
|---|---|---|
| **What it stores** | Extracted semantic facts about agent behavior and outcomes | Full document content: PDFs, research notes, strategy docs, runbooks, backtesting reports |
| **How it's written** | Agent narratives written post-cycle programmatically | Ingestion pipeline pushes documents via API |
| **How it's queried** | `search_mode: "memories"` — returns extracted facts | `search_mode: "chunks"` — returns raw document passages |
| **Temporal behavior** | Facts evolve; contradictions are auto-resolved; temporal changes are tracked | Source-of-truth documents; updated by re-ingestion; versioned by metadata |
| **Who queries it** | Individual agents, enriching system prompt pre-planning | All agents, operators, OpenClaw `autoResearch`, jobs service |
| **Primary use** | "What did this agent learn from past cycles?" | "What does the firm know about this topic?" |
| **OpenClaw integration** | Manual `store`/`recall` calls | Automatic `autoResearch` hook on every turn |

Both surfaces share the same `containerTag` namespace and the same Supermemory Pro API key. A query against a container will return results from both memory artifacts and indexed documents unless `search_mode` is explicitly specified. Where isolation between memory and document results is required, specify `search_mode` explicitly on every search call.

---

## 3. Service Architecture Placement

The RAG subsystem is a **knowledge enrichment surface** used by multiple consumers across the system. Unlike agent memory (pre-planning, per-agent), RAG is queried by agents, background jobs, the optimizer, and through OpenClaw `autoResearch` autonomously.

```
┌──────────────────────────────────────────────────────────────────────┐
│                       OpenClaw Control Plane                         │
│  (autoResearch hook, skill management, operator knowledge queries)   │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ autoResearch (per turn)
┌──────────────────────────────▼───────────────────────────────────────┐
│                         Agents Service                               │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────────┐   │
│  │ Analyst Agents │  │  Debate Agents │  │ Risk / Fund Manager  │   │
│  │ (5 specialists)│  │ (bull / bear)  │  │ Agents               │   │
│  └───────┬────────┘  └───────┬────────┘  └──────────┬───────────┘   │
│          │                   │                       │               │
│          └───────────────────┴───────────────────────┘               │
│                               │ search (pre-planning)                │
└──────────────────────────────┬┴──────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│               Supermemory.ai — Managed RAG Platform                  │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  Knowledge Collections (containerTag-scoped)                │     │
│  │                                                             │     │
│  │  kb_strategy  │  kb_research  │  kb_hl_protocol  │         │     │
│  │  kb_risk      │  kb_backtests │  kb_runbooks     │         │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                                                                      │
│  Ingestion ← Ingestion Pipeline (PDF, MD, TXT, code, web)           │
│  Search   → Hybrid semantic search + metadata filtering              │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────────┐
          │                    │                         │
┌─────────▼──────┐  ┌─────────▼──────────┐  ┌──────────▼──────────────┐
│  Jobs Service  │  │  Optimizer Agent   │  │  Orchestrator API        │
│  (backtests,   │  │  (off-path perf.   │  │  (governance, operator   │
│   ablations,   │  │   improvement)     │  │   knowledge queries)     │
│   eval runs)   │  └────────────────────┘  └─────────────────────────┘
└────────────────┘
```

**Key principle:** The RAG layer is never in the execution hot path. No SAE, Executor, FillReconciler, or Treasury Manager service calls the RAG API. All RAG queries are pre-planning enrichment or off-path analysis.

---

## 4. Knowledge Collection Schema

Each knowledge collection is a Supermemory `containerTag` dedicated to a distinct type of document corpus. Collections are separate from the agent memory containers defined in `MEMORY_IMPLEMENTATION.md`.

### 4.1 Collection Registry

| `containerTag` | Content Type | Primary Consumers | Update Cadence |
|---|---|---|---|
| `kb_strategy` | Strategy design documents, `trading_program.md`, `STRATEGY.md`, strategy plugin specs, historical prompt-policy rationale | All agents, operator | On strategy version promotion |
| `kb_research` | External research papers, market structure studies, IntelliClaw report archives, on-chain analytics reports | Analyst agents, debate agents, optimizer | As new research is reviewed and approved |
| `kb_hl_protocol` | HyperLiquid API docs, protocol changelog, perpetuals mechanics, funding rate formulas, margin/liquidation rules | Technical analyst, executor, fund manager | On HL protocol upgrades |
| `kb_risk` | Risk policy documents, SAE policy YAML files (human-readable), drawdown event postmortems, approved risk framework papers | Risk agents, fund manager, SAE (read-only enrichment) | On policy changes; immediately after postmortems |
| `kb_backtests` | Backtest reports (Markdown/PDF), ablation study summaries, walk-forward validation results, prompt-policy scoring reports | Optimizer agent, jobs service, fund manager | After each backtest or ablation run completes |
| `kb_runbooks` | Operational runbooks, incident response procedures, deployment guides, escalation matrices | Operator (via OpenClaw), Orchestrator API | On ops procedure changes |
| `kb_external` | Curated external market commentary, academic crypto research, DeFi structural analysis | News analyst, sentiment analyst | Operator-curated; weekly cadence |

### 4.2 Collection Entity Context Strings

Each collection should be initialized with an `entityContext` string to improve chunking and retrieval quality:

```python
COLLECTION_ENTITY_CONTEXTS = {
    "kb_strategy": (
        "Strategy documentation for the HyperLiquid Trading Firm — a multi-agent LLM-based "
        "perpetuals trading system. Contains strategy design specs, trading program intent documents, "
        "prompt-policy versioning rationale, and strategic direction documents. "
        "All documents describe algorithmic trading strategies for HyperLiquid perpetual futures."
    ),
    "kb_hl_protocol": (
        "HyperLiquid protocol and API documentation. Contains REST and WebSocket API references, "
        "perpetuals market mechanics, funding rate calculation formulas, margin and liquidation rules, "
        "order types, vault mechanics, and protocol changelog entries."
    ),
    "kb_backtests": (
        "Backtesting, ablation, and validation reports for the HyperLiquid Trading Firm's "
        "multi-agent trading system. Contains walk-forward results, Sharpe/Sortino/Calmar metrics, "
        "drawdown analysis, strategy regime segmentation studies, and prompt-policy scoring summaries."
    ),
    "kb_risk": (
        "Risk management framework documentation for the HyperLiquid Trading Firm. Contains "
        "SAE policy specifications, drawdown event postmortems, approved risk constraint rationale, "
        "cross-agent risk committee guidelines, and operator-approved risk override records."
    ),
}
```

---

## 5. Ingestion Pipeline

### 5.1 Document Types and Sources

Supermemory's managed RAG platform handles ingestion of text, PDF, images, code, and Markdown files. The ingestion pipeline for this repo uses the Python SDK with explicit `containerTag` routing.

| Document source | Target collection | Ingestion trigger | Format |
|---|---|---|---|
| `STRATEGY.md`, `trading_program.md` | `kb_strategy` | Git commit to main (via CI job) | Markdown |
| `packages/prompt-policies/**` (version notes) | `kb_strategy` | On strategy version promotion | Markdown |
| `config/policies/*.yaml` (human-readable) | `kb_risk` | On policy file change | YAML/text |
| Backtest report output (`jobs/backtest_runner.py`) | `kb_backtests` | Post-run, automated | Markdown/PDF |
| Ablation study summary (`jobs/ablation_runner.py`) | `kb_backtests` | Post-run, automated | Markdown |
| HL API docs (official) | `kb_hl_protocol` | Manual operator import; on HL protocol releases | Markdown/HTML |
| External research (operator-approved) | `kb_research` | Manual operator import | PDF/Markdown |
| Incident postmortems | `kb_risk` | Manual operator import after incident review | Markdown |
| Operational runbooks (`docs/runbooks/**`) | `kb_runbooks` | Git commit to main (via CI job) | Markdown |

### 5.2 Python SDK Ingestion Pattern

```python
import asyncio
import os
from pathlib import Path
from supermemory import AsyncSupermemory
from supermemory.types import AddDocumentParams

client = AsyncSupermemory(api_key=os.environ["SUPERMEMORY_API_KEY"])

async def ingest_document(
    content: str,
    container_tag: str,
    source_path: str,
    doc_type: str,
    version: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """
    Ingest a document into the specified knowledge collection.
    Returns the Supermemory document ID for reference tracking.
    """
    metadata = {
        "source_path": source_path,
        "doc_type": doc_type,
        "ingested_at": __import__("datetime").datetime.utcnow().isoformat(),
    }
    if version:
        metadata["version"] = version
    if tags:
        metadata["tags"] = tags

    result = await client.add(
        AddDocumentParams(
            content=content,
            container_tag=container_tag,
            metadata=metadata,
        )
    )
    return result.id


async def ingest_file(
    file_path: Path,
    container_tag: str,
    doc_type: str,
    **kwargs,
) -> str:
    """Convenience wrapper for file-based ingestion."""
    content = file_path.read_text(encoding="utf-8")
    return await ingest_document(
        content=content,
        container_tag=container_tag,
        source_path=str(file_path),
        doc_type=doc_type,
        **kwargs,
    )
```

### 5.3 CI-Triggered Ingestion Job

Documents in the repo that belong in a knowledge collection are automatically re-ingested on commit to `main`. The ingestion job runs as a Kubernetes Job, not as a long-running service.

```python
# apps/jobs/rag_ingest.py
# Triggered by: CI pipeline on commit to main branch
# Environment: paper / live (same knowledge base for both)

INGEST_MANIFEST = [
    {
        "paths": ["STRATEGY.md", "trading_program.md"],
        "container_tag": "kb_strategy",
        "doc_type": "strategy_doc",
        "tags": ["core_strategy"],
    },
    {
        "paths": ["docs/runbooks/*.md"],
        "container_tag": "kb_runbooks",
        "doc_type": "runbook",
        "tags": ["operations"],
    },
    {
        "paths": ["config/policies/*.yaml"],
        "container_tag": "kb_risk",
        "doc_type": "sae_policy",
        "tags": ["risk", "policy"],
    },
]
```

### 5.4 Post-Run Automated Ingestion

After each backtest, ablation, or prompt-policy scoring run, the jobs service automatically ingests the report into `kb_backtests`:

```python
# apps/jobs/backtest_runner.py — post-run hook (simplified)

async def on_backtest_complete(report_path: Path, run_metadata: dict) -> None:
    await ingest_file(
        file_path=report_path,
        container_tag="kb_backtests",
        doc_type="backtest_report",
        version=run_metadata.get("strategy_version"),
        tags=[
            run_metadata.get("strategy_name"),
            run_metadata.get("regime"),
            f"sharpe_{run_metadata.get('sharpe_ratio', 0):.2f}",
        ],
    )
```

---

## 6. OpenClaw autoResearch Integration

### 6.1 What autoResearch Does

The OpenClaw Supermemory skill's `autoResearch` feature intercepts every agent turn and, before the LLM generates a response, performs a semantic search across the agent's configured knowledge collections. The top results are injected into the context window automatically — no explicit tool call from the agent is required.

This is the **primary RAG surface** for all analyst agents, debate agents, and the fund manager. These agents benefit from continuously enriched context without requiring manual search logic in their prompt templates.

### 6.2 OpenClaw Skill Configuration

The Supermemory skill is configured via the OpenClaw `skills` configuration, which maps to the `supermemoryai/openclaw-supermemory` plugin. Each agent type receives its own skill configuration specifying which collections to search and whether `autoResearch` is active.

```yaml
# config/openclaw/supermemory-skill.yaml
# OpenClaw Supermemory skill configuration per agent role

skill: supermemory
version: "latest"
apiKey: "${SUPERMEMORY_API_KEY}"

agents:
  analyst_technical:
    autoResearch: true
    autoResearchLimit: 8
    containers:
      - kb_strategy
      - kb_hl_protocol
      - kb_backtests
    autoCapture: false           # Technical analyst does not auto-capture; writes via SDK post-cycle

  analyst_fundamental:
    autoResearch: true
    autoResearchLimit: 8
    containers:
      - kb_strategy
      - kb_research
      - kb_hl_protocol
    autoCapture: false

  analyst_sentiment:
    autoResearch: true
    autoResearchLimit: 6
    containers:
      - kb_research
      - kb_external
    autoCapture: false

  analyst_news:
    autoResearch: true
    autoResearchLimit: 6
    containers:
      - kb_research
      - kb_external
    autoCapture: false

  analyst_onchain:
    autoResearch: true
    autoResearchLimit: 8
    containers:
      - kb_hl_protocol
      - kb_research
    autoCapture: false

  researcher_bull:
    autoResearch: true
    autoResearchLimit: 10
    containers:
      - kb_strategy
      - kb_research
      - kb_backtests
    autoCapture: false

  researcher_bear:
    autoResearch: true
    autoResearchLimit: 10
    containers:
      - kb_strategy
      - kb_research
      - kb_backtests
    autoCapture: false

  agent_trader:
    autoResearch: true
    autoResearchLimit: 6
    containers:
      - kb_strategy
    autoCapture: false

  risk_engine:
    autoResearch: true
    autoResearchLimit: 6
    containers:
      - kb_risk
      - kb_strategy
    autoCapture: false

  agent_fund_manager:
    autoResearch: true
    autoResearchLimit: 8
    containers:
      - kb_strategy
      - kb_risk
      - kb_backtests
    autoCapture: false

  agent_optimizer:
    autoResearch: true
    autoResearchLimit: 15
    containers:
      - kb_strategy
      - kb_backtests
      - kb_research
    autoCapture: false

  agent_executor:
    autoResearch: true
    autoResearchLimit: 5
    containers:
      - kb_hl_protocol
    autoCapture: false
```

### 6.3 autoCapture Policy

`autoCapture` is **disabled for all agents** in the RAG context. Knowledge collections are populated exclusively through the ingestion pipeline (§5), not by capturing agent conversation output. This prevents:

- Unreviewed agent-generated content polluting the knowledge base
- Circular contamination where an agent's inference is later retrieved as ground truth
- Gradual semantic drift of the knowledge collections away from authoritative sources

The only exception is the `agent_optimizer`, which may be granted `autoCapture: true` in a future operator-approved configuration change, subject to a human review gate before any captured content enters the knowledge base.

### 6.4 The Four AI Tools

The OpenClaw Supermemory skill exposes four tools to agents. In the context of the trading firm's RAG usage, these tools are used as follows:

| Tool | Description | Trading firm usage |
|---|---|---|
| `supermemory_store` | Manually store content into a container | Restricted — only for operator-initiated knowledge base updates via OpenClaw CLI |
| `supermemory_search` | Explicit semantic search against a container | Used by analyst agents when the auto-injected context is insufficient; e.g., a deep dive on HL funding mechanics |
| `supermemory_forget` | Delete a document or memory by query | Used by operator to remove stale or incorrect documents; never called by agents autonomously |
| `supermemory_profile` | Retrieve the full entity profile/context summary | Used by the optimizer agent at session start to get a consolidated view of the firm's knowledge state |

### 6.5 Explicit Search: When Agents Call supermemory_search Directly

Beyond `autoResearch`, agents may issue explicit `supermemory_search` calls when their planning phase requires deep retrieval on a specific question. This is not the default — it is reserved for high-value targeted lookups.

Permitted explicit search patterns:

```
# Technical Analyst — deep query on HL protocol mechanics
supermemory_search(
    q="HyperLiquid funding rate settlement timing and mark price impact",
    container_tag="kb_hl_protocol",
    limit=5,
)

# Bear Researcher — querying relevant backtest failure modes
supermemory_search(
    q="strategy underperformance in high funding crowded long regime",
    container_tag="kb_backtests",
    limit=8,
    metadata_filter={"doc_type": "backtest_report"}
)

# Fund Manager — querying risk framework for correlation constraint rationale
supermemory_search(
    q="cross-asset correlation gate portfolio concentration risk",
    container_tag="kb_risk",
    limit=5,
)
```

---

## 7. Direct SDK Search Pattern

For consumers outside of OpenClaw (jobs service, optimizer agent's off-path analysis, Orchestrator API governance queries), the Python SDK provides direct search access.

### 7.1 Semantic Search

```python
from supermemory import AsyncSupermemory
from supermemory.types import SearchDocumentsParams

async def search_knowledge_base(
    query: str,
    container_tag: str,
    limit: int = 10,
    metadata_filter: dict | None = None,
    timeout_seconds: float = 3.0,
) -> list[dict]:
    """
    Semantic search against a knowledge collection.
    Returns a list of passages with content and metadata.
    Falls back to empty list on timeout or service unavailability.
    """
    try:
        params = SearchDocumentsParams(
            q=query,
            container_tag=container_tag,
            search_mode="chunks",
            limit=limit,
        )
        if metadata_filter:
            params.metadata_filter = metadata_filter

        results = await asyncio.wait_for(
            client.search.documents(params),
            timeout=timeout_seconds,
        )
        return [
            {"content": r.content, "metadata": r.metadata, "score": r.score}
            for r in results.results
        ]
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning(
            "rag_search_failed",
            container=container_tag,
            query=query[:100],
            error=str(exc),
        )
        return []
```

### 7.2 Metadata Filtering

Supermemory supports metadata filtering to narrow retrieval to specific document subsets. The trading firm uses standard metadata fields across all ingested documents to enable precise filtering:

| Metadata field | Values | Filter use case |
|---|---|---|
| `doc_type` | `strategy_doc`, `backtest_report`, `ablation_report`, `sae_policy`, `runbook`, `research_paper`, `protocol_doc` | Retrieve only backtest reports, or only policy docs |
| `version` | semver string (e.g., `"2.1.0"`) | Retrieve knowledge specific to a strategy version |
| `tags` | list of strings | Filter by regime, strategy name, or topic |
| `ingested_at` | ISO 8601 timestamp | Retrieve only recently ingested documents |

Example: retrieving only backtest reports for a specific strategy version:

```python
results = await search_knowledge_base(
    query="momentum strategy performance metrics high volatility regime",
    container_tag="kb_backtests",
    limit=10,
    metadata_filter={
        "doc_type": "backtest_report",
        "version": "2.1.0",
    },
)
```

### 7.3 Hybrid Search Mode

Supermemory supports a hybrid search mode combining dense semantic embeddings with sparse keyword matching. For the trading firm, hybrid mode is preferred for queries containing specific numeric identifiers, ticker symbols, or technical terms that benefit from exact-match scoring:

```python
# Hybrid search for exact protocol term matching
params = SearchDocumentsParams(
    q="PERP_FUNDING_RATE 8h settlement formula",
    container_tag="kb_hl_protocol",
    search_mode="hybrid",    # dense + sparse
    limit=5,
)
```

Use `search_mode="chunks"` (pure semantic) for conceptual research queries. Use `search_mode="hybrid"` for queries containing specific identifiers, formulas, or parameter names.

---

## 8. Cross-Container Query Pattern

Some agent roles benefit from querying multiple knowledge collections in a single planning step. Rather than issuing sequential queries, the trading firm uses parallel async queries across containers, merging and re-ranking results by score.

```python
async def multi_container_search(
    query: str,
    container_tags: list[str],
    limit_per_container: int = 5,
    timeout_seconds: float = 3.0,
) -> list[dict]:
    """
    Query multiple knowledge collections in parallel.
    Returns a merged, score-sorted list of passages.
    Partial failures return results from available containers only.
    """
    tasks = [
        search_knowledge_base(
            query=query,
            container_tag=tag,
            limit=limit_per_container,
            timeout_seconds=timeout_seconds,
        )
        for tag in container_tags
    ]
    results_per_container = await asyncio.gather(*tasks, return_exceptions=True)

    merged = []
    for tag, results in zip(container_tags, results_per_container):
        if isinstance(results, Exception):
            logger.warning("rag_container_unavailable", container=tag)
            continue
        for r in results:
            r["source_container"] = tag
            merged.append(r)

    merged.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return merged[:limit_per_container * 2]  # cap total returned passages
```

The bull/bear researcher agents and the fund manager use this pattern to query `kb_strategy`, `kb_research`, and `kb_backtests` in a single pre-planning step.

---

## 9. RAG Context Injection into Agent System Prompts

For agents that use direct SDK access (rather than OpenClaw `autoResearch`), retrieved passages are injected into the agent's system prompt using a structured block format that keeps RAG context visually separated from the base prompt and agent working memory.

```python
def build_rag_enriched_system_prompt(
    base_prompt: str,
    rag_passages: list[dict],
    section_title: str = "Relevant Knowledge Base Context",
) -> str:
    """
    Injects RAG search results into the agent system prompt as a
    clearly delimited context block.
    """
    if not rag_passages:
        return base_prompt

    passages_text = "\n\n".join(
        f"[{p.get('source_container', 'kb')} | score={p.get('score', 0.0):.2f}]\n{p['content']}"
        for p in rag_passages[:10]
    )
    return (
        f"{base_prompt}\n\n"
        f"---\n"
        f"## {section_title}\n"
        f"{passages_text}\n"
        f"---\n"
    )
```

**Context injection ordering convention** (from outermost to innermost in the system prompt):

1. Base system prompt (role definition, strategy context, current market snapshot)
2. Agent working memory enrichment block (from `MEMORY_IMPLEMENTATION.md` §7.1)
3. RAG knowledge base context block (this document §9)
4. Current cycle artifacts (ResearchPacket, DebateOutcome, etc. — from Orchestrator typed state)

RAG context is always placed inside working memory enrichment, which is placed inside the base prompt. This ordering ensures that the model treats firm-level knowledge as background context and per-agent learned behavior as closer context.

---

## 10. Document Update and Re-ingestion

### 10.1 Re-ingestion Policy

When a source document is updated, it must be re-ingested rather than appended to. The old document version should be deleted by source path before the new version is added. This prevents duplicate or contradictory passages in the knowledge base.

```python
async def reingest_document(
    content: str,
    container_tag: str,
    source_path: str,
    doc_type: str,
    version: str | None = None,
) -> str:
    """
    Delete existing document by source_path and ingest the new version.
    Used for strategy doc updates, policy file changes, runbook revisions.
    """
    # Delete existing document(s) matching this source path
    existing = await search_knowledge_base(
        query=source_path,
        container_tag=container_tag,
        limit=5,
        metadata_filter={"source_path": source_path},
    )
    for doc in existing:
        if doc.get("metadata", {}).get("source_path") == source_path:
            await client.documents.delete(doc["id"])

    # Ingest the new version
    return await ingest_document(
        content=content,
        container_tag=container_tag,
        source_path=source_path,
        doc_type=doc_type,
        version=version,
    )
```

### 10.2 Strategy Version Promotion Gate

When a new strategy version is promoted (via the `packages/prompt-policies/` promotion workflow), the following RAG operations are triggered automatically by the CI promotion job:

1. Re-ingest updated `STRATEGY.md` and version notes into `kb_strategy`
2. Re-ingest updated policy YAML files into `kb_risk`
3. Tag the new documents with the new version string
4. Issue a `supermemory_forget` call to remove any documents tagged with the prior version that are now superseded

This ensures that agents querying `kb_strategy` during the new version's cycles retrieve current, not stale, strategic context.

### 10.3 Stale Document TTL

The following collections have operator-configured stale document TTL policies:

| Collection | Suggested TTL | Rationale |
|---|---|---|
| `kb_external` | 90 days | External market commentary ages quickly; old views can mislead |
| `kb_backtests` | None (permanent) | Backtest history is valuable for longitudinal analysis |
| `kb_strategy` | None (versioned replacement) | Managed via re-ingestion on version promotion |
| `kb_hl_protocol` | None (manual re-ingestion on protocol changes) | Protocol docs should reflect current spec; manual control preferred |
| `kb_runbooks` | None (permanent) | Operational history is valuable |

TTL enforcement is handled by a periodic cleanup job (`apps/jobs/rag_cleanup.py`) that queries for documents older than the configured TTL and deletes them via the Supermemory API.

---

## 11. Operator Knowledge Queries

Beyond automated agent enrichment, the RAG layer is the primary knowledge surface for human operators working in the OpenClaw control plane. Operators can query any collection directly via the OpenClaw CLI using the `supermemory_search` tool:

```bash
# Query strategy collection for a specific topic
openclaw supermemory search \
  --container kb_strategy \
  --query "momentum strategy regime filtering logic" \
  --limit 5

# Query backtest collection for recent performance data
openclaw supermemory search \
  --container kb_backtests \
  --query "drawdown performance Q1 2026" \
  --metadata-filter '{"doc_type": "backtest_report"}' \
  --limit 10

# Query risk collection for SAE policy rationale
openclaw supermemory search \
  --container kb_risk \
  --query "leverage cap 3x rationale drawdown event" \
  --limit 5
```

The Orchestrator API also exposes a `/knowledge/search` endpoint that proxies queries to the Supermemory SDK, enabling dashboard-level knowledge base browsing for operators without direct CLI access.

---

## 12. Failure Isolation

### 12.1 Invariants

1. No service in the execution hot path (SAE, Executor, FillReconciler, Treasury) calls the RAG API
2. All RAG search calls use `asyncio.wait_for` with explicit timeouts
3. Partial container unavailability (one collection unreachable) returns results from remaining collections only — it does not block the agent's planning phase
4. `autoResearch` failure (OpenClaw/Supermemory unreachable) falls back to base system prompt enrichment only; agent planning continues
5. Ingestion failures are retried up to 3 times with exponential backoff; after 3 failures, the document is queued in a local retry queue and the ingestion job exits with a warning (non-fatal)

### 12.2 Timeouts

| Operation | Timeout | Failure behavior |
|---|---|---|
| `autoResearch` per-turn injection | 2.5s | Skip RAG enrichment for this turn; proceed with base prompt |
| Direct `supermemory_search` call | 3.0s | Return empty results; log `WARNING` |
| Multi-container parallel search | 3.0s | Return partial results from available containers |
| Document ingestion (CI job) | 30s per document | Retry × 3, then queue to local retry log |
| Stale document deletion (cleanup job) | 10s per delete | Log and continue; retry on next scheduled run |

### 12.3 Circuit Breaker

The RAG subsystem shares the same in-process circuit breaker as the memory subsystem (`apps/agents/rag/circuit_breaker.py`), tracking failures across both memory and RAG calls against the Supermemory service. State is shared: if the memory circuit opens, RAG calls are also blocked, and vice versa.

### 12.4 Observability

| Metric | Type | Labels |
|---|---|---|
| `supermemory_rag_search_duration_seconds` | Histogram | `container_tag`, `search_mode`, `status` |
| `supermemory_rag_autoresearch_duration_seconds` | Histogram | `agent_role`, `status` |
| `supermemory_rag_ingest_duration_seconds` | Histogram | `container_tag`, `doc_type`, `status` |
| `supermemory_rag_ingest_total` | Counter | `container_tag`, `doc_type`, `result` |
| `supermemory_rag_search_fallback_total` | Counter | `container_tag`, `reason` |
| `supermemory_rag_documents_total` | Gauge | `container_tag` (polled periodically) |

Alert: `supermemory_rag_search_fallback_total` rate > 30/min → `infra.rag_degraded` (non-critical; no trading halt).

---

## 13. Security Constraints

### 13.1 What May Be Ingested

Only the following content categories may be sent to the Supermemory managed RAG platform:

- Firm-authored design and strategy documents (`STRATEGY.md`, `SPEC-v2.1.md`, etc.)
- Publicly available research papers and protocol documentation
- Internal reports that contain no live financial data (historical backtest summaries with no real position sizes or PnL figures)
- Operational runbooks containing no credentials, IP addresses, or infrastructure topology

### 13.2 What Must Never Be Ingested

The following content must never be sent to any Supermemory container:

- Live or historical position sizes, open PnL, realized PnL, or account balance figures
- HyperLiquid API private keys, wallet private keys, or any credential material
- Infrastructure secrets: passwords, tokens, certificates, IP addresses, DNS names of internal services
- Individual fill records, order IDs, or exchange-internal identifiers
- Personally identifiable information about operators or counterparties
- Any content from `.env` files or Kubernetes Secrets

The ingestion pipeline includes a content policy pre-check that scans document content for patterns matching API key formats, private key formats, and credential structures before calling `client.add()`. Documents that fail the content policy check are rejected and logged to the ingestion audit trail.

```python
import re

CONTENT_POLICY_PATTERNS = [
    re.compile(r"0x[a-fA-F0-9]{64}"),         # Ethereum private key
    re.compile(r"[A-Za-z0-9]{32,64}"),          # Generic API key (broad; context-checked)
    re.compile(r"sk-[a-zA-Z0-9]{32,}"),         # OpenAI-style API key
    re.compile(r"-----BEGIN .+? PRIVATE KEY-----"),  # PEM private key
]

def passes_content_policy(content: str) -> tuple[bool, str | None]:
    """Returns (True, None) if content passes, or (False, reason) if rejected."""
    for pattern in CONTENT_POLICY_PATTERNS:
        if pattern.search(content):
            return False, f"Content matches forbidden pattern: {pattern.pattern[:40]}"
    return True, None
```

### 13.3 API Key Scope

The `SUPERMEMORY_API_KEY` used for RAG operations is the same key as used for memory operations (single Pro account, containerTag-scoped isolation). Key management follows the same constraints defined in `MEMORY_IMPLEMENTATION.md §10.2`.

---

## 14. Validation Plan

### Phase 1 — Collection Initialization

1. Create all seven `containerTag` collections with entity context strings
2. Ingest 5 representative documents per collection (strategy docs, policy files, backtest reports, protocol docs, runbooks)
3. Verify each document is retrievable via keyword query within its collection
4. Verify cross-collection leakage: a query to `kb_risk` must not return documents ingested only into `kb_strategy`

### Phase 2 — Retrieval Quality

1. For each collection, compose 10 representative agent queries based on real planning scenarios
2. Evaluate top-5 retrieved passages for semantic relevance (manual review)
3. Measure retrieval latency p50/p95 from the deployment region
4. Test metadata filtering: confirm `doc_type` and `version` filters correctly narrow results

### Phase 3 — autoResearch Integration

1. Enable `autoResearch: true` for two agents in isolation (technical analyst, fund manager) in paper environment
2. Run 20 paper cycles and inspect injected context blocks in agent logs
3. Evaluate context relevance: are injected passages topically appropriate to the planning query?
4. Measure `supermemory_rag_autoresearch_duration_seconds` p95 — must be < 2.0s

### Phase 4 — Ingestion Pipeline

1. Trigger CI ingestion job and verify all manifest documents are ingested successfully
2. Trigger a re-ingestion via strategy version promotion and verify old version documents are replaced
3. Simulate ingestion failure (revoke API key temporarily) and verify retry queue behavior and non-fatal exit

### Phase 5 — Content Policy

1. Attempt to ingest a synthetic document containing a fake private key pattern
2. Confirm the content policy check blocks ingestion and logs the rejection
3. Confirm no partial content is ingested when rejection occurs

### Acceptance Criteria

| Test | Pass condition |
|---|---|
| Collection isolation | Zero cross-container leakage in 100 queries |
| Retrieval quality | >= 70% of top-5 passages rated relevant by manual review |
| autoResearch latency | p95 < 2.0s from production region |
| Ingestion pipeline | All manifest documents ingested with no failures on first run |
| Content policy | 100% rejection rate for documents matching forbidden patterns |
| Failure isolation | All paper cycles complete under simulated Supermemory outage |

---

## 15. File Layout

```
apps/agents/
  rag/
    client.py              # Supermemory SDK client (shared with memory/client.py singleton)
    circuit_breaker.py     # Shared circuit breaker (same instance as memory CB)
    collections.py         # Collection containerTag constants and entity context strings
    search.py              # search_knowledge_base(), multi_container_search()
    inject.py              # build_rag_enriched_system_prompt()
    content_policy.py      # passes_content_policy() pre-ingest content scanner

apps/jobs/
  rag_ingest.py            # CI-triggered full manifest ingestion job
  rag_reingest.py          # Document re-ingestion on version promotion
  rag_cleanup.py           # Stale document TTL enforcement job
  rag_post_backtest.py     # Post-backtest/ablation report auto-ingest hook

config/
  openclaw/
    supermemory-skill.yaml # Per-agent autoResearch and container routing config
  rag/
    collections.yaml       # Entity context strings per containerTag (non-secret)
    ingest-manifest.yaml   # CI ingestion manifest: source paths -> containerTag mapping
    ttl-policy.yaml        # Per-collection stale document TTL configuration

infra/k8s/
  jobs/
    rag-ingest-job.yaml    # Kubernetes Job manifest for CI ingestion
    rag-cleanup-cronjob.yaml  # CronJob for TTL enforcement

tests/
  unit/
    rag/
      test_content_policy.py
      test_metadata_filter.py
      test_multi_container_search.py
  integration/
    rag/
      test_collection_isolation.py
      test_retrieval_quality.py
      test_ingest_pipeline.py
      test_autoresearch_injection.py
      test_failure_isolation.py
```

---

## 16. Open Questions

| Question | Owner | Resolution path |
|---|---|---|
| Should `kb_external` content require human review before ingestion, or can a curated web crawler ingest approved sources automatically? | Operator | Define an approved source list and automated curator policy before enabling auto-ingest |
| Should backtest report ingestion include raw metric tables (Sharpe, Calmar, max DD), or summaries only? | Engineering | Evaluate whether raw numeric tables improve or degrade retrieval quality in Phase 2 |
| Is there a Supermemory Pro feature for pinned or high-weight documents that should always appear in results? | Engineering | Review Supermemory Pro docs; relevant for core strategy docs that should rank highly for all queries |
| What is the right document deduplication strategy for HL protocol docs when minor version releases are published? | Engineering | Implement version-tagged ingestion with previous version deletion on each new HL release |
| Should `agent_optimizer` be granted `autoCapture: true` (captured outputs enter `kb_backtests`) after human review? | Operator | Gate decision on Phase 3 validation results and explicit operator approval |

---

*Supermemory.ai service: [supermemory.ai](https://supermemory.ai) · Docs: [supermemory.ai/docs](https://supermemory.ai/docs) · MCP endpoint: `https://mcp.supermemory.ai/mcp` · OpenClaw plugin: [supermemoryai/openclaw-supermemory](https://github.com/supermemoryai/openclaw-supermemory)*
