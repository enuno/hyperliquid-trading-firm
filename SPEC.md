# Hyperliquid Trading Firm — System Specification

**Version:** 3.0 — April 2026
**Status:** Active Development — Phase A
**Supersedes:** SPEC-v1.md (v0.1.0), SPEC-v2.md (v0.2.0), SPEC-v2.1.md (v2.1.0), SPEC.md (v2.2)
**Repo:** https://github.com/enuno/hyperliquid-trading-firm

---

## Table of Contents

1. [Overview](#1-overview)
2. [Design Principles](#2-design-principles)
3. [System Architecture](#3-system-architecture)
4. [TradingAgents Framework Integration](#4-tradingagents-framework-integration)
5. [Agent Roles and Responsibilities](#5-agent-roles-and-responsibilities)
6. [Decision Cycle Flow](#6-decision-cycle-flow)
7. [Data Flow and Invariants](#7-data-flow-and-invariants)
8. [Data Contracts — Protobuf](#8-data-contracts--protobuf)
9. [ObservationPack Schema](#9-observationpack-schema)
10. [TradeIntent Schema](#10-tradeintent-schema)
11. [Strategy Architecture](#11-strategy-architecture)
12. [Autoresearch Feedback Loop](#12-autoresearch-feedback-loop)
13. [Paper Bot — Continuous Real-Time Reinforcement](#13-paper-bot--continuous-real-time-reinforcement)
14. [Live Bot — Guarded Real-Fund Execution](#14-live-bot--guarded-real-fund-execution)
15. [Recovery Mode](#15-recovery-mode)
16. [SAE — Safety and Execution Agent](#16-sae--safety-and-execution-agent)
17. [FundManager](#17-fundmanager)
18. [Clawvisor HITL Rulesets](#18-clawvisor-hitl-rulesets)
19. [DecisionTrace and Audit Log](#19-decisiontrace-and-audit-log)
20. [Treasury Management System](#20-treasury-management-system)
21. [Quant Layer — apps/quant/](#21-quant-layer--appsquant)
22. [Orchestrator API](#22-orchestrator-api)
23. [Autonomous AI Optimization Agent](#23-autonomous-ai-optimization-agent)
24. [Safety Architecture — Invariants](#24-safety-architecture--invariants)
25. [Storage Schema](#25-storage-schema)
26. [Observability and Alerting](#26-observability-and-alerting)
27. [Dashboard](#27-dashboard)
28. [Repository Structure](#28-repository-structure)
29. [Configuration and Environment](#29-configuration-and-environment)
30. [Phased Build Plan](#30-phased-build-plan)
31. [Limitations and Scope Constraints](#31-limitations-and-scope-constraints)
32. [References](#32-references)

---

## 1. Overview

This system is an institutional-grade, autonomous, multi-agent LLM trading system for HyperLiquid perpetuals. It is modeled after the organizational structure of a real trading firm, implementing the architecture described in the [TradingAgents paper (arXiv 2412.20138)](https://arxiv.org/pdf/2412.20138) and the [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) open-source framework.

It combines a multi-agent adversarial debate architecture with deterministic quantitative pre-processing, a fractional Kelly sizing model, a multi-layer safety enforcement chain, and a non-bypassable Safety Approval Engine (SAE).

**Core mission:** Generate risk-adjusted returns on HL perps using structured agent debate, quant-validated signals, and fail-safe execution — not speculation.

**Key constraints:**
- All strategies are hypotheses to be validated before live deployment
- No guaranteed profits; every component must be independently audited
- LLM agents are advisory; SAE is the final deterministic gate before any order
- Closed bars only for all quantitative analysis — never include an incomplete bar
- Live execution requires human approval through the Clawvisor HITL system

The system extends the base TradingAgents framework with:

- A **Safety Approval Engine (SAE)** — non-bypassable deterministic pre-execution policy enforcement; no LLM in the approval path
- An **OpenClaw control plane** adapter for operator governance, HITL gating, and strategy lifecycle management
- A **Clawvisor HITL ruleset** system for operator-defined human approval requirements
- An **autonomous AI optimization agent** for continuous off-path performance improvement
- A **treasury management module** — automated BTC-to-stablecoin conversion for risk management
- A **quant layer** — deterministic signal pre-processing (wave detection, regime classification, Kelly sizing)
- Full **DecisionTrace** persistence so every trade decision is replayable and attributable
- A **reflection and continuous-improvement loop** for post-trade analysis and prompt-policy evolution

---

## 2. Design Principles

1. **Evidence-based, skeptical.** Treat all strategy hypotheses as unproven until out-of-sample validated.
2. **Separation of concerns.** Signal generation, risk control, execution, and audit are strictly isolated modules.
3. **Fail-closed by default.** Any stale data, missing context, or ambiguous state results in no trade — never a guess.
4. **Immutable audit trail.** Every signal, decision, order, and fill is written to `DecisionTrace` before execution. No action without a trace.
5. **No LLM authority over position sizing.** Kelly inputs must come from OOS historical statistics, not LLM confidence scores.
6. **Deterministic safety layer.** SAE enforces hard limits independent of agent output. Agents cannot override SAE.
7. **Observable and recoverable.** Every component exposes health metrics. Any failure must produce a clean recovery state, not corruption.
8. **Role specialization over monolithic agents.** Separate analyst, debate, trader, risk, fund-manager agents per TradingAgents.
9. **Structured state over prompt chaining.** Typed JSON/protobuf artifacts at every handoff.
10. **Adversarial challenge before commitment.** Bull/bear debate rounds before TradeIntent.
11. **Adaptation off the hot path.** Prompt-policy changes and strategy upgrades require explicit versioned promotion.
12. **No-trade is a first-class outcome.** HOLD/FLAT emitted when consensus is weak or risk objections unresolved.
13. **Live execution requires human approval.** Clawvisor HITL ruleset gates all live-mode cycles.
14. **Treasury-aware profitability.** BTC-to-stablecoin conversion integrated into risk management layer.

---

## 3. System Architecture

### 3.1 High-Level Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                        Data Ingestion                           │
│  HyperliquidFeed (REST bootstrap → WS delta → REST reconcile)  │
│  IntelliClaw (liquidation cluster feed)                         │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HLMarketContext
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Quant Layer                                │
│  WaveDetector + WaveAdapter  │  QZRegimeClassifier              │
│  KellySizingService          │  (deterministic, no LLM)         │
└───────────────────────────┬─────────────────────────────────────┘
                            │ WaveAnalysisResult, RegimeMappingResult, KellyOutput
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     ObserverAgent                               │
│  Assembles ObservationPack — merges quant outputs + raw market  │
│  context into typed schema consumed by debate agents            │
└───────────────────────────┬─────────────────────────────────────┘
                            │ ObservationPack
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│               Analyst Layer (5 specialists)                     │
│  Fundamental │ Sentiment │ News │ Technical │ Onchain           │
│  → ResearchPacket                                               │
└───────────────────────────┬─────────────────────────────────────┘
                            │ ResearchPacket
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Debate Layer (LLM)                           │
│  BullAgent  │  BearAgent  │  NeutralAgent / Moderator           │
│  Structured adversarial debate → DebateOutcome                  │
└───────────────────────────┬─────────────────────────────────────┘
                            │ DebateOutcome
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     TraderAgent (LLM)                           │
│  Synthesizes debate → emits TradeIntent (direction + rationale) │
│  Calls KellySizingService to populate sizing fields             │
└───────────────────────────┬─────────────────────────────────────┘
                            │ TradeIntent
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   RiskCommitteeAgent (LLM)                      │
│  3 profiles (aggressive / neutral / conservative) in parallel   │
│  → RiskReview                                                   │
└───────────────────────────┬─────────────────────────────────────┘
                            │ RiskReview
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FundManager                                │
│  Deterministic portfolio-level caps, correlation limits         │
│  → ExecutionApproval                                            │
└───────────────────────────┬─────────────────────────────────────┘
                            │ ExecutionApproval
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Clawvisor HITL Gate                            │
│  Evaluates HITL ruleset → pauses for human approval if required │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              SAE — Safety and Execution Agent                   │
│  Final deterministic gate — enforces hard limits                │
│  Writes DecisionTrace → submits order to HL                     │
└───────────────────────────┬─────────────────────────────────────┘
                            │ Order
                            ▼
                    HyperLiquid Exchange
                            │
                            ▼
                    Treasury Management
                    (BTC→USDC conversion on realized PnL)
```

### 3.2 Service Map

```
┌─────────────────────────────────────────────────────────┐
│                    OpenClaw Control Plane                │
│  (cycle trigger, HITL approval, policy governance,      │
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
       │         └──────┬──────┘    ┌───────▼────────┐
       │                │           │  Treasury Mgr   │
       │                │           │  (BTC→stable)   │
       └────────────────▼───────────┴────────┬────────┘
                  Postgres / MLflow / Object Store
                  (DecisionTraces, fills, policies,
                   prompt history, experiments,
                   treasury events)
                         │
               ┌─────────┴──────────┐
               │   Dashboard / UI   │
               │  (traces, govern., │
               │   experiments)     │
               └────────────────────┘
                         │
               ┌─────────▼──────────┐
               │  Optimizer Agent   │
               │  (off-path perf.   │
               │   improvement)     │
               └────────────────────┘
```

### 3.3 Dual-Bot Architecture

The system operates two concurrent bots plus an overnight autoresearch loop:

```
┌─────────────────────────────────────────────────────────────────┐
│                     OVERNIGHT AGENT LOOP                        │
│  autoresearch-style: ~100 experiments × 5min backtest budget    │
│                                                                 │
│  ┌──────────────┐    propose     ┌──────────────────────────┐   │
│  │  LLM Agent   │ ─────────────► │  strategy_paper.py       │   │
│  │  (iteration  │ ◄───────────── │  backtest score          │   │
│  │   loop)      │    score       └──────────────────────────┘   │
│  └──────┬───────┘                                               │
│         │ accepted (Sharpe ≥ threshold)                         │
└─────────┼───────────────────────────────────────────────────────┘
          │ git commit + ArgoCD deploy
          ▼
┌─────────────────────────────────────┐
│         PAPER BOT (always on)       │  ← real-time reinforcement data
│  strategy_paper.py                  │    every trade logged to RL buffer
│  HyperLiquid paper wallet           │
└──────────────┬──────────────────────┘
               │ reinforcement signal (win/loss/edge deltas)
               │ fed back into next autoresearch iteration
               ▼
┌─────────────────────────────────────┐
│         LIVE BOT (guarded)          │
│  strategy_live.py ← promoted from   │
│  paper only when paper Sharpe≥1.5   │
│  AND paper win_rate≥45% over 48h    │
│                                     │
│  ┌─────────────────────────────┐    │
│  │  PROFIT VAULT               │    │
│  │  10–20% of each trade PnL   │    │
│  │  sent to vault wallet addr  │    │
│  └─────────────────────────────┘    │
│                                     │
│  DRAWDOWN GUARD: if equity drops    │
│  to 50% of start → CEASE TRADING   │
│  → trigger Recovery Mode            │
└─────────────────────────────────────┘
```

---

## 4. TradingAgents Framework Integration

### 4.1 Adoption Strategy

The [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) framework is incorporated as a **git submodule** under `apps/agents/tradingagents/`. Its internal agent graph, analyst roles, debate workflow, and backbone LLM routing are used directly, **wrapped by HL-specific adapters** that:

1. Replace TradingAgents' generic data feeds with HyperLiquid + IntelliClaw + onchain sources
2. Enforce typed output schemas (JSON matching proto contracts) instead of free-form text
3. Route outputs into the Orchestrator API's typed state store
4. Add the `onchain` analyst role (not in base framework) for HL-specific DeFi signals
5. Add the `optimizer_agent` for autonomous off-path performance improvement

### 4.2 What Is Used Unchanged

- Analyst agent class hierarchy (fundamental, sentiment, news, technical)
- Bull/bear researcher pattern and debate facilitator
- Trader agent synthesis pattern
- Backbone LLM routing concept (fast models for retrieval, strong models for synthesis/debate)
- Risk management team structure (mapped to aggressive/neutral/conservative profiles)
- Fund manager final approval pattern

### 4.3 What Is Extended or Replaced

| TradingAgents Component | This Repo Extension |
|:--|:--|
| In-process agent graph | Distributed services via Orchestrator API event bus |
| Free-form string outputs | Typed protobuf/JSON artifact outputs |
| Single-process execution | SAE non-bypassable approval layer |
| Generic data sources | HL-specific: HyperLiquid REST/WS, IntelliClaw, Pyth, onchain |
| No operator governance | OpenClaw adapter + Clawvisor HITL rulesets |
| No audit trail | Immutable DecisionTrace per cycle in Postgres |
| No post-trade reflection | Jobs service: offline evaluation, prompt-policy scoring |
| No treasury management | Automated BTC-to-stablecoin conversion module |
| No autonomous optimization | Optimizer agent for off-path performance improvement |
| No quant pre-processing | Full quant layer: wave detection, regime classification, Kelly sizing |

### 4.4 Model Routing

| Stage | Model Class | Rationale |
|:--|:--|:--|
| Data normalization, entity extraction | Fast/cheap (GPT-4o-mini, Haiku) | High volume, low reasoning requirement |
| Analyst synthesis | Mid-tier (GPT-4o, Sonnet) | Domain reasoning on structured inputs |
| Bull/bear debate rounds | Strong reasoning (o3, Opus) | Adversarial argument quality matters |
| Trader synthesis | Strong reasoning | Final intent formulation |
| Risk committee | Mid-tier × 3 profiles | Parallel profile evaluation |
| Fund manager | Strong reasoning | Portfolio-level constraint enforcement |
| Optimizer agent | Mid-tier | Off-path; latency tolerance is high |
| SAE | Deterministic rule engine | No LLM — hard policy only |

---

## 5. Agent Roles and Responsibilities

### 5.1 ObserverAgent

Assembles `ObservationPack` from all available inputs. Does not interpret or trade.

**Inputs:**
- `HLMarketContext` from `HyperliquidFeed`
- `WaveAnalysisResult` + `WaveSAEInputs` from `WaveAdapter`
- `RegimeMappingResult` from `QZRegimeClassifier`
- Active positions and open orders

**Outputs:** Fully typed `ObservationPack` (see §9).

**Constraints:**
- Must not call LLM
- Must set `has_data_gap = True` if any feed exceeds 60s stale
- Must run `WaveAdapter.analyze()` on closed bars only

### 5.2 Analyst Agents (5 specialists)

Five specialist analysts produce a `ResearchPacket`:

| Analyst | Source |
|:--|:--|
| `fundamental` | On-chain metrics, protocol data, macro indicators |
| `sentiment` | Social media sentiment, fear/greed indices, IntelliClaw |
| `news` | News feeds, event calendars, regulatory developments |
| `technical` | Price action, indicators, pattern recognition |
| `onchain` | HL-specific: vault flows, liquidation map, whale tracker, funding |

Each analyst receives the same `ObservationPack` and produces an `AnalystScore` with cited evidence. If any source is stale > 60s, the analyst must flag `data_gap: true`.

### 5.3 BullAgent / BearAgent / NeutralAgent (Debate Layer)

Adversarial LLM debate agents. Each receives the same `ObservationPack` and `ResearchPacket` and produces a structured argument for or against entering a position.

**Constraints:**
- Must cite specific fields from `ObservationPack` in every argument
- Must not fabricate market data not present in `ObservationPack`
- Confidence scores from debate are advisory only — never used as Kelly inputs

### 5.4 TraderAgent

Synthesizes debate output into a `TradeIntent`.

**Constraints:**
- Must call `KellySizingService` with OOS-validated stats, not LLM confidence
- Must emit `FLAT` if debate is inconclusive or `has_data_gap = True`

### 5.5 RiskCommitteeAgent

Three profiles (aggressive / neutral / conservative) evaluate `TradeIntent` in parallel.

**Constraints:**
- May only reduce `suggested_notional_pct`, never increase it
- Must provide written rationale for any veto
- Veto writes to `DecisionTrace` before propagating

### 5.6 FundManager

Deterministic (non-LLM) portfolio-level gating agent. See §17.

### 5.7 SAE — Safety and Execution Agent

Final deterministic gate. No LLM dependency. See §16.

---

## 6. Decision Cycle Flow

```
1.  INGEST        Market snapshot (HL OHLCV + OB + funding rate + OI)
                  + IntelliClaw intel feed
                  + Sentiment/news ingestion (with bot-filter weights)
                  + Onchain signals (vault flows, liquidation map, whale tracker)

2.  QUANT         Quant layer: WaveDetector, RegimeClassifier, KellySizing
                  → WaveAnalysisResult, RegimeMappingResult

3.  OBSERVE       ObserverAgent assembles ObservationPack
                  → Flag has_data_gap if any source stale > 60s

4.  ANALYZE       5 specialist analysts → ResearchPacket
                  [fundamental, sentiment, news, technical, onchain]

5.  DEBATE        Bull researcher thesis + Bear researcher thesis
                  → Facilitator debate (N rounds, configurable)
                  → DebateOutcome [consensus_strength, open_risks]
                  → If consensus_strength < threshold → FLAT (skip to step 13)

6.  TRADE         Trader agent synthesizes ResearchPacket + DebateOutcome
                  → TradeIntent [action, confidence, notional_pct, rationale]
                  → KellySizingService populates sizing fields

7.  RISK          3 risk profiles evaluate TradeIntent in parallel
                  → RiskVote × 3 → RiskReview [committee_result, net_size_cap]

8.  FUND MGR      Fund manager applies portfolio constraints
                  → ExecutionApprovalRequest → ExecutionApproval

9.  HITL GATE     Clawvisor HITL ruleset evaluated
                  → If required: pause for human approval via OpenClaw
                  → On timeout: apply on_timeout policy (reject or approve)

10. SAE           Deterministic policy checks (no LLM):
                  position limits, drawdown, daily loss, leverage caps,
                  liquidity gate, correlation gate, stale data,
                  funding rate, event blackout, swing failure proximity
                  → ExecutionDecision [allowed, checks_passed/failed, staged_requests]

11. EXECUTE       Executor submits staged requests to HyperLiquid
                  → FillReport(s)

12. RECONCILE     Fill reconciler updates portfolio state (position, PnL,
                  exposure, drawdown)

13. PERSIST       DecisionTrace written atomically with all artifacts

14. TREASURY      Treasury manager evaluates realized PnL against conversion
                  thresholds → triggers BTC→USDC conversion if applicable

15. REFLECT       Post-trade jobs (off hot path):
                  prompt-policy scoring, ablation contribution,
                  optimizer agent evaluation, reflection loop
```

### 6.1 No-Trade Conditions

The system **must** emit `action: FLAT` and skip execution when any of the following are true:

- `debate_outcome.consensus_strength < config.min_consensus_threshold`
- `risk_review.committee_result == "reject"` and `config.require_unanimous_for_live == true`
- `execution_approval.approved == false`
- `sae_decision.allowed == false`
- HITL gate is open and timeout has not expired
- Any analyst report has `data_gap: true`
- Any required condition in `trade_intent.required_conditions` is not satisfied
- `market_snapshot.age_seconds > 60` (stale data)
- `ObservationPack.has_data_gap == true`

---

## 7. Data Flow and Invariants

### 7.1 Closed-Bar Invariant

**All quantitative analysis runs on closed bars only.** The current incomplete bar is never included in any calculation. This is enforced at the feed adapter level (`HyperliquidFeed`) and validated in `WaveDetector`.

Rationale: Intrabar calculations produce regime/wave false positives, unstable RSI values, and incorrect swing detection that vanish at bar close.

### 7.2 Feed Reconciliation

`HyperliquidFeed` reconciles REST vs WS state every 30 seconds. If a sequence gap is detected or any source exceeds 60 seconds stale:
- `HLMarketContext.has_data_gap` is set to `True`
- `ObservationPack.has_data_gap` is propagated
- `TraderAgent` must emit `FLAT` on `has_data_gap = True`
- SAE must reject any `ExecutionApproval` where source `ObservationPack.has_data_gap = True`

### 7.3 Signal Freshness

Every field in `ObservationPack` carries a `timestamp_utc`. SAE validates that all signals are within `MAX_SIGNAL_AGE_SECONDS` (default 120) before proceeding.

---

## 8. Data Contracts — Protobuf

### 8.1 Core Types (common.proto)

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
  UNKNOWN     = 6;
}
```

### 8.2 Decisioning (decisioning.proto)

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
  tradingfirm.common.Meta meta                = 1;
  double                  bull_score          = 2;
  double                  bear_score          = 3;
  string                  bull_thesis         = 4;
  string                  bear_thesis         = 5;
  double                  consensus_strength  = 6;
  repeated string         open_risks          = 7;
  string                  facilitator_summary = 8;
  uint32                  debate_rounds       = 9;
}

message TradeIntent {
  tradingfirm.common.Meta      meta                = 1;
  string                       asset               = 2;
  tradingfirm.common.Direction action              = 3;
  double                       thesis_strength     = 4;
  double                       confidence          = 5;
  double                       target_notional_pct = 6;
  double                       preferred_leverage  = 7;
  uint32                       max_slippage_bps    = 8;
  string                       time_horizon        = 9;
  repeated string              required_conditions = 10;
  string                       rationale           = 11;
}
```

### 8.3 Risk (risk.proto)

```protobuf
message RiskVote {
  tradingfirm.common.Meta meta         = 1;
  string                  profile      = 2;  // aggressive|neutral|conservative
  bool                    approve      = 3;
  double                  size_cap_pct = 4;
  repeated string         objections   = 5;
}

message RiskReview {
  tradingfirm.common.Meta meta             = 1;
  repeated RiskVote       votes            = 2;
  string                  committee_result = 3;  // approve|approve_with_modification|reject
  double                  net_size_cap_pct = 4;
  repeated string         unresolved_risks = 5;
}

message ExecutionApprovalRequest {
  tradingfirm.common.Meta             meta                   = 1;
  tradingfirm.decisioning.TradeIntent trade_intent           = 2;
  RiskReview                          risk_review            = 3;
  double                              portfolio_exposure_pct = 4;
  double                              daily_pnl_pct          = 5;
  double                              drawdown_pct           = 6;
  double                              correlation_to_book    = 7;
}

message ExecutionApproval {
  tradingfirm.common.Meta meta               = 1;
  bool                    approved           = 2;
  string                  rejection_reason   = 3;
  double                  final_notional_pct = 4;
  double                  final_leverage     = 5;
  string                  execution_algo     = 6;  // TWAP|VWAP|POV|ICEBERG|MARKET|LIMIT
}
```

### 8.4 Execution (execution.proto)

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
  tradingfirm.common.Meta   meta             = 1;
  bool                      allowed          = 2;
  string                    policy_version   = 3;
  repeated string           checks_passed    = 4;
  repeated string           checks_failed    = 5;
  repeated ExecutionRequest staged_requests  = 6;
  string                    rejection_reason = 7;
}

message FillReport {
  tradingfirm.common.Meta meta           = 1;
  string                  venue_order_id = 2;
  string                  asset          = 3;
  double                  filled_qty     = 4;
  double                  avg_price      = 5;
  double                  fees_usd       = 6;
  double                  slippage_bps   = 7;
  string                  status         = 8;
}
```

---

## 9. ObservationPack Schema

`ObservationPack` is the typed, immutable context object passed from `ObserverAgent` to all downstream agents. It is written to `DecisionTrace` before any agent processes it.

```python
@dataclass(frozen=True)
class ObservationPack:
    # Identity
    asset: str                          # e.g. "BTC-PERP"
    timestamp_utc: datetime
    has_data_gap: bool                  # True = fail-closed downstream

    # Market state
    mid_price: float
    mark_price: float
    index_price: float
    bid: float
    ask: float
    spread_bps: float

    # Order book depth
    depth_10bps_usd: float              # Total liquidity within +/-10bps
    depth_50bps_usd: float

    # Funding
    funding_rate_8h: float              # Normalized to 8h regardless of venue cadence
    funding_rate_annualized: float
    predicted_funding_rate_8h: float

    # Liquidation clusters (from IntelliClaw)
    nearest_liq_cluster_above_pct: float   # % distance above mid
    nearest_liq_cluster_below_pct: float   # % distance below mid
    liq_cluster_density_above: float       # Relative density score
    liq_cluster_density_below: float

    # Volatility
    realized_vol_24h: float
    realized_vol_7d: float
    realized_vol_zscore: float              # Z-score vs 90-day history

    # Regime (from QZRegimeClassifier)
    market_regime: MarketRegime             # Canonical operational enum
    qz_regime: QZRegime                     # Fine-grained regime label
    regime_confidence: float

    # Wave structure (from WaveAdapter)
    swing_high: Optional[SwingLevel]        # Nearest confirmed swing high
    swing_low: Optional[SwingLevel]         # Nearest confirmed swing low
    quantitative_baseline: dict             # Full wave analysis dict (see §21.4)

    # Portfolio context
    current_position_size: float
    current_position_direction: str         # "LONG" | "SHORT" | "FLAT"
    current_position_pnl_pct: float
    current_position_age_bars: int

    # Active orders
    open_orders: List[dict]
```

**`MarketRegime` enum values** (from `proto/common.proto`):
- `TREND_UP`, `TREND_DOWN` — clean directional
- `RANGE` — mean-reversion
- `HIGH_VOL` — risk-control-dominant; overrides direction
- `EVENT_RISK` — structural uncertainty; default to FLAT
- `UNKNOWN` — insufficient data

**`QZRegime` enum values** (fine-grained, from `apps/quant/regimes/`):
- `trend_up_low_vol`, `trend_up_high_vol`
- `trend_down_low_vol`, `trend_down_high_vol`
- `range_low_vol`, `range_high_vol`
- `event_breakout`
- `liquidation_cascade_risk`
- `funding_crowded_long`, `funding_crowded_short`

---

## 10. TradeIntent Schema

```python
@dataclass
class TradeIntent:
    # Identity
    intent_id: str                      # UUID
    asset: str
    timestamp_utc: datetime
    observation_pack_id: str            # Links to ObservationPack in DecisionTrace

    # Decision
    direction: str                      # "LONG" | "SHORT" | "FLAT"
    rationale: str                      # Written justification citing ObservationPack fields
    debate_summary: str                 # Condensed debate outcome

    # Kelly sizing (populated by KellySizingService)
    kelly_inputs: KellyInputs           # win_prob, payoff_ratio, source bucket, OOS trade count
    kelly_output: KellyOutput           # raw_fraction, adjusted_fraction, penalties_applied
    suggested_notional_pct: float       # Final Kelly-adjusted size as % of portfolio

    # Entry/exit parameters
    entry_price_estimate: float
    stop_loss_price: float
    take_profit_price: float
    max_holding_bars: int

    # Confidence (advisory only — never used as Kelly input)
    agent_confidence: float             # from TraderAgent — informational only
```

---

## 11. Strategy Architecture

### 11.1 Dual-File Architecture

The agent manages **two** strategy files. `strategy_paper.py` is the active experiment target. `strategy_live.py` is only written when paper promotion criteria are met.

```
strategy/
├── strategy_base.py          ← locked interface
├── strategy_paper.py         ← AGENT-EDITABLE (paper bot target)
├── strategy_live.py          ← written by promotion logic only (not agent-direct)
└── strategy_vault.py         ← vault pct config (locked addr, editable rate)
```

### 11.2 Shared Interface (strategy_base.py, locked)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal
import pandas as pd

@dataclass
class StrategyConfig:
    # Indicator params — agent editable
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    atr_period: int = 14
    atr_stop_multiplier: float = 2.0
    bb_period: int = 20
    bb_std: float = 2.0
    vwap_enabled: bool = False

    # Signal logic — agent editable
    entry_signal: Literal[
        "ema_cross", "rsi_reversal", "breakout",
        "bb_squeeze", "vwap_reversion", "hybrid"
    ] = "ema_cross"
    exit_signal: Literal[
        "atr_trail", "fixed_tp_sl", "time_exit", "signal_flip"
    ] = "atr_trail"
    take_profit_pct: float = 0.03
    stop_loss_pct: float = 0.015

    # Sizing — agent editable (capped by safety layer)
    position_size_pct: float = 0.10
    max_concurrent_positions: int = 1

    # Order type — agent editable
    entry_order_type: Literal["limit", "market"] = "limit"
    limit_offset_bps: int = 5
    min_edge_bps: int = 10

    # Vault config — agent MAY adjust rate, vault address is LOCKED
    vault_take_pct: float = 0.10        # 10-20%; clamped by safety layer


class BaseStrategy(ABC):
    def __init__(self, config: StrategyConfig):
        self.cfg = config

    @abstractmethod
    def generate_signal(self, candles: pd.DataFrame) -> Literal["long", "short", "flat"]: ...

    @abstractmethod
    def compute_entry_price(self, signal: str, mid: float) -> float: ...

    @abstractmethod
    def compute_position_size(self, equity: float, price: float) -> float: ...

    @abstractmethod
    def should_exit(self, position: dict, candles: pd.DataFrame) -> bool: ...
```

### 11.3 Three-Tier Promotion Lifecycle

```
BACKTEST  →  Sharpe >= 1.5, max_dd < 8%, n_trades >= 10
    ↓
PAPER TRADE  →  Sharpe >= 1.5, win_rate >= 45%, 48h real-time window
    ↓
LIVE TRADE  →  Real funds, vault active, drawdown guards armed
    ↓ (on equity <= 50% of session start)
RECOVERY MODE  →  Live halted, accelerated research (200 iter/night),
                  raised bar: Sharpe >= 2.0, win_rate >= 50%, 72h paper
```

### 11.4 Strategy Config Constraints

When proposing a new `strategy_paper.py`, an agent MUST:

- Implement the `BaseStrategy` interface defined in `strategy/strategy_base.py`
- Change **at most 3** `StrategyConfig` parameters per iteration
- Justify each change referencing recent paper trade outcomes from the RL buffer
- Prefer `limit` order types (`entry_order_type = "limit"`)
- Keep `vault_take_pct` within `[0.10, 0.20]`
- Keep `position_size_pct <= 0.20` (safety layer will clamp)

### 11.5 Supported Entry/Exit Signals

**Entry:** `ema_cross`, `rsi_reversal`, `breakout`, `bb_squeeze`, `vwap_reversion`, `hybrid`
**Exit:** `atr_trail`, `fixed_tp_sl`, `time_exit`, `signal_flip`

Do not introduce signal types outside this enum without updating `strategy_base.py` in a separate, human-reviewed PR.

---

## 12. Autoresearch Feedback Loop

The key innovation: paper-trade outcomes feed directly back into each new autoresearch proposal as **reinforcement context**. The LLM agent sees recent paper trade results, not just backtest scores.

### 12.1 Reinforcement Buffer

```python
@dataclass
class PaperTradeOutcome:
    strategy_run_id: str
    symbol: str
    signal: str            # long / short
    entry_price: float
    exit_price: float
    pnl_usd: float
    pnl_pct: float
    hold_bars: int
    entry_signal_features: dict   # snapshot of indicators at entry
    exit_reason: str       # atr_trail | tp | sl | signal_flip | time_exit
    funding_paid: float
    fee_paid: float
    timestamp: int
```

### 12.2 Agent Proposal Context Injection

```python
async def build_proposal_context(db) -> dict:
    return {
        "program": load_trading_program("trading_program.md"),
        "backtest_history": db.last_n_experiments(20),
        "paper_rl_window": db.get_rl_aggregates(hours=48),
        "paper_recent_trades": db.get_paper_outcomes(limit=50),
        "current_live_config": load_live_config(),
        "market_conditions": await get_market_snapshot(),  # funding, vol regime
        "recovery_mode": get_recovery_state(),
    }
```

### 12.3 Iteration Loop

```python
async def overnight_loop(
    max_iterations: int = 100,
    backtest_budget_minutes: float = 5.0,
    score_threshold: float = 1.5,
):
    for i in range(max_iterations):
        # 1. BUILD CONTEXT — backtest history + live paper RL signal
        ctx = await build_proposal_context(db)

        # 2. PROPOSE — LLM generates StrategyConfig + strategy body
        proposal = await agent.propose_strategy(
            context=ctx,
            constraints=[
                "max 3 StrategyConfig param changes from current paper config",
                "prefer limit orders",
                "account for current funding rate regime",
                "justify each change referencing recent paper trade outcomes",
            ]
        )

        # 3. VALIDATE
        if not validate_strategy_module(proposal.code):
            db.log(proposal, kept=False, rationale="validation_fail")
            continue

        # 4. BACKTEST (5min budget)
        try:
            score = await asyncio.wait_for(
                run_backtest(proposal.strategy, candles),
                timeout=backtest_budget_minutes * 60
            )
        except asyncio.TimeoutError:
            db.log(proposal, kept=False, rationale="timeout")
            continue

        # 5. SCORE vs THRESHOLD
        if not should_keep(score, db.get_best_score()):
            db.log(proposal, score=score, kept=False)
            continue

        # 6. ACCEPT — deploy to paper bot (ArgoCD picks up commit)
        db.log(proposal, score=score, kept=True)
        git_commit_strategy(
            proposal.code,
            path="strategy/strategy_paper.py",
            tag=f"paper/v{i}",
            message=proposal.rationale
        )

        await asyncio.sleep(2)
```

### 12.4 Keep / Discard Decision

```python
def should_keep(new_score: dict, best_score: dict | None) -> bool:
    if new_score["max_drawdown"] > 0.08:
        return False   # hard constraint
    if new_score["n_trades"] < 10:
        return False   # insufficient sample
    if best_score is None:
        return new_score["sharpe"] > SCORE_THRESHOLD
    return (new_score["sharpe"] > best_score["sharpe"] and
            new_score["max_drawdown"] <= best_score["max_drawdown"] * 1.1)
```

---

## 13. Paper Bot — Continuous Real-Time Reinforcement

The paper bot runs **continuously** (not just during evaluation windows). It shadows live market prices 24/7, logging every simulated trade to the RL buffer.

```python
class PaperBot:
    async def run(self):
        async for tick in hl_ws.subscribe_trades(symbol):
            signal = self.strategy.generate_signal(self.candle_buffer)
            if signal != "flat" and self.position is None:
                self._open_simulated_position(signal, tick.price)
            elif self.position and self.strategy.should_exit(
                    self.position, self.candle_buffer):
                outcome = self._close_simulated_position(tick.price)
                await rl_buffer.write(outcome)
                await self._check_promotion_criteria()

    async def _check_promotion_criteria(self):
        agg = await rl_buffer.get_aggregates(hours=48)
        if (agg.sharpe >= 1.5
                and agg.win_rate >= 0.45
                and agg.meets_minimum_trades(n=30)
                and not recovery_state.active):
            await promote_to_live(self.strategy)
```

---

## 14. Live Bot — Guarded Real-Fund Execution

### 14.1 Session State

```python
@dataclass
class LiveSession:
    session_id: str
    session_start_equity: float     # set at bot start, never updated
    current_equity: float
    peak_equity: float
    vault_balance: float            # accumulated in separate HL sub-account
    total_profit_realized: float
    halt_reason: str | None = None

    @property
    def recovery_threshold(self) -> float:
        return self.session_start_equity * 0.50   # 50% floor

    @property
    def in_recovery(self) -> bool:
        return self.current_equity <= self.recovery_threshold
```

### 14.2 Trade Execution with Vault Deduction

```python
async def close_position_and_vault(position, exit_price, session):
    raw_pnl = compute_pnl(position, exit_price)
    fee = compute_fees(position, exit_price)
    net_pnl = raw_pnl - fee

    if net_pnl > 0:
        vault_amt = net_pnl * clamp(session.vault_take_pct, 0.10, 0.20)
        trading_amt = net_pnl - vault_amt
        await exchange.transfer_to_vault(vault_amt, VAULT_SUBACCOUNT_ADDRESS)
        session.vault_balance += vault_amt
        session.current_equity += trading_amt
    else:
        session.current_equity += net_pnl

    session.peak_equity = max(session.peak_equity, session.current_equity)
    db.log_live_trade(position, exit_price, net_pnl, vault_amt)
    safety.check_recovery_threshold(session)
```

### 14.3 Vault Rules (locked, human-configurable)

| Rule | Value | Notes |
|:--|:--|:--|
| Vault take rate | 10-20% | Agent may set within range; default 10% |
| Vault take condition | Profitable trades only | Losses never touch vault |
| Vault address | `VAULT_SUBACCOUNT_ADDRESS` env var | Locked; never agent-writable |
| Vault withdrawal | Manual only | No automated withdrawal logic |
| Vault floor protection | Vault balance never re-deployed to trading | One-way transfer |

---

## 15. Recovery Mode

Recovery mode activates when `session.current_equity <= session_start_equity * 0.50`.

### 15.1 Trigger Sequence

1. Cancel all open live orders
2. Close all open positions at market
3. Engage recovery mode
4. Emit alert

### 15.2 Recovery Mode Behavior

```python
@dataclass
class RecoveryState:
    active: bool = False
    activated_at: int = 0
    floor_equity: float = 0.0
    recovery_target_sharpe: float = 2.0   # higher bar than normal 1.5
    min_paper_hours: float = 72.0         # 3 days minimum paper revalidation
    iterations_completed: int = 0
    deactivation_criteria_met: bool = False
```

While in recovery:

1. **Live bot**: completely halted, no orders
2. **Autoresearch loop**: runs at double iteration rate (overnight: 200 experiments)
3. **Paper bot**: continues 24/7, feeds RL buffer
4. **Promotion bar raised**: Sharpe >= 2.0 (vs normal 1.5), 72h paper window (vs 48h), win_rate >= 50% (vs 45%)
5. **Recovery exit**: all three raised criteria met → live bot resumes with new strategy, `session_start_equity` reset to current equity level

---

## 16. SAE — Safety and Execution Agent

SAE is the final deterministic gate before any order reaches HyperLiquid. It is the only component with exchange API write access. It cannot be overridden by any agent output. It has no LLM dependency.

### 16.1 Pre-execution Checks

SAE validates all of the following before submitting any order. Failure on any check results in immediate REJECT with `DecisionTrace` entry:

| Check | Hard Limit | Source |
|:--|:--|:--|
| Signal freshness | All signals < 120s old | `ObservationPack.timestamp_utc` |
| Data gap | `has_data_gap = False` | `ObservationPack.has_data_gap` |
| Position size | <= `SAE_MAX_NOTIONAL_PCT` (10%) | `ExecutionApproval.approved_notional_pct` |
| Notional USD | <= `SAE_MAX_NOTIONAL_USD` | Config |
| Leverage | <= `SAE_MAX_LEVERAGE` (3x paper, 2x live) | Config |
| Spread | <= `SAE_MAX_SPREAD_BPS` (50bps) | `ObservationPack.spread_bps` |
| Funding | Long: funding < `SAE_MAX_FUNDING_LONG` (0.30%/8h) | `ObservationPack.funding_rate_8h` |
| Volatility | Vol z-score <= `SAE_MAX_VOL_ZSCORE` (3.0) | `ObservationPack.realized_vol_zscore` |
| Liq cluster proximity | Nearest cluster > `SAE_MIN_LIQ_DISTANCE_PCT` (0.5%) | `ObservationPack.nearest_liq_cluster_*_pct` |
| Swing failure proximity | `near_swing_failure = True` → -50% size penalty | `WaveSAEInputs.near_swing_failure` |
| Near swing failure USD | Position <= `SAE_SWING_FAILURE_REDUCED_PCT` (5%) | When `near_swing_failure = True` |
| Liquidity gate | 24h volume >= 10x trade notional | Config |
| Correlation gate | New position correlation to book <= 0.7 | Config |
| Portfolio drawdown | Portfolio drawdown <= 8% | Live portfolio state |
| Daily loss limit | Daily PnL <= -3% | Live portfolio state |
| Event blackout | No active macro event flag | Config |
| Kill switch | `KILL_SWITCH = False` | Environment variable |

### 16.2 Order Execution

On approval:

1. Write complete `DecisionTrace` entry with all inputs, checks, and approval state
2. Compute final order parameters (size, price, slippage tolerance)
3. Submit order to HL with idempotency key = `intent_id`
4. On fill: write fill details to `DecisionTrace`
5. On partial fill: reassess remaining quantity before submitting remainder

### 16.3 Kill Switch

`KILL_SWITCH=true` in environment immediately:
- Rejects all new `ExecutionApproval` objects
- Does NOT close existing positions automatically (separate `EMERGENCY_FLATTEN=true` env var)
- Logs kill switch activation to audit log with timestamp and PID

### 16.4 Heartbeat Monitoring

SAE exposes a `/health` endpoint. A watchdog process restarts SAE if heartbeat exceeds `SAE_HEARTBEAT_TIMEOUT_SECONDS` (30). On restart, SAE reconciles open orders with exchange state before accepting new approvals.

---

## 17. FundManager

FundManager is a deterministic (non-LLM) component that applies portfolio-level constraints to `RiskReview` before emitting `ExecutionApproval`.

### 17.1 Portfolio Constraints

| Constraint | Default | Config Key |
|:--|:--|:--|
| Max single position | 10% of portfolio | `FUND_MAX_SINGLE_POSITION_PCT` |
| Max correlated exposure | 25% of portfolio | `FUND_MAX_CORRELATED_EXPOSURE_PCT` |
| Max total gross exposure | 200% of portfolio | `FUND_MAX_GROSS_EXPOSURE_PCT` |
| Max positions simultaneously | 5 | `FUND_MAX_CONCURRENT_POSITIONS` |
| Min time between trades (same asset) | 4 closed bars | `FUND_MIN_BARS_BETWEEN_TRADES` |

### 17.2 Kelly Governance

FundManager receives `TradeIntent.suggested_notional_pct` (Kelly-adjusted) and applies the portfolio constraints above. It may **reduce** but never **increase** `suggested_notional_pct`. The resulting `approved_notional_pct` is written to `ExecutionApproval`.

SAE then applies its own independent position limit check on `approved_notional_pct`. Neither FundManager nor SAE can increase the size set by `KellySizingService`.

---

## 18. Clawvisor HITL Rulesets

The Clawvisor system gates specific actions behind human approval. Rules are evaluated after FundManager and before SAE.

### 18.1 Ruleset Schema

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
    },
    {
      "name": "treasury_large_conversion",
      "when": { "treasury_conversion_usd_gte": 10000 },
      "require_approval": true,
      "timeout_seconds": 600,
      "on_timeout": "reject"
    }
  ]
}
```

---

## 19. DecisionTrace and Audit Log

Every trading decision — including rejections — is written to an append-only `DecisionTrace` before the action is taken.

### 19.1 DecisionTrace Fields

```python
@dataclass
class DecisionTrace:
    trace_id: str                       # UUID
    timestamp_utc: datetime
    asset: str
    cycle_id: str                       # Groups all records from one decision cycle

    # Inputs
    observation_pack: ObservationPack
    debate_result: DebateResult
    trade_intent: TradeIntent
    risk_review: RiskReview
    execution_approval: ExecutionApproval

    # Kelly audit
    kelly_inputs: KellyInputs
    kelly_output: KellyOutput

    # Wave audit
    wave_analysis: dict
    wave_phase: str
    wave_confluence_score: float
    near_swing_failure: bool

    # HITL gate
    hitl_required: bool
    hitl_approved_by: Optional[str]
    hitl_approved_at_ms: Optional[int]

    # SAE decision
    sae_checks_passed: List[str]
    sae_checks_failed: List[str]
    sae_decision: str                   # "APPROVED" | "REJECTED" | "KILL_SWITCH"
    sae_rejection_reason: Optional[str]

    # Order (if approved)
    order_id: Optional[str]
    order_params: Optional[dict]
    fill_price: Optional[float]
    fill_size: Optional[float]
    fill_timestamp_utc: Optional[datetime]

    # Treasury
    treasury_triggered: bool
    treasury_btc_converted_usd: float
    treasury_stable_received_usd: float

    # Metadata
    strategy_version: str
    prompt_policy_versions: dict
    mode: str                           # "paper" | "live" | "backtest" | "recovery"
    final_result: str                   # "filled|no_fill|rejected_sae|rejected_risk|rejected_hitl|flat"
    total_latency_ms: int
    agent_latencies_ms: dict
```

### 19.2 Storage

`DecisionTrace` records are:
- Written to Postgres (`decision_traces` table) in real-time
- Also written to a local append-only SQLite database (`data/traces/traces.db`) as a fallback
- Asynchronously replicated to object storage (S3-compatible) for durability
- Never mutated after write — corrections are new records with `correction_of_trace_id` field
- Retained for minimum 365 days

---

## 20. Treasury Management System

The treasury system manages BTC-to-stablecoin conversion to reduce mark-to-market volatility and lock in realized profits.

### 20.1 Conversion Triggers

| Trigger | Default Threshold | Configurable |
|:--|:--|:--|
| BTC price >= rolling 30d high x 1.05 | Convert 20% of BTC balance | Yes |
| Portfolio drawdown >= 5% | Convert 30% of BTC to USDC | Yes |
| Realized PnL threshold | +5% portfolio gain since last conversion | Yes |
| Weekly rebalance | Rebalance to 60% BTC / 40% stablecoin | Yes |
| Time-based | Every 7 days regardless of PnL | Yes |
| Volatility spike | BTC 24h volatility > 2 standard deviations | Yes |
| Manual operator trigger | Via `POST /treasury/convert` | Always |

### 20.2 Constraints

- All conversions executed via HyperLiquid spot markets (BTC/USDC)
- Conversions require 2-of-2 signature (operator + automated system) for amounts above threshold
- Maximum single conversion: 25% of BTC balance
- No conversions during active open positions
- All conversions > configurable USD threshold require HITL approval (see §18)
- Treasury module has no authority to initiate trading positions; spot conversion only
- Full conversion audit log written to `treasury_events` table and included in `DecisionTrace`

### 20.3 Configuration

```json
{
  "policy_id": "treasury_default_v1",
  "target_stable_pct": 30,
  "min_conversion_usd": 500,
  "hitl_threshold_usd": 10000,
  "conversion_algo": "TWAP",
  "conversion_window_minutes": 15,
  "triggers": {
    "pnl_threshold_pct": 5.0,
    "time_interval_days": 7,
    "volatility_zscore_threshold": 2.0,
    "take_profit_pct": 1.05,
    "drawdown_hedge_pct": 0.05
  }
}
```

---

## 21. Quant Layer — `apps/quant/`

The `apps/quant/` module provides deterministic, quantitative signal pre-processing that runs before LLM agents and feeds structured evidence into `ObservationPack`. It has zero LLM calls, zero network calls (feeds are injected), and zero side effects.

**Governance invariant:** No quant module output is ever executable trading authority on its own. All outputs are advisory inputs to LLM agents or penalty inputs to deterministic safety checks.

### 21.1 HyperLiquid Feed Adapter

**Source:** `apps/quant/feeds/hyperliquid_feed.py`

`HyperliquidFeed` produces `HLMarketContext` objects. It operates snapshot-first (REST bootstrap) with WebSocket delta updates and periodic REST reconciliation.

**Key normalizations for HL perps:**
- Funding rate normalized to 8-hour equivalent regardless of venue cadence
- `depth_10bps_usd` computed as order book depth within +/-10bps of mid
- Liquidation clusters expressed as signed distance percentage from current mid
- Bars are closed-bar only — current incomplete bar is never included

**Adapted from:** [Quant-Zero](https://github.com/marcohwlam/quant-zero)

### 21.2 Kelly Sizing Service

**Source:** `apps/quant/sizing/kelly_sizing_service.py`

`KellySizingService` computes a fractional Kelly position size and writes a fully auditable `KellyOutput` into `TradeIntent` and `DecisionTrace`.

**Critical constraint:** `win_prob` and `payoff_ratio` MUST come from validated out-of-sample historical estimates from `apps/jobs/ablation_runner.py` — never from raw LLM confidence scores. A minimum of 30 OOS trades is required before Kelly sizing is active for any `(strategy, asset, regime, direction)` bucket. If the bucket has < 30 OOS trades, emit FLAT.

**Penalty adjustments applied sequentially:**

| Condition | Size Penalty |
|:--|:--|
| `signal_quality < 0.60` | -50% |
| Funding rate > 0.10% per 8h on LONG | -25% |
| Funding rate > 0.20% per 8h on LONG | -50% (replaces -25%) |
| Realized vol z-score > 2.0 | -50% |
| Nearest liq cluster within 1.5% | -50% |
| Adjusted fraction < `KELLY_MIN_NOTIONAL_PCT` (0.5%) | Emit FLAT |
| Result > `KELLY_MAX_NOTIONAL_PCT` (10%) | Hard cap at 10% |

**Governance:** `kelly_inputs` and `kelly_output` are written to `TradeIntent` and persisted in `DecisionTrace`. `FundManager` may reduce `suggested_notional_pct` but must never increase it. SAE enforces its own `position_limit` independently.

**Recall governance rule:** Any strategy reaching KellySizingService must have passed:
1. BacktestResult.GO verdict from ablation_runner.py
2. Manual review by Network Engineering
3. `strategy_registry.yaml` approval
4. 30+ OOS trades in production paper trading mode

### 21.3 Regime Mapper

**Source:** `apps/quant/regimes/regime_mapper.py`

`RegimeMapper` bridges fine-grained `QZRegime` labels to the canonical `MarketRegime` enum.

**Design principle:** `MarketRegime` is an operational (risk-first) enum, not a descriptive one. High-volatility conditions override directional labels because risk control dominates direction in HL perp trading.

| QZRegime | MarketRegime | Rationale |
|:--|:--|:--|
| `trend_up_low_vol` | `TREND_UP` | Clean directional |
| `trend_up_high_vol` | `HIGH_VOL` | Risk control dominates |
| `trend_down_low_vol` | `TREND_DOWN` | Clean directional |
| `trend_down_high_vol` | `HIGH_VOL` | Risk control dominates |
| `range_low_vol` | `RANGE` | Mean-reversion regime |
| `range_high_vol` | `HIGH_VOL` | Execution risk dominates |
| `event_breakout` | `EVENT_RISK` | Structural uncertainty |
| `liquidation_cascade_risk` | `EVENT_RISK` | Structurally unstable |
| `funding_crowded_long` | `EVENT_RISK` | Carry blow-off risk |
| `funding_crowded_short` | `EVENT_RISK` | Carry blow-off risk |

**Dual-field design:** Both `qz_regime` (fine-grained) and `market_regime` (canonical operational) are written to `ObservationPack`. Agents reason with richer context; SAE and FundManager operate on the canonical enum only.

### 21.4 Wave Structure Detector

**Sources:** `apps/quant/signals/wave_detector.py`, `apps/quant/signals/wave_adapter.py`

**Adapted from:** [WaveEdge](https://github.com/koobraelac/wavedge) — wave structure detection algorithm, liquidation-proximity swing detection, and multi-timeframe divergence detection concepts.

**Wave phase classifications:**

| Phase | Meaning |
|:--|:--|
| `IMPULSIVE_UP` | HH + HL sequence, >=3 confirmed legs, no deep retracement |
| `IMPULSIVE_DOWN` | LL + LH sequence, >=3 confirmed legs, no deep retracement |
| `CORRECTIVE_ABC_UP` | Bounded corrective structure pushing price up |
| `CORRECTIVE_ABC_DOWN` | Bounded corrective structure pushing price down |
| `COMPLEX_CORRECTION` | Multi-leg WXY or similar overlapping correction (>6 swings) |
| `TRANSITION` | Structural break — swing sequence violates all patterns — highest uncertainty |
| `UNKNOWN` | Insufficient bars for classification |

**Wave to QZRegime mapping:**

| WavePhase | Confluence >= 0.67 | QZRegime |
|:--|:--|:--|
| `IMPULSIVE_UP` | Yes | `trend_up_low_vol` |
| `IMPULSIVE_UP` | No | `trend_up_high_vol` |
| `IMPULSIVE_DOWN` | Yes | `trend_down_low_vol` |
| `IMPULSIVE_DOWN` | No | `trend_down_high_vol` |
| `CORRECTIVE_ABC_UP/DOWN` | Yes | `range_low_vol` |
| `CORRECTIVE_ABC_UP/DOWN` | No | `range_high_vol` |
| `COMPLEX_CORRECTION` | Either | `range_high_vol` |
| `TRANSITION` | Either | `event_breakout` |
| `UNKNOWN` | Either | `unknown` |

**Key outputs written to `ObservationPack.quantitative_baseline["wave"]`:**

- `wave_phase` — string value of `WavePhase` enum
- `wave_phase_confidence` — [0,1] composite confidence
- `confluence_score` — [0,1] cross-timeframe agreement
- `timeframe_phases` — per-TF phase dict
- `nearest_swing_high` / `nearest_swing_low` — price of nearest confirmed swing
- `nearest_swing_high_distance_pct` / `nearest_swing_low_distance_pct` — % distance from mid
- `has_bearish_divergence` / `has_bullish_divergence` — RSI divergence at swing points only
- `qz_regime_from_wave` / `market_regime_from_wave` — regime from wave analysis

**SAE enrichment (`WaveSAEInputs`):**

- `near_swing_failure: bool` — True when price is within 0.8% of nearest confirmed swing low (LONG) or high (SHORT)
- `swing_failure_price: Optional[float]`
- `swing_failure_distance_pct: Optional[float]`
- `wave_confluence_score: float`

SAE applies a 50% size reduction when `near_swing_failure = True`. This is a penalty, not a veto.

**Critical caveats:**
- Wave labeling is inherently ambiguous. Treat `wave_phase` as strong advisory evidence, not trading authority.
- Run on **closed bars only**.
- HL liquidation spike wicks must be pre-filtered before wave detection runs. `_filter_liq_wicks()` currently flags spikes in logging but does not mutate frozen `HLBar` dataclass objects. **Phase B TODO:** accept mutable bar types and apply actual wick clipping.

### 21.5 ObserverAgent Integration

```python
from apps.quant.signals.wave_adapter import analyze_wave

output = analyze_wave(
    asset=ctx.asset,
    bars_by_tf={
        "4h": ctx.bars_4h,
        "1h": ctx.bars_1h,
        "15m": ctx.bars_15m,
    },
    current_mid_price=ctx.mid_price,
    direction_for_sae="LONG",
)

# Inject into ObservationPack
obs_pack.quantitative_baseline["wave"] = output.observation_dict
obs_pack.swing_high = output.wave_result.nearest_swing_high
obs_pack.swing_low  = output.wave_result.nearest_swing_low

# SAE receives separately — not via ObservationPack
sae_wave_inputs = output.sae_inputs
```

### 21.6 Integration Points Summary

| Quant Component | Consumes | Produces | Used By |
|:--|:--|:--|:--|
| `HyperliquidFeed` | HL REST/WS, IntelliClaw | `HLMarketContext` | `ObserverAgent`, jobs |
| `WaveDetector` + `WaveAdapter` | `HLMarketContext.bars_*`, `mid_price` | `WaveAnalysisResult`, `WaveSAEInputs` | `ObserverAgent`, SAE |
| `QZRegimeClassifier` | `HLMarketContext`, wave phase | `RegimeMappingResult` | `ObserverAgent` |
| `KellySizingService` | OOS stats, signal quality, market context | `KellyOutput` in `TradeIntent` | `TraderAgent`, `FundManager` |

---

## 22. Orchestrator API

### 22.1 Endpoints

| Method | Path | Description |
|:--|:--|:--|
| `POST` | `/cycles/trigger` | Trigger a new decision cycle |
| `GET` | `/cycles/:id` | Get cycle status |
| `GET` | `/traces/:id` | Get full DecisionTrace |
| `GET` | `/traces` | List traces (paginated, filterable) |
| `POST` | `/control/halt` | Emergency halt all cycles |
| `POST` | `/control/resume` | Resume after halt |
| `POST` | `/control/emergency-close` | Immediate flat of all positions |
| `POST` | `/governance/hitl-rules` | Update HITL ruleset |
| `POST` | `/governance/hitl-rules/:rule/approve` | Human approval for open HITL gate |
| `POST` | `/governance/prompt-policies/promote` | Promote prompt-policy version |
| `POST` | `/governance/strategies/promote` | Promote strategy version |
| `POST` | `/sae/policies/reload` | Hot-reload SAE policy |
| `PUT` | `/sae/policies` | Adjust SAE leverage, size, and drawdown policy parameters |
| `PUT` | `/config/strategy` | Update strategy configuration for the paper bot |
| `GET` | `/status` | System health |
| `GET` | `/metrics` | Prometheus scrape endpoint |
| `GET` | `/treasury/status` | Current treasury state and conversion history |
| `POST` | `/research/jobs` | Initiate a ResearchClaw job |
| `GET` | `/research/jobs/:id` | Poll ResearchClaw job status and stage progress |
| `GET` | `/research/hypotheses` | List approved and pending HypothesisSet entries |

### 22.2 Cycle Trigger Request

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

## 23. Autonomous AI Optimization Agent

The `optimizer_agent` operates entirely **off the hot path** and is never part of the live decision cycle. It is a long-running background process that:

- Analyzes `DecisionTrace` artifacts and `ablation_results` from Postgres
- Identifies patterns in which prompt-policy versions, analyst configurations, or strategy parameters correlate with improved metrics (Sharpe, drawdown, hit rate)
- Generates candidate prompt-policy version proposals and evaluation reports
- Submits proposals to the `prompt_policy_scorer.py` evaluation harness
- Posts recommendations to the governance queue for human review via OpenClaw
- **Never** promotes its own proposals autonomously — all promotions require human approval through the Clawvisor HITL system

---

## 24. Safety Architecture — Invariants

These invariants **must** hold in all modes, verified by architecture tests:

1. No `ExecutionRequest` reaches an Executor without a passing `ExecutionDecision` from SAE
2. No `ExecutionDecision` is issued without an `ExecutionApproval` from Fund Manager
3. No live-mode cycle completes without HITL approval when the active ruleset requires it
4. All DecisionTrace artifacts are written atomically before fill reconciliation
5. SAE has no LLM dependency — it is a deterministic rule engine only
6. Strategy version changes require Clawvisor HITL approval before taking effect in live mode
7. Prompt-policy versions are immutable once promoted; only new versions may be created
8. Treasury module cannot open positions; it may only submit spot conversion orders after HITL approval when above threshold
9. The agent has **no write path** to `VAULT_SUBACCOUNT_ADDRESS`, `HL_PRIVATE_KEY`, or any K8s Secret value
10. ResearchClaw outputs are READ-ONLY proposals until `HypothesisSet.approved = true` is set by a human via the dashboard
11. No `print()` / `logger.*` may emit a secret value at any log level

---

## 25. Storage Schema

### 25.1 Key Postgres Tables

| Table | Primary Key | Purpose |
|:--|:--|:--|
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
| `governance_events` | `event_id` | All governance actions |
| `recovery_state` | `service_name` | Last known safe state per service |
| `ablation_results` | `(run_id, variant)` | Ablation experiment outputs |
| `treasury_events` | `event_id` | Conversion triggers, approvals, fills |
| `optimizer_runs` | `run_id` | Autonomous optimization agent outputs |

### 25.2 SQLite (Local Fallback)

```sql
-- experiments.db
CREATE TABLE experiments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    timestamp   INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    score_json  TEXT NOT NULL,
    sharpe      REAL,
    max_dd      REAL,
    kept        INTEGER DEFAULT 0,
    rationale   TEXT
);

CREATE TABLE paper_outcomes (...);  -- PaperTradeOutcome records
CREATE TABLE rl_aggregates (
    run_id TEXT,
    window_hours REAL,
    sharpe REAL,
    win_rate REAL,
    avg_edge_bps REAL,
    worst_trade_pct REAL,
    funding_drag REAL,
    meets_promotion_criteria INTEGER
);
```

---

## 26. Observability and Alerting

### 26.1 Metric Categories

**Trading metrics:** cumulative return, annualized return, Sharpe ratio, max drawdown, hit rate, turnover, exposure concentration, avg holding period, slippage bps

**Process metrics:** cycle latency P50/P95/P99, analyst latency per role, debate duration, debate rounds per cycle, veto frequency, no-trade frequency, HITL approval time, treasury conversion frequency

**Safety metrics:** SAE rejection frequency per check, stale-data incident count, risk committee disagreement rate, human override count, recovery entry count, prompt-policy rollback count, optimizer recommendation adoption rate

### 26.2 Alerting Thresholds

| Alert | Condition |
|:--|:--|
| `trading.drawdown.critical` | Portfolio drawdown > 6% |
| `safety.stale_data` | Market snapshot age > 90s in live mode |
| `safety.sae_rejection_spike` | SAE rejection rate > 30% over 10 cycles |
| `process.cycle_latency` | Cycle P95 latency > 8s |
| `infra.agent_service_down` | Agent service health check fails > 30s |
| `treasury.conversion_failed` | Treasury conversion order not filled within 30 min |

---

## 27. Dashboard

The research dashboard (`apps/dashboard/`) provides:

### 27.1 Market Research View
- Last 365 days of 1-minute candles per market (HL `candleSnapshot` API + local time-series store)
- Strategy entry/exit markers and regime annotations

### 27.2 P/L View
- Paper P/L, live P/L, vault balance, drawdown events, and promotion events
- Cumulative P/L, daily P/L, rolling Sharpe ratio, max drawdown, win rate
- Fees paid, funding paid/received, reserved profit sent to vault

### 27.3 System Status
- Current mode: `backtest | paper | live | recovery`
- Experiment history, accepted/rejected strategies, promotion events
- Risk and halt status

### 27.4 Research Panel
- ResearchClaw job queue (stage X/23 progress), artifact browser
- Hypothesis feed with approve/reject controls
- Literature citation cache
- The approve action is the only path that sets `HypothesisSet.approved = true`

### 27.5 Implementation
- Backend: FastAPI or similar lightweight Python service
- Frontend: React / Next.js
- Storage: SQLite for metadata, Parquet or DuckDB for candle history and trades
- Auth: SSO or reverse-proxy auth; dashboard must not expose secrets or raw API keys

---

## 28. Repository Structure

```
hyperliquid-trading-firm/
├── README.md
├── SPEC-v3.md                          ← this file
├── AGENTS.md                           ← agent edit boundaries and rules
├── CLAUDE.md                           ← Claude-specific guidance
├── DEVELOPMENT_PLAN.md
├── LICENSE
├── Makefile
├── docker-compose.yml
├── .env.example
│
├── proto/
│   ├── common.proto                    # Meta, Direction, TradeMode, MarketRegime
│   ├── decisioning.proto               # ResearchPacket, DebateOutcome, TradeIntent
│   ├── risk.proto                      # RiskVote, RiskReview, ExecutionApproval
│   ├── execution.proto                 # ExecutionRequest, ExecutionDecision, FillReport
│   └── controlplane.proto              # OpenClaw API types, HITLRuleSet
│
├── apps/
│   ├── orchestrator-api/               # TypeScript/Node — cycle coordinator, public API
│   ├── agents/                         # Python — TradingAgents-based multi-agent pipeline
│   │   ├── tradingagents/              # git submodule: TauricResearch/TradingAgents
│   │   ├── adapters/                   # HL-specific adapters
│   │   ├── src/
│   │   │   ├── agents/                 # Analyst stubs (sentiment, fundamental, etc.)
│   │   │   ├── tools/                  # intelliclaw_client.py
│   │   │   └── types/                  # intel.py
│   │   ├── analysts/                   # fundamental, sentiment, news, technical, onchain
│   │   ├── researchers/                # bull.py, bear.py
│   │   ├── debate/                     # facilitator.py
│   │   ├── trader/                     # trader_agent.py
│   │   ├── risk/                       # aggressive.py, neutral.py, conservative.py
│   │   ├── fund_manager/              # fund_manager_agent.py
│   │   └── optimizer/                  # optimizer_agent.py
│   ├── quant/                          # Deterministic quant pre-processing
│   │   ├── feeds/                      # hyperliquid_feed.py
│   │   ├── signals/                    # wave_detector.py, wave_adapter.py
│   │   ├── regimes/                    # regime_mapper.py
│   │   └── sizing/                     # kelly_sizing_service.py
│   ├── sae-engine/                     # TypeScript/Node — policy engine, hard gates
│   ├── executors/                      # Python — HL paper + live venue adapters
│   ├── treasury/                       # Python — BTC-to-stablecoin conversion
│   ├── jobs/                           # backtests, ablations, prompt scoring
│   └── dashboard/                      # Next.js — decision traces, governance, experiments UI
│
├── packages/
│   ├── schemas/                        # Generated JSON schemas + TS/Python shared models
│   ├── prompt-policies/                # Versioned prompt templates
│   └── strategy-sdk/                   # Plugin API for strategy modules
│
├── config/
│   ├── env/                            # Per-environment .env overlays
│   ├── policies/                       # SAE policy YAML files
│   ├── strategies/                     # Strategy configuration JSON
│   ├── hitl-rulesets/                  # Clawvisor HITL JSON rulesets
│   └── model-routing/                  # LLM model routing tables
│
├── strategy/
│   ├── strategy_base.py                # Locked interface
│   ├── strategy_paper.py               # AGENT-EDITABLE
│   ├── strategy_live.py                # Written by promotion logic only
│   └── strategy_vault.py               # Vault pct config
│
├── agent/                              # Core runtime
│   ├── main.py                         # Orchestrator
│   ├── exchange.py                     # HL SDK, auth, rate limit (locked)
│   ├── safety.py                       # Kill switches, recovery trigger (locked)
│   ├── harness.py                      # Backtest + scoring (locked)
│   ├── iteration_loop.py              # Autoresearch engine (locked)
│   ├── paper_bot.py                    # Continuous paper trader (locked)
│   ├── live_bot.py                     # Live trader with vault (locked)
│   ├── rl_buffer.py                    # Reinforcement data store (locked)
│   └── recovery.py                     # Recovery mode state machine (locked)
│
├── multiclaw/                          # User-directed research layer (non-execution path)
│   ├── AutoResearchClaw/               # 23-stage autonomous research pipeline
│   ├── researchclaw-skill/             # OpenClaw skill wrapper
│   ├── research-bridge/                # Adapter: context injector, output parser
│   └── mlflow/                         # MLflow experiment tracking stack
│
├── prompts/
│   └── research/                       # ResearchClaw prompt templates
│
├── logs/
│   ├── research/
│   │   ├── artifacts/                  # Read-only research outputs
│   │   ├── approved_hypotheses/        # Human-approved hypotheses for iter loop
│   │   └── research_registry.db
│   ├── experiments.db
│   └── experiments.jsonl
│
├── infra/
│   ├── k8s/                            # Kubernetes manifests
│   ├── argocd/                         # GitOps application definitions
│   ├── terraform/                      # Cloud infrastructure
│   └── observability/                  # Prometheus, Grafana, Loki configs
│
├── docs/
│   ├── intelliclaw.md
│   ├── analysts.md
│   ├── research.md
│   ├── architecture.md
│   ├── api-contracts.md
│   ├── treasury.md
│   └── runbooks/
│
└── tests/
    ├── contract/                       # Proto/schema contract tests
    ├── integration/                    # Service-to-service tests
    ├── simulation/                     # Paper trade simulation tests
    └── chaos/                          # Fault injection and recovery tests
```

---

## 29. Configuration and Environment

All configuration is loaded from environment variables. No secrets in source.

### 29.1 Required Environment Variables

```bash
# HyperLiquid
HL_API_KEY=
HL_API_SECRET=
HL_WALLET_ADDRESS=
HL_PRIVATE_KEY=                         # K8s Secret only
HL_TESTNET=true
VAULT_SUBACCOUNT_ADDRESS=               # K8s Secret only

# Trade mode
TRADE_MODE=paper                        # paper | live

# LLM
LLM_PROVIDER=anthropic
LLM_MODEL=claude-opus-4-5
LLM_API_KEY=
LLM_MAX_TOKENS=4096

# IntelliClaw
INTELLICLAW_URL=http://intelliclaw:8080
INTELLICLAW_API_KEY=
INTELLICLAW_CACHE_TTL=60

# MLflow
MLFLOW_TRACKING_URI=http://multiclaw-mlflow:5000

# Safety limits — SAE
SAE_MAX_NOTIONAL_PCT=10
SAE_MAX_NOTIONAL_USD=50000
SAE_MAX_LEVERAGE=5
SAE_MAX_SPREAD_BPS=50
SAE_MAX_FUNDING_LONG=0.0030
SAE_MAX_VOL_ZSCORE=3.0
SAE_MIN_LIQ_DISTANCE_PCT=0.5
SAE_MAX_DAILY_DD_PCT=3.0
SAE_HEARTBEAT_TIMEOUT_SECONDS=30
KILL_SWITCH=false
EMERGENCY_FLATTEN=false

# Fund manager
FUND_MAX_SINGLE_POSITION_PCT=10
FUND_MAX_CORRELATED_EXPOSURE_PCT=25
FUND_MAX_GROSS_EXPOSURE_PCT=200
FUND_MAX_CONCURRENT_POSITIONS=5
FUND_MIN_BARS_BETWEEN_TRADES=4

# Kelly sizing
KELLY_MAX_NOTIONAL_PCT=10
KELLY_MIN_NOTIONAL_PCT=0.5
KELLY_MAX_FRACTION=0.25

# Treasury
TREASURY_TAKE_PROFIT_PCT=1.05
TREASURY_CONVERT_PCT=0.20
TREASURY_DRAWDOWN_HEDGE_PCT=0.05
TREASURY_DRAWDOWN_CONVERT_PCT=0.30
TREASURY_TARGET_BTC_PCT=0.60
TREASURY_MAX_SINGLE_CONVERT_PCT=0.25

# Infra
LOG_LEVEL=INFO
TRACE_DB_PATH=data/traces/traces.db
S3_TRACE_BUCKET=
```

### 29.2 API Key Security

- Trading keys: minimum permissions — place/cancel orders, read positions only
- Read-only keys: separate key for data feeds, monitoring dashboards
- Never log API keys; mask in all trace output
- Rotate on any suspected compromise; KILL_SWITCH immediately on rotation

---

## 30. Phased Build Plan

### Phase A — Foundation (Current)

**Exit criteria:** Paper trading with live data for 30 days, Sharpe > 0.8, max drawdown < 8%, zero SAE bypass incidents.

Deliverables:

- [x] `HyperliquidFeed` — REST/WS feed with reconciliation
- [x] `WaveDetector` + `WaveAdapter` — wave structure detection
- [x] `KellySizingService` — fractional Kelly with OOS gating
- [x] `RegimeMapper` — QZRegime to MarketRegime
- [ ] `ObserverAgent` — assembles `ObservationPack`
- [ ] Analyst agents (5 specialists)
- [ ] Debate agent framework — BullAgent, BearAgent, NeutralAgent
- [ ] `TraderAgent`
- [ ] `RiskCommitteeAgent`
- [ ] `FundManager`
- [ ] SAE with full pre-execution checks
- [ ] `DecisionTrace` storage and audit
- [ ] Paper trading harness
- [ ] Orchestrator API
- [ ] Dashboard (basic)

**Phase A known TODOs:**
- `wave_detector.py`: `_filter_liq_wicks()` logs spike events but does not mutate frozen `HLBar` objects. Requires mutable bar types.
- `KellySizingService`: OOS bucket statistics are manually seeded. Phase B wires `ablation_runner.py` output directly.

### Phase B — Live Trading (Planned)

**Exit criteria:** Live trading with real capital for 60 days at 10% max position size. Sharpe > 1.0 live vs paper. All Phase A TODOs closed.

Deliverables:
- Mutable bar types for liq spike wick clipping
- `ablation_runner.py` → `KellySizingService` automatic OOS stat pipeline
- Treasury management system
- Multi-asset support (ETH-PERP, SOL-PERP)
- Correlation matrix for FundManager
- Live monitoring dashboard
- Clawvisor HITL system
- OpenClaw control plane adapter
- Optimizer agent (off-path)

### Phase C — Scale (Future)

- Increased position limits with extended track record
- Additional strategy families (mean reversion, basis)
- Automated regime-adaptive parameter tuning
- Cross-venue arbitrage monitoring

---

## 31. Limitations and Scope Constraints

The following items are **explicitly out of scope**:

- Cross-exchange arbitrage or multi-venue execution
- Equity, options, or non-perpetual instruments
- Fully autonomous live trading without HITL approval (always required in v1 live)
- Self-modifying strategy logic without explicit promotion gates
- Any AI-generated reasoning placed directly in an execution path without SAE review
- Treasury module initiating leveraged positions (spot conversion only)

The TradingAgents paper's reported performance (26-27% cumulative return, Sharpe 6-8) was measured over a narrow Q1 2024 simulation window on selected US equities. These results should be treated as **design validation evidence only, not live trading performance targets**. All performance claims for this system require independent walk-forward validation in paper mode before any live deployment decision.

---

## 32. References

- TradingAgents paper: https://arxiv.org/pdf/2412.20138
- TauricResearch/TradingAgents: https://github.com/TauricResearch/TradingAgents
- FinArena paper (multi-agent trading evaluation): https://arxiv.org/abs/2509.11420
- HyperLiquid API docs: https://hyperliquid.gitbook.io/hyperliquid-docs
- Quant-Zero (signal architecture, Kelly framework): https://github.com/marcohwlam/quant-zero
- WaveEdge (wave structure detection, swing levels): https://github.com/koobraelac/wavedge
- Haiku trading agent framework: https://docs.haiku.trade/
- This repo: https://github.com/enuno/hyperliquid-trading-firm
- DEVELOPMENT_PLAN.md: phased build plan with exit gates
