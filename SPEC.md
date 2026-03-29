# hyperliquid-trading-firm — System Specification

> **Version:** 2.2.0
> **Last updated:** 2026-03-29
> **Status:** Active development — paper trading target
> **Repo:** https://github.com/enuno/hyperliquid-trading-firm

---

## 1. Purpose and Scope

`hyperliquid-trading-firm` is an **auditable, modular, multi-agent LLM trading system** targeting
HyperLiquid perpetuals. It is modeled after the organizational structure of a real trading firm,
implementing the architecture described in the
[TradingAgents paper (arXiv 2412.20138)](https://arxiv.org/pdf/2412.20138) and the
[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) open-source
framework, further extended by the arena-style debate and observer-layer architecture from the
[FinArena paper (arXiv 2509.11420)](https://arxiv.org/abs/2509.11420).

The system extends the base TradingAgents framework with:

- A **ObserverAgent layer** that normalizes, tags, and contextualizes raw market data before
  analysts ever receive it, improving context construction quality and information traceability
- An **information partitioner** that deliberately creates asymmetric information subsets for
  each debater, surfacing genuine disagreement that a single-context agent misses
- An **arena-style multi-round debate panel** (3–5 debaters) with per-round belief revision
  tracking — replacing the single bull/bear pair with a heterogeneous panel initialized with
  different information subsets and different backbone LLM providers
- An **ArbitratorAgent** that evaluates evidence quality across debate rounds, assigns
  conviction-weighted outcomes, and mandates HOLD when evidence quality is insufficient
- A **Safety Approval Engine (SAE)** — non-bypassable deterministic pre-execution policy
  enforcement including new crypto-native checks for debate evidence quality and liquidation
  cluster proximity
- An **OpenClaw control plane** adapter for operator governance, HITL gating, and strategy
  lifecycle management
- A **Clawvisor HITL ruleset** system for operator-defined human approval requirements
- An **autonomous AI agent layer** for continuous performance optimization and monitoring
- A **treasury management module** — automated BTC-to-stablecoin conversion for risk
  management and profitability from Bitcoin price volatility
- Full **DecisionTrace** persistence so every trade decision is replayable and attributable
- A **reflection and continuous-improvement loop** for post-trade analysis and prompt-policy
  evolution (off the hot path)

### What This System Does

The system operates as an autonomous, AI-driven trading organization on HyperLiquid:

1. **Observes** — `ObserverAgent` normalizes raw market data, onchain signals, news, and
   sentiment into a structured `ObservationPack` with staleness metadata and a `regime_tag`
2. **Partitions** — `InformationPartitioner` creates asymmetric information subsets so each
   debater reasons from a distinct (but overlapping) evidence base
3. **Analyzes** — Five specialist analysts (fundamental, sentiment, news, technical, onchain)
   produce typed `AnalystScore` objects assembled into a `ResearchPacket`
4. **Debates** — A 3-debater panel (bull-initialized, bear-initialized, neutral) runs N rounds
   of cross-examination in the arena; each debater's conviction score is tracked per round
5. **Arbitrates** — `ArbitratorAgent` resolves the debate with an evidence-quality score and
   `ArbitratorVerdict`; mandates HOLD if evidence is too thin
6. **Synthesizes** — Trader agent produces a typed `TradeIntent` incorporating belief revision
   delta and funding-rate-adjusted leverage
7. **Reviews** — Three-profile risk committee and fund manager govern position sizing
8. **Gates** — Non-bypassable SAE and optional Clawvisor HITL approval before execution
9. **Executes** — HyperLiquid paper or live markets via staged execution requests
10. **Learns** — Post-trade reflection, ablation evaluation, and optimizer agent recommendations

This system treats **live execution as safety-critical**. No LLM output is ever executable
trading authority on its own. All adaptation happens off the hot path.

---

## 2. Design Principles

| Principle | Implementation |
|---|---|
| Observer-first context construction | Raw data normalized by ObserverAgent before analysts; reduces context errors |
| Information asymmetry in debate | Partitioner gives each debater a distinct evidence subset |
| Evidence-citation requirement | Every debate claim must reference a specific ObservationPack artifact |
| Belief revision as signal | Per-round conviction delta tracked; large negative delta compresses position size |
| Arbitrated deadlock resolution | ArbitratorAgent mandates HOLD when evidence quality < threshold |
| Model heterogeneity | Different LLM providers assigned to different roles to reduce correlated reasoning failure |
| Role specialization | Separate analyst, debate, trader, risk, fund-manager agents |
| Structured state over prompt chaining | Typed JSON/protobuf artifacts at every handoff |
| Hard safety gates | SAE enforces policy; cannot be bypassed by any agent or operator |
| Full auditability | Every artifact keyed on `cycle_id`; DecisionTrace persisted immutably |
| Adaptation off the hot path | Prompt-policy changes require versioned promotion gates |
| No-trade is a first-class outcome | HOLD/FLAT emitted when consensus is weak, evidence thin, or risks unresolved |
| Live execution requires human approval | Clawvisor HITL ruleset gates all live-mode cycles |
| Autonomous optimization | Optimizer agent continuously evaluates performance off the hot path |
| Treasury-aware profitability | BTC-to-stablecoin conversion integrated into risk management |

---

## 3. Repository Structure

```text
hyperliquid-trading-firm/
├─ README.md
├─ SPEC.md                              ← this file
├─ DEVELOPMENT_PLAN.md
├─ LICENSE
├─ Makefile
├─ docker-compose.yml
├─ docker-compose.paper.yml
├─ docker-compose.live.yml
├─ .env.example
│
├─ proto/
│  ├─ common.proto
│  ├─ decisioning.proto                 # ObservationPack, ResearchPacket, DebateOutcome (updated),
│  │                                    # ArbitratorVerdict, TradeIntent
│  ├─ risk.proto
│  ├─ execution.proto
│  └─ controlplane.proto
│
├─ apps/
│  ├─ orchestrator-api/
│  ├─ agents/
│  │  ├─ tradingagents/                 # git submodule: TauricResearch/TradingAgents
│  │  ├─ adapters/
│  │  ├─ observer/                      # NEW (FinArena)
│  │  │  ├─ observer_agent.py           # Normalizes raw data → ObservationPack
│  │  │  └─ information_partitioner.py  # Creates asymmetric subsets per debater
│  │  ├─ analysts/
│  │  │  ├─ fundamental.py
│  │  │  ├─ sentiment.py
│  │  │  ├─ news.py
│  │  │  ├─ technical.py
│  │  │  └─ onchain.py
│  │  ├─ debate/
│  │  │  ├─ arena_facilitator.py        # REPLACES facilitator.py — multi-round cross-examination
│  │  │  ├─ arbitrator_agent.py         # NEW (FinArena) — resolves deadlock
│  │  │  ├─ debater_a.py                # REPLACES bull.py — configurable init stance
│  │  │  ├─ debater_b.py                # REPLACES bear.py
│  │  │  └─ debater_c.py                # NEW — neutral debater
│  │  ├─ trader/
│  │  │  └─ trader_agent.py
│  │  ├─ risk/
│  │  │  ├─ aggressive.py
│  │  │  ├─ neutral.py
│  │  │  └─ conservative.py
│  │  ├─ fund_manager/
│  │  │  └─ fund_manager_agent.py
│  │  └─ optimizer/
│  │     └─ optimizer_agent.py
│  ├─ sae-engine/
│  ├─ executors/
│  │  ├─ hyperliquid_paper.py
│  │  ├─ hyperliquid_live.py
│  │  └─ fill_reconciler.py
│  ├─ treasury/
│  │  ├─ treasury_manager.py
│  │  └─ conversion_policy.py
│  ├─ jobs/
│  │  ├─ backtest_runner.py
│  │  ├─ ablation_runner.py
│  │  └─ prompt_policy_scorer.py
│  └─ dashboard/
│
├─ packages/
│  ├─ schemas/
│  ├─ prompt-policies/
│  │  ├─ observer/v1/                   # NEW
│  │  ├─ analyst/
│  │  ├─ debater-a/v1/                  # REPLACES bull/
│  │  ├─ debater-b/v1/                  # REPLACES bear/
│  │  ├─ debater-c/v1/                  # NEW
│  │  ├─ arbitrator/v1/                 # NEW
│  │  ├─ trader/
│  │  ├─ risk-aggressive/
│  │  ├─ risk-neutral/
│  │  ├─ risk-conservative/
│  │  └─ fund-manager/
│  └─ strategy-sdk/
│
├─ config/
│  ├─ env/
│  ├─ policies/
│  ├─ strategies/
│  ├─ hitl-rulesets/
│  ├─ debate-panels/                    # NEW — panel composition configs
│  │  ├─ panel_3_default.json
│  │  └─ panel_5_aggressive.json
│  └─ model-routing/
│     └─ heterogeneous_v1.json          # NEW — per-role provider routing
│
├─ strategy/
│  ├─ strategy_paper.py
│  ├─ strategy_live.py
│  └─ trading_program.md
│
├─ infra/
│  ├─ k8s/
│  ├─ argocd/
│  ├─ terraform/
│  └─ observability/
│
├─ docs/
│  ├─ architecture.md
│  ├─ api-contracts.md
│  ├─ protobuf.md
│  ├─ tradingagents-integration.md
│  ├─ finarena-integration.md           # NEW — FinArena adoption and crypto adaptation notes
│  ├─ treasury.md
│  └─ runbooks/
│
└─ tests/
   ├─ contract/
   ├─ integration/
   ├─ simulation/
   └─ chaos/
```


---

## 4. Framework Integration

### 4.1 TradingAgents (TauricResearch/TradingAgents)

The base TradingAgents framework provides the analyst agent hierarchy, trader synthesis pattern,
risk management team structure, fund manager approval pattern, and backbone LLM routing concept.
See `docs/tradingagents-integration.md` for full adoption details.

### 4.2 FinArena Integration (arXiv 2509.11420)

The [FinArena paper](https://arxiv.org/abs/2509.11420) introduces arena-style multi-agent debate
with structured evidence citation, belief revision tracking, and arbitrated deadlock resolution.
These patterns are adopted and extended for crypto perpetuals.

**What is adopted unchanged:**

- Observer → Analyst → Debater → Arbitrator pipeline layering
- Multi-round cross-examination debate structure
- Evidence-citation requirement for all debate claims
- Confidence-calibrated abstention (mandate HOLD when evidence quality insufficient)
- Belief revision tracking per debater per round

**What is extended for crypto perps:**

- Observer adds crypto-native signals: funding rate regime, OI-weighted liquidation levels,
perp basis (spot vs perp spread), whale vault flows, BTC dominance delta, regime tag
- Debater initialization includes forced-bearish stance to counter equities-trained LLM
bullish recency bias from 2020–2024 training data
- `funding_rate_adjusted_leverage` computed in TraderAgent to penalize carry cost on longs
- `liquidation_proximity` SAE check rejects or size-reduces trades near dense liq clusters
- `regime_tag` added to ObservationPack to contextualize LLM reasoning

**What remains unproven for live crypto:**

- Arena debate improvement over single bull/bear pair is validated on equities backtests only;
crypto perps walk-forward validation required before trusting performance claims
- 3-debater panel vs 2-debater performance difference unvalidated; ablation required
- Belief revision delta as a direct sizing signal is a novel extension not in the paper


### 4.3 Model Heterogeneity

FinArena recommends using different LLM providers for different roles to reduce correlated
reasoning failure. This is implemented as `config/model-routing/heterogeneous_v1.json`.


| Role | Provider | Rationale |
| :-- | :-- | :-- |
| Observer, sentiment, technical, onchain | OpenAI GPT-4o-mini | High-volume normalization/classification |
| News, fundamental synthesis | OpenAI GPT-4o | Domain reasoning |
| Debater A (bull-init) | Anthropic Claude Opus | Different reasoning bias from OpenAI |
| Debater B (bear-init) | OpenAI o3 | Strong adversarial reasoning |
| Debater C (neutral) | Google Gemini Ultra | Third-party perspective |
| Arbitrator | Anthropic Claude Opus | Highest evidence evaluation quality |
| Trader | OpenAI o3 | Final synthesis |
| Risk committee (×3) | OpenAI GPT-4o | Parallel profile evaluation |
| Fund manager | Anthropic Claude Opus | Portfolio constraint enforcement |
| SAE | Deterministic rule engine | No LLM |

Provider failover: if primary provider is unavailable, fall back to OpenAI for the same role
before marking cycle as failed.

---

## 5. Runtime Architecture

### 5.1 Decision Cycle Flow

```
1.  INGEST         Market snapshot (HL OHLCV + OB + funding rate + OI)
                   + IntelliClaw intel feed
                   + Sentiment/news (with bot-filter weights)
                   + Onchain signals (vault flows, liq map, whale tracker)

2.  OBSERVE        ObserverAgent normalizes all sources → ObservationPack
                   Tags: regime_tag, staleness, has_critical_gap
                   → If has_critical_gap == true: emit FLAT, skip cycle

3.  PARTITION      InformationPartitioner assigns asymmetric subsets:
                   debater_a_subset, debater_b_subset, debater_c_subset

4.  ANALYZE        5 specialist analysts → ResearchPacket
                   [fundamental, sentiment, news, technical, onchain]
                   Each analyst receives full ObservationPack

5.  DEBATE         3-debater arena (A=bull-init, B=bear-init, C=neutral)
                   Each debater initialized with distinct information subset
                   N rounds cross-examination; claims must cite ObservationPack artifacts
                   Per-round conviction scores tracked → belief revision deltas computed
                   → If consensus_strength < threshold: mandate FLAT

6.  ARBITRATE      ArbitratorAgent evaluates claim evidence quality
                   → ArbitratorVerdict: winner, evidence_quality_score,
                      arbitrator_confidence, mandate_hold
                   → If mandate_hold == true: emit FLAT

7.  TRADE          Trader agent synthesizes ResearchPacket + DebateOutcome
                   + funding_rate_adjusted_leverage
                   → TradeIntent [action, confidence, notional_pct, rationale]

8.  RISK           3 risk profiles evaluate TradeIntent + ArbitratorVerdict in parallel
                   → RiskVote × 3 → RiskReview [committee_result, net_size_cap]
                   Arbitrator confidence is input to risk sizing

9.  FUND MGR       Fund manager applies portfolio constraints
                   → ExecutionApprovalRequest → ExecutionApproval

10. HITL GATE      Clawvisor HITL ruleset evaluated
                   → If required: pause for human approval via OpenClaw

11. SAE            Deterministic policy checks (no LLM):
                   position_limit, portfolio_drawdown, daily_loss_limit,
                   leverage_cap, liquidity_gate, correlation_gate,
                   stale_data, funding_rate, event_blackout,
                   debate_evidence_quality (NEW), liquidation_proximity (NEW)
                   → ExecutionDecision [allowed, checks_passed/failed, staged_requests]

12. EXECUTE        Executor submits staged requests to HyperLiquid
                   → FillReport(s)

13. RECONCILE      Fill reconciler updates portfolio state

14. PERSIST        DecisionTrace written atomically to Postgres

15. TREASURY       Treasury manager evaluates realized PnL → conversion if triggered

16. REFLECT        Post-trade jobs (off hot path):
                   prompt-policy scoring, ablation contribution, optimizer recommendations
```


### 5.2 No-Trade Conditions

The system **must** emit `action: FLAT` when any of the following are true:

- `observation_pack.has_critical_gap == true`
- `debate_outcome.consensus_strength < config.min_consensus_threshold`
- `debate_outcome.arbitrator_verdict.mandate_hold == true`
- `debate_outcome.arbitrator_verdict.evidence_quality_score < config.min_evidence_quality`
- `risk_review.committee_result == "reject"` with `require_unanimous_for_live == true`
- `execution_approval.approved == false`
- `sae_decision.allowed == false`
- HITL gate open and timeout not expired
- Any analyst `data_gap: true`
- Market snapshot age > 60s


### 5.3 Time Horizon Policy

LLM-based decisions operate only on **4h candle close or longer** timeframes. Sub-4h signals
may feed the Observer layer as observations but must never be the primary trigger for a decision
cycle. The effective latency of LLM reasoning (6h+) makes intraday scalps structurally
incompatible with this architecture.


| Horizon Class | HL Perps Mapping | Cycle Trigger |
| :-- | :-- | :-- |
| Swing | 4h–24h | 4h candle close |
| Trend | 1d–7d | Daily close |
| Scalp | <4h | NOT SUPPORTED |


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
  REGIME_UNSPECIFIED       = 0;
  TREND_UP                 = 1;
  TREND_DOWN               = 2;
  RANGE                    = 3;
  EVENT_RISK               = 4;
  HIGH_VOL                 = 5;
  ALTSEASON                = 6;
  BTC_DOMINANCE_RISING     = 7;
  DERISKING                = 8;
}
```


### 6.2 Decisioning (decisioning.proto)

```protobuf
// NEW — ObservationPack (FinArena observer layer)
message ObservationEntry {
  string source             = 1;
  string type               = 2;
  string content            = 3;
  double confidence         = 4;
  int32  staleness_seconds  = 5;
}

message InformationSubset {
  string debater_id         = 1;
  repeated string sources   = 2;
}

message ObservationPack {
  tradingfirm.common.Meta       meta               = 1;
  repeated ObservationEntry     observations       = 2;
  repeated InformationSubset    subsets            = 3;
  tradingfirm.common.MarketRegime regime_tag       = 4;
  bool                          has_critical_gap   = 5;
  double                        funding_rate_8h    = 6;
  double                        liq_cluster_distance_pct = 7;
  double                        btc_dominance_delta = 8;
}

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
  string                          observation_pack_id = 10;
}

// UPDATED — DebateOutcome with belief revision tracking (FinArena)
message DebaterClaim {
  string          debater_id      = 1;
  string          claim           = 2;
  repeated string evidence_refs   = 3;
  double          conviction      = 4;
  double          revision_delta  = 5;
  string          revised_due_to  = 6;
}

message DebateRound {
  uint32                  round  = 1;
  repeated DebaterClaim   claims = 2;
}

message ArbitratorVerdict {
  string  winner                   = 1;  // bull|bear|inconclusive
  double  evidence_quality_score   = 2;
  double  arbitrator_confidence    = 3;
  string  reasoning                = 4;
  bool    mandate_hold             = 5;
}

message DebateOutcome {
  tradingfirm.common.Meta   meta                  = 1;
  uint32                    panel_size            = 2;
  repeated DebateRound      rounds                = 3;
  ArbitratorVerdict         arbitrator_verdict    = 4;
  double                    net_conviction_delta  = 5;
  double                    consensus_strength    = 6;
  repeated string           open_risks            = 7;
}

message TradeIntent {
  tradingfirm.common.Meta      meta                         = 1;
  string                       asset                        = 2;
  tradingfirm.common.Direction action                       = 3;
  double                       thesis_strength              = 4;
  double                       confidence                   = 5;
  double                       target_notional_pct          = 6;
  double                       preferred_leverage           = 7;
  double                       funding_rate_adjusted_leverage = 8;  // NEW
  uint32                       max_slippage_bps             = 9;
  string                       time_horizon                 = 10;
  repeated string              required_conditions          = 11;
  string                       rationale                    = 12;
}
```


### 6.3 Risk (risk.proto)

```protobuf
message RiskVote {
  tradingfirm.common.Meta meta                      = 1;
  string                  profile                   = 2;
  bool                    approve                   = 3;
  double                  size_cap_pct              = 4;
  repeated string         objections                = 5;
  double                  arbitrator_confidence_input = 6;  // NEW
}

message RiskReview {
  tradingfirm.common.Meta meta             = 1;
  repeated RiskVote       votes            = 2;
  string                  committee_result = 3;
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


### 6.5 DecisionTrace (JSON — stored in Postgres)

```json
{
  "cycle_id": "cyc_01JQ...",
  "asset": "BTC-PERP",
  "mode": "paper",
  "market_snapshot_id": "ms_01JQ...",
  "observation_pack_id": "obs_01JQ...",
  "strategy_version": "paper/v17",
  "prompt_policy_versions": {
    "observer":          "observer/v1",
    "fundamental":       "fundamental/v4",
    "sentiment":         "sentiment/v3",
    "news":              "news/v5",
    "technical":         "technical/v6",
    "onchain":           "onchain/v2",
    "debater_a":         "debater-a/v1",
    "debater_b":         "debater-b/v1",
    "debater_c":         "debater-c/v1",
    "arbitrator":        "arbitrator/v1",
    "trader":            "trader/v9",
    "risk_aggressive":   "risk-aggressive/v2",
    "risk_neutral":      "risk-neutral/v3",
    "risk_conservative": "risk-conservative/v2",
    "fund_manager":      "fund-manager/v4"
  },
  "observation_pack":       {},
  "research_packet":        {},
  "debate_outcome":         {},
  "trade_intent":           {},
  "risk_review":            {},
  "execution_approval_req": {},
  "execution_approval":     {},
  "hitl_gate": {
    "required": false,
    "approved_by": null,
    "approved_at_ms": null
  },
  "sae_decision":  {},
  "fill_reports":  [],
  "treasury_event": {
    "triggered": false,
    "btc_converted_usd": 0,
    "stable_received_usd": 0
  },
  "final_state": {
    "result": "filled|no_fill|rejected_sae|rejected_risk|rejected_hitl|flat|mandate_hold",
    "halt_flags": [],
    "total_latency_ms": 2140,
    "agent_latencies_ms": {}
  }
}
```


### 6.6 Debate Panel Configuration (JSON)

```json
// config/debate-panels/panel_3_default.json
{
  "panel_id": "panel_3_default",
  "panel_size": 3,
  "debate_rounds": 2,
  "debaters": [
    {
      "id": "debater_a",
      "initial_stance": "bullish",
      "system_prompt_override": null,
      "information_subset_priority": ["hl_ohlcv", "onchain", "sentiment"]
    },
    {
      "id": "debater_b",
      "initial_stance": "bearish",
      "system_prompt_override": "You are a skeptical short-seller. Your prior is that this asset will revert. Argue against the long. Weight funding rate carry cost and liquidation risk heavily.",
      "information_subset_priority": ["fundamental", "news", "onchain"]
    },
    {
      "id": "debater_c",
      "initial_stance": "neutral",
      "system_prompt_override": null,
      "information_subset_priority": ["hl_ohlcv", "fundamental", "news", "sentiment"]
    }
  ]
}
```


### 6.7 Clawvisor HITL Ruleset (JSON)

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

## 7. Safety Architecture

### 7.1 Invariants

1. No `ExecutionRequest` reaches an Executor without a passing `ExecutionDecision` from SAE
2. No `ExecutionDecision` issued without an `ExecutionApproval` from Fund Manager
3. No live-mode cycle completes without HITL approval when ruleset requires it
4. All DecisionTrace artifacts written atomically before fill reconciliation
5. SAE has no LLM dependency — deterministic rule engine only
6. Strategy and prompt-policy changes require HITL approval before live effect
7. Prompt-policy versions are immutable once promoted
8. Treasury module cannot open leveraged positions; spot conversion only
9. ArbitratorAgent `mandate_hold == true` is terminal — no downstream agent may override it
10. Debater `initial_stance: bearish` system prompt may not be removed without SPEC.md update

### 7.2 SAE Policy Checks

| Check | Default Threshold | Configurable |
| :-- | :-- | :-- |
| `position_limit` | Max notional per asset ≤ 15% | Yes |
| `portfolio_drawdown` | Drawdown ≤ 8% | Yes |
| `daily_loss_limit` | Daily PnL ≤ -3% | Yes |
| `leverage_cap` | ≤ 3× paper, ≤ 2× live | Yes |
| `liquidity_gate` | 24h volume ≥ 10× trade notional | Yes |
| `correlation_gate` | Correlation to book ≤ 0.7 | Yes |
| `stale_data` | Snapshot age ≤ 60s | Yes |
| `funding_rate` | Funding ≤ 0.1% per 8h | Yes |
| `event_blackout` | No active macro event flag | Yes |
| `debate_evidence_quality` | evidence_quality_score ≥ 0.55 AND arbitrator_confidence ≥ 0.50 | Yes |
| `liquidation_proximity` | liq_cluster_distance_pct > 1.5% (reduce 50% if 1.5–3%, reject if <1.5%) | Yes |


---

## 8. Orchestrator API

### 8.1 Endpoints

| Method | Path | Description |
| :-- | :-- | :-- |
| `POST` | `/cycles/trigger` | Trigger decision cycle |
| `GET` | `/cycles/:id` | Cycle status |
| `GET` | `/traces/:id` | Full DecisionTrace |
| `GET` | `/traces` | List traces (paginated, filterable) |
| `POST` | `/control/halt` | Emergency halt |
| `POST` | `/control/resume` | Resume after halt |
| `POST` | `/control/emergency-close` | Immediate FLAT all positions |
| `POST` | `/governance/hitl-rules` | Update HITL ruleset |
| `POST` | `/governance/hitl-rules/:rule/approve` | Human HITL approval |
| `POST` | `/governance/prompt-policies/promote` | Promote prompt-policy version |
| `POST` | `/governance/strategies/promote` | Promote strategy version |
| `POST` | `/sae/policies/reload` | Hot-reload SAE policy |
| `GET` | `/status` | System health |
| `GET` | `/metrics` | Prometheus scrape |
| `GET` | `/treasury/status` | Treasury state |


---

## 9. Treasury Management

### 9.1 Conversion Triggers

| Trigger | Default | Configurable |
| :-- | :-- | :-- |
| Realized PnL threshold | +5% portfolio gain | Yes |
| Time-based | Every 7 days | Yes |
| Volatility spike | BTC 24h vol > 2σ | Yes |
| Manual | `POST /treasury/convert` via OpenClaw | Always |

### 9.2 Configuration

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
    "volatility_zscore_threshold": 2.0
  }
}
```


---

## 10. Storage Schema

### 10.1 Key Postgres Tables

| Table | Primary Key | Purpose |
| :-- | :-- | :-- |
| `decision_traces` | `cycle_id` | Full DecisionTrace JSON |
| `observation_packs` | `observation_pack_id` | ObservationPack artifacts |
| `analyst_reports` | `(cycle_id, analyst)` | Analyst outputs |
| `debate_rounds` | `(cycle_id, round)` | Per-round debater claims and conviction deltas |
| `arbitrator_verdicts` | `cycle_id` | ArbitratorVerdict records |
| `risk_reviews` | `cycle_id` | Committee results |
| `execution_decisions` | `cycle_id` | SAE decisions |
| `fills` | `venue_order_id` | Fill records |
| `prompt_policies` | `(role, version)` | Versioned prompt templates |
| `prompt_history` | `(cycle_id, role)` | Rendered prompts per cycle |
| `strategy_versions` | `(name, version)` | Strategy plugin registry |
| `hitl_rulesets` | `ruleset_id` | HITL rule definitions |
| `human_approvals` | `(cycle_id, rule_name)` | Human approval records |
| `governance_events` | `event_id` | All governance actions |
| `recovery_state` | `service_name` | Last known safe state |
| `ablation_results` | `(run_id, variant)` | Ablation outputs |
| `treasury_events` | `event_id` | Conversion events |
| `optimizer_runs` | `run_id` | Optimizer recommendations |


---

## 11. Observability

### 11.1 Metric Categories

**Trading:** cumulative return, annualized return, Sharpe, max drawdown, hit rate, turnover,
exposure concentration, avg holding period, slippage bps

**Process:** cycle latency P50/P95/P99, analyst latency per role, debate duration, debate rounds,
arena cross-examination latency, arbitrator confidence distribution, veto frequency, no-trade
frequency, mandate_hold frequency, HITL approval time

**Safety:** SAE rejection per check (including `debate_evidence_quality` and
`liquidation_proximity`), stale-data incidents, risk disagreement rate, human override count,
recovery entries, prompt-policy rollbacks, optimizer adoption rate

### 11.2 Alerting Thresholds

| Alert | Condition |
| :-- | :-- |
| `trading.drawdown.critical` | Portfolio drawdown > 6% |
| `safety.stale_data` | Snapshot age > 90s in live mode |
| `safety.sae_rejection_spike` | SAE rejection rate > 30% over 10 cycles |
| `debate.mandate_hold_spike` | mandate_hold rate > 40% over 20 cycles |
| `process.cycle_latency` | Cycle P95 > 8s |
| `infra.agent_service_down` | Agent health check fails > 30s |
| `treasury.conversion_failed` | Conversion not filled within 30 min |


---

## 12. Autonomous AI Optimization Agent

The `optimizer_agent` operates entirely off the hot path. It:

- Analyzes `DecisionTrace`, `debate_rounds`, `arbitrator_verdicts`, and `ablation_results`
- Identifies patterns correlating prompt-policy versions and debate configurations with improved
metrics (paying special attention to `evidence_quality_score` and `arbitrator_confidence`)
- Generates candidate prompt-policy versions with `status: candidate`
- Scores candidates via `prompt_policy_scorer.py` evaluation harness
- Posts recommendations to governance queue for human review via OpenClaw
- **Never** auto-promotes — all promotions require human HITL approval

---

## 13. Ablation Suite

The `ablation_runner.py` evaluates these variants (added to `ablation_results` table):


| Variant | What Is Disabled |
| :-- | :-- |
| `single_agent` | All debate, risk committee, observer |
| `no_observer` | ObserverAgent bypassed; raw data direct to analysts |
| `no_debate` | Debate bypassed; trader uses ResearchPacket directly |
| `2_debater_vs_3_debater` | Panel reduced to A+B only |
| `no_arbitrator` | ArbitratorAgent bypassed; facilitator summary only |
| `no_risk_committee` | Risk review bypassed |
| `no_sae` | SAE bypassed (paper only — never live) |
| `no_fund_manager` | Fund manager approval bypassed |
| `homogeneous_models` | All roles use same LLM provider (monoculture baseline) |
| `no_treasury` | Treasury evaluation bypassed |
| `full_system` | All stages active |


---

## 14. Limitations and Scope Constraints

**Out of scope:** cross-exchange arbitrage, equities/options, unattended live trading without
HITL, self-modifying strategy logic, AI reasoning directly in execution path without SAE review,
treasury initiating leveraged positions, sub-4h decision cycles.

**Performance claims:** The TradingAgents paper reported 26–27% cumulative return and Sharpe 6–8
on a narrow Q1 2024 equities simulation. The FinArena paper reports improvements on equities
backtests. Neither validates crypto perps live trading performance. All performance claims
require independent walk-forward validation in paper mode before any live deployment decision.

---

## 15. References

- TradingAgents paper: https://arxiv.org/pdf/2412.20138
- TauricResearch/TradingAgents: https://github.com/TauricResearch/TradingAgents
- FinArena paper: https://arxiv.org/abs/2509.11420
- HyperLiquid API: https://hyperliquid.gitbook.io/hyperliquid-docs
- This repo: https://github.com/enuno/hyperliquid-trading-firm
- DEVELOPMENT_PLAN.md: phased build plan with exit gates
