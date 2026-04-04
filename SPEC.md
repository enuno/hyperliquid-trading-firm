# Hyperliquid Trading Firm — System Specification

**Version:** 2.2 — April 2026  
**Status:** Active Development — Phase A  
**Repo:** https://github.com/enuno/hyperliquid-trading-firm

---

## Table of Contents

1. [Overview](#1-overview)
2. [Design Principles](#2-design-principles)
3. [System Architecture](#3-system-architecture)
4. [Agent Roles and Responsibilities](#4-agent-roles-and-responsibilities)
5. [Data Flow](#5-data-flow)
6. [ObservationPack Schema](#6-observationpack-schema)
7. [TradeIntent Schema](#7-tradeintent-schema)
8. [SAE — Safety and Execution Agent](#8-sae--safety-and-execution-agent)
9. [FundManager](#9-fundmanager)
10. [DecisionTrace and Audit Log](#10-decisiontrace-and-audit-log)
11. [Treasury Management System](#11-treasury-management-system)
12. [Phased Build Plan](#12-phased-build-plan)
13. [Configuration and Environment](#13-configuration-and-environment)
14. [Quant Layer — apps/quant/](#14-quant-layer--appsquant)
15. [References](#15-references)

---

## 1. Overview

This system is an institutional-grade autonomous trading agent for HyperLiquid perpetuals. It combines a multi-agent LLM debate architecture with deterministic quantitative pre-processing, a fractional Kelly sizing model, and a multi-layer safety enforcement chain.

**Core mission:** Generate risk-adjusted returns on HL perps using structured agent debate, quant-validated signals, and fail-safe execution — not speculation.

**Key constraints:**
- All strategies are hypotheses to be validated before live deployment
- No guaranteed profits; every component must be independently audited
- LLM agents are advisory; SAE is the final deterministic gate before any order
- Closed bars only for all quantitative analysis — never include an incomplete bar

---

## 2. Design Principles

1. **Evidence-based, skeptical.** Treat all strategy hypotheses as unproven until out-of-sample validated.
2. **Separation of concerns.** Signal generation, risk control, execution, and audit are strictly isolated modules.
3. **Fail-closed by default.** Any stale data, missing context, or ambiguous state results in no trade — never a guess.
4. **Immutable audit trail.** Every signal, decision, order, and fill is written to `DecisionTrace` before execution. No action without a trace.
5. **No LLM authority over position sizing.** Kelly inputs must come from OOS historical statistics, not LLM confidence scores.
6. **Deterministic safety layer.** SAE enforces hard limits independent of agent output. Agents cannot override SAE.
7. **Observable and recoverable.** Every component exposes health metrics. Any failure must produce a clean recovery state, not corruption.

---

## 3. System Architecture

```

┌─────────────────────────────────────────────────────────────────┐
│                        Data Ingestion                           │
│  HyperliquidFeed (REST bootstrap → WS delta → REST reconcile)  │
│  IntelliClaw (liquidation cluster feed)                        │
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
│                    Debate Layer (LLM)                           │
│  BullAgent  │  BearAgent  │  NeutralAgent / Moderator           │
│  Structured adversarial debate → DebateResult                   │
└───────────────────────────┬─────────────────────────────────────┘
│ DebateResult
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
│  Reviews TradeIntent against portfolio context                  │
│  May veto, reduce size, or approve with conditions              │
└───────────────────────────┬─────────────────────────────────────┘
│ RiskReview
▼
┌─────────────────────────────────────────────────────────────────┐
│                      FundManager                                │
│  Applies portfolio-level caps, correlation limits               │
│  Emits ExecutionApproval with final notional                    │
└───────────────────────────┬─────────────────────────────────────┘
│ ExecutionApproval
▼
┌─────────────────────────────────────────────────────────────────┐
│              SAE — Safety and Execution Agent                   │
│  Final deterministic gate — enforces hard limits                │
│  Writes DecisionTrace → submits order to HL                     │
└───────────────────────────┬─────────────────────────────────────┘
│ Order
▼
HyperLiquid Exchange

```

---

## 4. Agent Roles and Responsibilities

### 4.1 ObserverAgent

Assembles `ObservationPack` from all available inputs. Does not interpret or trade.

**Inputs:**
- `HLMarketContext` from `HyperliquidFeed`
- `WaveAnalysisResult` + `WaveSAEInputs` from `WaveAdapter`
- `RegimeMappingResult` from `QZRegimeClassifier`
- Active positions and open orders

**Outputs:** Fully typed `ObservationPack` (see §6).

**Constraints:**
- Must not call LLM
- Must set `has_data_gap = True` if any feed exceeds 60s stale
- Must run `WaveAdapter.analyze()` on closed bars only

### 4.2 BullAgent / BearAgent / NeutralAgent

Adversarial LLM debate agents. Each receives the same `ObservationPack` and produces a structured argument for or against entering a position.

**Outputs:** `DebatePosition` — structured argument with cited evidence from `ObservationPack`.

**Constraints:**
- Must cite specific fields from `ObservationPack` in every argument
- Must not fabricate market data not present in `ObservationPack`
- Confidence scores from debate are advisory only — never used as Kelly inputs

### 4.3 TraderAgent

Synthesizes debate output into a `TradeIntent`.

**Outputs:** `TradeIntent` (see §7), including:
- Direction (`LONG` / `SHORT` / `FLAT`)
- Asset and timeframe
- Entry/exit rationale linked to debate evidence
- Kelly sizing fields (populated by `KellySizingService`)

**Constraints:**
- Must call `KellySizingService` with OOS-validated stats, not LLM confidence
- Must emit `FLAT` if debate is inconclusive or `has_data_gap = True`

### 4.4 RiskCommitteeAgent

LLM agent that reviews `TradeIntent` against portfolio context and existing exposures.

**Outputs:** `RiskReview` — approve / approve-with-reduction / veto.

**Constraints:**
- May only reduce `suggested_notional_pct`, never increase it
- Must provide written rationale for any veto
- Veto writes to `DecisionTrace` before propagating

### 4.5 FundManager

Deterministic (non-LLM) portfolio-level gating agent.

**Inputs:** `RiskReview`, current portfolio state, correlation matrix.

**Outputs:** `ExecutionApproval` with final `approved_notional_pct`.

**Constraints:**
- Hard cap: single position ≤ `FUND_MAX_SINGLE_POSITION_PCT` (default 10%)
- Correlation cap: total correlated exposure ≤ `FUND_MAX_CORRELATED_EXPOSURE_PCT` (default 25%)
- May not increase `suggested_notional_pct` from `RiskReview`

### 4.6 SAE — Safety and Execution Agent

Final deterministic gate. Enforces hard limits independent of all upstream agent output.

See §8 for full SAE specification.

---

## 5. Data Flow

### 5.1 Closed-Bar Invariant

**All quantitative analysis runs on closed bars only.** The current incomplete bar is never included in any calculation. This is enforced at the feed adapter level (`HyperliquidFeed`) and validated in `WaveDetector`.

Rationale: Intrabar calculations produce regime/wave false positives, unstable RSI values, and incorrect swing detection that vanish at bar close.

### 5.2 Feed Reconciliation

`HyperliquidFeed` reconciles REST vs WS state every 30 seconds. If a sequence gap is detected or any source exceeds 60 seconds stale:
- `HLMarketContext.has_data_gap` is set to `True`
- `ObservationPack.has_data_gap` is propagated
- `TraderAgent` must emit `FLAT` on `has_data_gap = True`
- SAE must reject any `ExecutionApproval` where source `ObservationPack.has_data_gap = True`

### 5.3 Signal Freshness

Every field in `ObservationPack` carries a `timestamp_utc`. SAE validates that all signals are within `MAX_SIGNAL_AGE_SECONDS` (default 120) before proceeding.

---

## 6. ObservationPack Schema

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
    depth_10bps_usd: float              # Total liquidity within ±10bps
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
    regime_confidence: float                # 

    # Wave structure (from WaveAdapter)
    swing_high: Optional[SwingLevel]        # Nearest confirmed swing high
    swing_low: Optional[SwingLevel]         # Nearest confirmed swing low
    quantitative_baseline: dict             # Full wave analysis dict (see §14.4)

    # Portfolio context
    current_position_size: float
    current_position_direction: str         # "LONG" | "SHORT" | "FLAT"
    current_position_pnl_pct: float
    current_position_age_bars: int

    # Active orders
    open_orders: List[dict]

    # Quant baseline (arbitrary key-value store for additional signals)
    # Standard keys: "wave", "momentum", "regime_history"
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

## 7. TradeIntent Schema

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
    agent_confidence: float             #  from TraderAgent — informational only
```


---

## 8. SAE — Safety and Execution Agent

SAE is the final deterministic gate before any order reaches HyperLiquid. It is the only component with exchange API write access. It cannot be overridden by any agent output.

### 8.1 Pre-execution Checks

SAE validates all of the following before submitting any order. Failure on any check results in immediate REJECT with `DecisionTrace` entry:


| Check | Hard Limit | Source |
| :-- | :-- | :-- |
| Signal freshness | All signals < 120s old | `ObservationPack.timestamp_utc` |
| Data gap | `has_data_gap = False` | `ObservationPack.has_data_gap` |
| Position size | ≤ `SAE_MAX_NOTIONAL_PCT` (10%) | `ExecutionApproval.approved_notional_pct` |
| Notional USD | ≤ `SAE_MAX_NOTIONAL_USD` | Config |
| Leverage | ≤ `SAE_MAX_LEVERAGE` | Config |
| Spread | ≤ `SAE_MAX_SPREAD_BPS` (50bps) | `ObservationPack.spread_bps` |
| Funding | Long: funding < `SAE_MAX_FUNDING_LONG` (0.30%/8h) | `ObservationPack.funding_rate_8h` |
| Volatility | Vol z-score ≤ `SAE_MAX_VOL_ZSCORE` (3.0) | `ObservationPack.realized_vol_zscore` |
| Liq cluster proximity | Nearest cluster > `SAE_MIN_LIQ_DISTANCE_PCT` (0.5%) | `ObservationPack.nearest_liq_cluster_*_pct` |
| **Swing failure proximity** | `near_swing_failure = True` → −50% size penalty | `WaveSAEInputs.near_swing_failure` |
| **Near swing failure USD** | Position ≤ `SAE_SWING_FAILURE_REDUCED_PCT` (5%) | When `near_swing_failure = True` |
| Kill switch | `KILL_SWITCH = False` | Environment variable |
| Daily drawdown | Portfolio drawdown < `SAE_MAX_DAILY_DD_PCT` (3%) | Live portfolio state |

### 8.2 Order Execution

On approval:

1. Write complete `DecisionTrace` entry with all inputs, checks, and approval state
2. Compute final order parameters (size, price, slippage tolerance)
3. Submit order to HL with idempotency key = `intent_id`
4. On fill: write fill details to `DecisionTrace`
5. On partial fill: reassess remaining quantity before submitting remainder

### 8.3 Kill Switch

`KILL_SWITCH=true` in environment immediately:

- Rejects all new `ExecutionApproval` objects
- Does NOT close existing positions automatically (separate `EMERGENCY_FLATTEN=true` env var)
- Logs kill switch activation to audit log with timestamp and PID


### 8.4 Heartbeat Monitoring

SAE exposes a `/health` endpoint. A watchdog process restarts SAE if heartbeat exceeds `SAE_HEARTBEAT_TIMEOUT_SECONDS` (30). On restart, SAE reconciles open orders with exchange state before accepting new approvals.

---

## 9. FundManager

FundManager is a deterministic (non-LLM) component that applies portfolio-level constraints to `RiskReview` before emitting `ExecutionApproval`.

### 9.1 Portfolio Constraints

| Constraint | Default | Config Key |
| :-- | :-- | :-- |
| Max single position | 10% of portfolio | `FUND_MAX_SINGLE_POSITION_PCT` |
| Max correlated exposure | 25% of portfolio | `FUND_MAX_CORRELATED_EXPOSURE_PCT` |
| Max total gross exposure | 200% of portfolio | `FUND_MAX_GROSS_EXPOSURE_PCT` |
| Max positions simultaneously | 5 | `FUND_MAX_CONCURRENT_POSITIONS` |
| Min time between trades (same asset) | 4 closed bars | `FUND_MIN_BARS_BETWEEN_TRADES` |

### 9.2 Kelly Governance

FundManager receives `TradeIntent.suggested_notional_pct` (Kelly-adjusted) and applies the portfolio constraints above. It may **reduce** but never **increase** `suggested_notional_pct`. The resulting `approved_notional_pct` is written to `ExecutionApproval`.

SAE then applies its own independent position limit check on `approved_notional_pct`. Neither FundManager nor SAE can increase the size set by `KellySizingService`.

---

## 10. DecisionTrace and Audit Log

Every trading decision — including rejections — is written to an append-only `DecisionTrace` before the action is taken. This provides full post-hoc auditability.

### 10.1 DecisionTrace Fields

```python
@dataclass
class DecisionTrace:
    trace_id: str                       # UUID
    timestamp_utc: datetime
    asset: str
    cycle_id: str                       # Groups all records from one decision cycle

    # Inputs
    observation_pack: ObservationPack   # Full snapshot at decision time
    debate_result: DebateResult
    trade_intent: TradeIntent
    risk_review: RiskReview
    execution_approval: ExecutionApproval

    # Kelly audit
    kelly_inputs: KellyInputs           # win_prob, payoff_ratio, OOS trade count, source bucket
    kelly_output: KellyOutput           # raw_fraction, adjusted_fraction, penalties applied

    # Wave audit
    wave_analysis: dict                 # output.observation_dict from WaveAdapter
    wave_phase: str
    wave_confluence_score: float
    near_swing_failure: bool

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
```


### 10.2 Storage

`DecisionTrace` records are:

- Written to a local append-only SQLite database (`data/traces/traces.db`) in real-time
- Asynchronously replicated to object storage (S3-compatible) for durability
- Never mutated after write — corrections are new records with `correction_of_trace_id` field
- Retained for minimum 365 days

---

## 11. Treasury Management System

The treasury system manages BTC → stablecoin conversion to reduce mark-to-market volatility and lock in mining revenue.

### 11.1 Conversion Rules

| Trigger | Action |
| :-- | :-- |
| BTC price ≥ rolling 30d high × `TREASURY_TAKE_PROFIT_PCT` (1.05) | Convert `TREASURY_CONVERT_PCT` (20%) of BTC balance to USDC |
| Portfolio drawdown ≥ `TREASURY_DRAWDOWN_HEDGE_PCT` (5%) | Convert `TREASURY_DRAWDOWN_CONVERT_PCT` (30%) of BTC to USDC |
| Weekly rebalance | Rebalance to `TREASURY_TARGET_BTC_PCT` (60%) BTC / 40% stablecoin |

### 11.2 Constraints

- All conversions require 2-of-2 signature (operator + automated system)
- Maximum single conversion: `TREASURY_MAX_SINGLE_CONVERT_PCT` (25% of BTC balance)
- No conversions during active open positions
- Full conversion audit log written to separate `TreasuryTrace` table

---

## 12. Phased Build Plan

### Phase A — Foundation (Current)

**Exit criteria:** Paper trading with live data for 30 days, Sharpe > 0.8, max drawdown < 8%, zero SAE bypass incidents.

Deliverables:

- [x] `HyperliquidFeed` — REST/WS feed with reconciliation
- [x] `WaveDetector` + `WaveAdapter` — wave structure detection (§14.4)
- [x] `KellySizingService` — fractional Kelly with OOS gating (§14.2)
- [x] `RegimeMapper` — QZRegime → MarketRegime (§14.3)
- [ ] `ObserverAgent` — assembles `ObservationPack`
- [ ] Debate agent framework — BullAgent, BearAgent, NeutralAgent
- [ ] `TraderAgent`
- [ ] `RiskCommitteeAgent`
- [ ] `FundManager`
- [ ] SAE with full pre-execution checks
- [ ] `DecisionTrace` storage and audit
- [ ] Paper trading harness

**Phase A known TODOs:**

- `wave_detector.py`: `_filter_liq_wicks()` logs spike events but does not mutate frozen `HLBar` objects. Actual wick-clipping requires mutable bar types. See comment in source (`# TODO(phase-b): accept mutable bars and apply actual clipping`).
- `KellySizingService`: OOS bucket statistics are manually seeded for Phase A. Phase B wires `ablation_runner.py` output directly.


### Phase B — Live Trading (Planned)

**Exit criteria:** Live trading with real capital for 60 days at 10% max position size. Sharpe > 1.0 live vs paper. All TODOs from Phase A closed.

Deliverables:

- Mutable bar types for liq spike wick clipping
- `ablation_runner.py` → `KellySizingService` automatic OOS stat pipeline
- Treasury management system
- Multi-asset support (ETH-PERP, SOL-PERP)
- Correlation matrix for FundManager
- Live monitoring dashboard


### Phase C — Scale (Future)

- Increased position limits with extended track record
- Additional strategy families (mean reversion, basis)
- Automated regime-adaptive parameter tuning
- Cross-venue arbitrage monitoring

---

## 13. Configuration and Environment

All configuration is loaded from environment variables. No secrets in source. Rotate keys via secret manager, not by editing `.env`.

### 13.1 Required Environment Variables

```bash
# HyperLiquid
HL_API_KEY=
HL_API_SECRET=
HL_WALLET_ADDRESS=
HL_TESTNET=true                         # Set false for live trading

# Safety limits
SAE_MAX_NOTIONAL_PCT=10
SAE_MAX_NOTIONAL_USD=50000
SAE_MAX_LEVERAGE=5
SAE_MAX_SPREAD_BPS=50
SAE_MAX_FUNDING_LONG=0.0030            # 0.30% per 8h
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
KELLY_MAX_FRACTION=0.25                # Full Kelly cap before adjustments

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
LLM_PROVIDER=anthropic
LLM_MODEL=claude-opus-4-5
LLM_MAX_TOKENS=4096
```


### 13.2 API Key Security

- Trading keys: minimum permissions — place/cancel orders, read positions only
- Read-only keys: separate key for data feeds, monitoring dashboards
- Never log API keys; mask in all trace output
- Rotate on any suspected compromise; KILL_SWITCH immediately on rotation

---

## 14. Quant Layer — `apps/quant/`

The `apps/quant/` module provides deterministic, quantitative signal pre-processing that runs before LLM agents and feeds structured evidence into `ObservationPack`. It has zero LLM calls, zero network calls (feeds are injected), and zero side effects.

**Governance invariant:** No quant module output is ever executable trading authority on its own. All outputs are advisory inputs to LLM agents or penalty inputs to deterministic safety checks. The decision chain — debate → trader → risk committee → fund manager → SAE → executor — remains intact.

---

### 14.1 HyperLiquid Feed Adapter

**Source:** `apps/quant/feeds/hyperliquid_feed.py`

`HyperliquidFeed` produces `HLMarketContext` objects consumed by `ObserverAgent`, `QZRegimeClassifier`, and `KellySizingService`. It operates snapshot-first (REST bootstrap) with WebSocket delta updates and periodic REST reconciliation.

**Architecture:**

- Bootstrap via REST before any WS subscriptions
- Reconcile every 30 seconds to detect sequence gaps and drift
- Set `has_data_gap = True` if any source exceeds 60 seconds stale
- SAE must fail-close on `has_data_gap = True`

**Key normalizations for HL perps:**

- Funding rate normalized to 8-hour equivalent regardless of venue cadence
- `depth_10bps_usd` computed as order book depth within ±10bps of mid
- Liquidation clusters expressed as signed distance percentage from current mid
- Bars are closed-bar only — current incomplete bar is never included

**Adapted from:** [Quant-Zero](https://github.com/marcohwlam/quant-zero) — closed-bar signal architecture and feed bootstrap pattern.

---

### 14.2 Kelly Sizing Service

**Source:** `apps/quant/sizing/kelly_sizing_service.py`

`KellySizingService` computes a fractional Kelly position size and writes a fully auditable `KellyOutput` into `TradeIntent` and `DecisionTrace`.

**Critical constraint:** `win_prob` and `payoff_ratio` MUST come from validated out-of-sample historical estimates from `apps/jobs/ablation_runner.py` — never from raw LLM confidence scores. A minimum of 30 OOS trades is required before Kelly sizing is active for any `(strategy, asset, regime, direction)` bucket. If the bucket has < 30 OOS trades, emit FLAT.

**Penalty adjustments applied sequentially:**


| Condition | Size Penalty |
| :-- | :-- |
| `signal_quality < 0.60` | −50% |
| Funding rate > 0.10% per 8h on LONG | −25% |
| Funding rate > 0.20% per 8h on LONG | −50% (replaces −25%) |
| Realized vol z-score > 2.0 | −50% |
| Nearest liq cluster within 1.5% | −50% |
| Adjusted fraction < `KELLY_MIN_NOTIONAL_PCT` (0.5%) | Emit FLAT |
| Result > `KELLY_MAX_NOTIONAL_PCT` (10%) | Hard cap at 10% |

**Governance:** `kelly_inputs` and `kelly_output` are written to `TradeIntent` and persisted in `DecisionTrace`. `FundManager` may reduce `suggested_notional_pct` but must never increase it. SAE enforces its own `position_limit` independently.

**Adapted from:** [Quant-Zero](https://github.com/marcohwlam/quant-zero) — fractional Kelly framework and OOS validation requirements.

---

### 14.3 Regime Mapper

**Source:** `apps/quant/regimes/regime_mapper.py`

`RegimeMapper` bridges fine-grained `QZRegime` labels to the canonical `MarketRegime` enum from `proto/common.proto`.

**Design principle:** `MarketRegime` is an operational (risk-first) enum, not a descriptive one. High-volatility conditions override directional labels because risk control dominates direction in HL perp trading.

**Mapping table:**


| QZRegime | MarketRegime | Rationale |
| :-- | :-- | :-- |
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

---

### 14.4 Wave Structure Detector

**Sources:** `apps/quant/signals/wave_detector.py`, `apps/quant/signals/wave_adapter.py`

**Adapted from:** [WaveEdge](https://github.com/koobraelac/wavedge) — wave structure detection algorithm, liquidation-proximity swing detection, and multi-timeframe divergence detection concepts. Re-implemented as a deterministic, closed-bar-only Python module with no LLM calls, no network calls, and no side effects.

`WaveDetector` implements deterministic multi-timeframe wave structure classification on HL perp closed bars. `WaveAdapter` bridges detector output to `ObservationPack`, regime mapping, and SAE enrichment inputs.

**Wave phase classifications:**


| Phase | Meaning |
| :-- | :-- |
| `IMPULSIVE_UP` | HH + HL sequence, ≥3 confirmed legs, no deep retracement |
| `IMPULSIVE_DOWN` | LL + LH sequence, ≥3 confirmed legs, no deep retracement |
| `CORRECTIVE_ABC_UP` | Bounded corrective structure pushing price up |
| `CORRECTIVE_ABC_DOWN` | Bounded corrective structure pushing price down |
| `COMPLEX_CORRECTION` | Multi-leg WXY or similar overlapping correction (>6 swings) |
| `TRANSITION` | Structural break — swing sequence violates all patterns — highest uncertainty |
| `UNKNOWN` | Insufficient bars for classification |

**Wave → QZRegime mapping:**


| WavePhase | Confluence ≥ 0.67 | QZRegime |
| :-- | :-- | :-- |
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
- `timeframe_phases` — per-TF phase dict (e.g. `{"4h": "IMPULSIVE_UP", "1h": "CORRECTIVE_ABC_DOWN"}`)
- `nearest_swing_high` / `nearest_swing_low` — price of nearest confirmed swing
- `nearest_swing_high_distance_pct` / `nearest_swing_low_distance_pct` — % distance from mid
- `has_bearish_divergence` / `has_bullish_divergence` — RSI divergence at swing points only
- `qz_regime_from_wave` / `market_regime_from_wave` — regime from wave analysis

**Also written directly to `ObservationPack`:**

- `obs_pack.swing_high` = `output.wave_result.nearest_swing_high` (typed `SwingLevel`)
- `obs_pack.swing_low` = `output.wave_result.nearest_swing_low` (typed `SwingLevel`)

**SAE enrichment (`WaveSAEInputs`):**

- `near_swing_failure: bool` — True when price is within 0.8% of nearest confirmed swing low (LONG) or high (SHORT)
- `swing_failure_price: Optional[float]`
- `swing_failure_distance_pct: Optional[float]`
- `wave_confluence_score: float`

SAE applies a 50% size reduction when `near_swing_failure = True`. This is a penalty, not a veto.

**Critical caveats:**

- Wave labeling is inherently ambiguous. This module returns the most statistically probable structural interpretation — not ground truth. Treat `wave_phase` as strong advisory evidence, not trading authority.
- Run on **closed bars only**. Intrabar computation produces false state transitions at bar boundaries.
- HL liquidation spike wicks must be pre-filtered before wave detection runs. `_filter_liq_wicks()` currently flags spikes in logging but does not mutate frozen `HLBar` dataclass objects. **Phase B TODO:** accept mutable bar types and apply actual wick clipping.

---

### 14.5 ObserverAgent Integration

```python
# Canonical wiring in apps/agents/observer/observer_agent.py

from apps.quant.signals.wave_adapter import analyze_wave

output = analyze_wave(
    asset=ctx.asset,
    bars_by_tf={
        "4h": ctx.bars_4h,
        "1h": ctx.bars_1h,
        "15m": ctx.bars_15m,
    },
    current_mid_price=ctx.mid_price,
    direction_for_sae="LONG",  # pass pending TradeIntent direction if known
)

# Inject into ObservationPack
obs_pack.quantitative_baseline["wave"] = output.observation_dict
obs_pack.swing_high = output.wave_result.nearest_swing_high
obs_pack.swing_low  = output.wave_result.nearest_swing_low

# SAE receives separately — not via ObservationPack
sae_wave_inputs = output.sae_inputs
```


---

### 14.6 Integration Points Summary

| Quant Component | Consumes | Produces | Used By |
| :-- | :-- | :-- | :-- |
| `HyperliquidFeed` | HL REST/WS, IntelliClaw | `HLMarketContext` | `ObserverAgent`, jobs |
| `WaveDetector` + `WaveAdapter` | `HLMarketContext.bars_*`, `mid_price` | `WaveAnalysisResult`, `WaveSAEInputs` | `ObserverAgent`, SAE |
| `QZRegimeClassifier` | `HLMarketContext`, wave phase | `RegimeMappingResult` | `ObserverAgent` |
| `KellySizingService` | OOS stats, signal quality, market context | `KellyOutput` in `TradeIntent` | `TraderAgent`, `FundManager` |


---

## 15. References

- TradingAgents paper: https://arxiv.org/pdf/2412.20138
- TauricResearch/TradingAgents: https://github.com/TauricResearch/TradingAgents
- FinArena paper (multi-agent trading evaluation): https://arxiv.org/abs/2509.11420
- HyperLiquid API docs: https://hyperliquid.gitbook.io/hyperliquid-docs
- Quant-Zero (signal architecture, Kelly framework): https://github.com/marcohwlam/quant-zero
- WaveEdge (wave structure detection, swing levels): https://github.com/koobraelac/wavedge
- Haiku trading agent framework: https://docs.haiku.trade/
- This repo: https://github.com/enuno/hyperliquid-trading-firm
- DEVELOPMENT_PLAN.md: phased build plan with exit gates
