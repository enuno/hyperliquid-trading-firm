# STRATEGY.md — HyperLiquid Trading Firm

**Version:** 1.0 — April 2026
**Status:** Active Reference — Phase A
**Repo:** https://github.com/enuno/hyperliquid-trading-firm

---

## Table of Contents

1. [Overview & Philosophy](#1-overview--philosophy)
2. [Strategy Governance Rules](#2-strategy-governance-rules)
3. [Market Regime Framework](#3-market-regime-framework)
4. [Core Strategy — Wave-Trend Momentum (Phase A)](#4-core-strategy--wave-trend-momentum-phase-a)
5. [Planned Strategy — Mean Reversion / Range (Phase C)](#5-planned-strategy--mean-reversion--range-phase-c)
6. [Planned Strategy — Funding Rate Carry (Phase C)](#6-planned-strategy--funding-rate-carry-phase-c)
7. [Planned Strategy — Basis / Cross-Venue Arbitrage (Phase C)](#7-planned-strategy--basis--cross-venue-arbitrage-phase-c)
8. [Planned Strategy — Liquidation Cascade Fade (Phase C)](#8-planned-strategy--liquidation-cascade-fade-phase-c)
9. [Planned Strategy — On-Chain Smart Money Flow (Phase B/C)](#9-planned-strategy--on-chain-smart-money-flow-phase-bc)
10. [Kelly Sizing Governance](#10-kelly-sizing-governance)
11. [Risk Controls & Circuit Breakers](#11-risk-controls--circuit-breakers)
12. [Validation Requirements (All Strategies)](#12-validation-requirements-all-strategies)
13. [Strategy Registry & Lifecycle](#13-strategy-registry--lifecycle)
14. [References](#14-references)

---

## 1. Overview & Philosophy

This document enumerates all trading strategies — current and planned — for the HyperLiquid Autonomous Trading Firm. All strategies target HyperLiquid perpetuals. Each strategy is treated as a **hypothesis** to be validated, not a guaranteed edge.

**Core principles that govern every strategy in this document:**

- All strategies are hypotheses to be validated before live deployment
- No strategy may bypass the debate → trader → risk committee → FundManager → SAE chain
- No guaranteed profits; every component is independently auditable
- LLM agents are advisory; SAE is the final deterministic gate before any order
- Kelly inputs must come from OOS-validated statistics, never LLM confidence scores
- Closed bars only — current incomplete bar never included in any calculation
- Fail-closed by default — ambiguous state results in FLAT, never a guess

**Instrument scope:**
- Phase A: BTC-PERP
- Phase B: ETH-PERP, SOL-PERP
- Phase C: Additional high-liquidity HL perps as validated

---

## 2. Strategy Governance Rules

Before any strategy reaches `KellySizingService` or paper trading, it must pass all four gates:

1. **`BacktestResult.GO` verdict** from `apps/jobs/ablation_runner.py` (in-sample / out-of-sample split, bias-checked)
2. **Manual review and approval** by Network Engineering (repo owner)
3. **`strategy_registry.yaml` entry** — strategy is registered with ID, version, asset scope, regime scope, and activation date
4. **30+ OOS trades** accumulated in production paper trading mode before Kelly sizing is activated for that `(strategy, asset, regime, direction)` bucket

A recall competition (agent-nominated strategy) may propose a strategy for internal validation but may **not** independently authorize paper trading, live trading, or Kelly parameterization.

---

## 3. Market Regime Framework

All strategies are regime-scoped. A strategy that fails to specify target regime(s) is not activatable.

### 3.1 Canonical `MarketRegime` Enum (Operational — Risk-First)

| Regime | Meaning | Default Strategy Posture |
|---|---|---|
| `TREND_UP` | Clean directional uptrend, HH+HL confirmed | Trend-following LONG |
| `TREND_DOWN` | Clean directional downtrend, LL+LH confirmed | Trend-following SHORT |
| `RANGE` | Mean-reversion conditions, bounded oscillation | Mean reversion / fade extremes |
| `HIGH_VOL` | Volatility z-score elevated; risk control dominates direction | Reduced size or FLAT |
| `EVENT_RISK` | Structural uncertainty: breakout, liq cascade, crowded funding | Default FLAT |
| `UNKNOWN` | Insufficient data for classification | FLAT — mandatory |

### 3.2 Fine-Grained `QZRegime` Labels (Advisory — Agents See Both)

| QZRegime | MarketRegime | Rationale |
|---|---|---|
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

### 3.3 Regime Source Stack

Regime classification is layered from three deterministic inputs:

1. **Wave structure** (`WaveDetector` + `WaveAdapter`) — primary structural regime signal
2. **Volatility z-score** (`ObservationPack.realized_vol_zscore`) — vol override
3. **Funding rate** (`ObservationPack.funding_rate_8h`) — crowding override

`HIGH_VOL` and `EVENT_RISK` always override directional labels. `UNKNOWN` always produces FLAT.

---

## 4. Core Strategy — Wave-Trend Momentum (Phase A)

**Status:** Active — paper trading target (Phase A exit gate)
**Instruments:** BTC-PERP (Phase A); ETH-PERP, SOL-PERP (Phase B)
**Target Regime:** `TREND_UP` / `TREND_DOWN` with `QZRegime` = `trend_*_low_vol`
**Strategy Type:** Multi-timeframe wave structure momentum

### 4.1 Hypothesis

In HL perpetuals, directional momentum signals derived from Elliott-style wave structure classification — specifically confirmed `IMPULSIVE_UP` / `IMPULSIVE_DOWN` phases with high cross-timeframe confluence — provide a statistically significant edge in trend-dominant, low-volatility regimes. The edge hypothesis: institutional order flow creates self-reinforcing swing structures that persist for multiple bars, allowing entry after swing confirmation with defined risk at the prior swing level.

### 4.2 Signal Logic

**Entry conditions (LONG):**
- `WavePhase = IMPULSIVE_UP` confirmed on primary timeframe (4h)
- `confluence_score ≥ 0.67` across [4h, 1h, 15m]
- Supporting 1h timeframe not in `CORRECTIVE_ABC_DOWN` or `COMPLEX_CORRECTION`
- No `has_bearish_divergence` at current swing high
- `MarketRegime = TREND_UP`
- Funding rate < `SAE_MAX_FUNDING_LONG` (0.30% per 8h)
- `realized_vol_zscore ≤ 2.0`
- Price not within 0.8% of nearest confirmed swing low (`near_swing_failure = False`, or size halved if True)
- Nearest liquidation cluster > 0.5% from entry price

**Entry conditions (SHORT):** Mirror of LONG using `IMPULSIVE_DOWN`, `TREND_DOWN`, `has_bullish_divergence`.

**Exit logic:**
- Primary: Stop loss at prior swing low (LONG) / high (SHORT) as defined by `ObservationPack.swing_low` / `.swing_high`
- Secondary: Take profit at next structural resistance (estimated by WaveDetector projection)
- Forced exit: `max_holding_bars` exceeded (set per `TradeIntent`)
- Emergency: `KILL_SWITCH=true` or `EMERGENCY_FLATTEN=true`

**FLAT conditions (mandatory):**
- `has_data_gap = True`
- `MarketRegime` ∈ {`HIGH_VOL`, `EVENT_RISK`, `UNKNOWN`}
- `WavePhase` ∈ {`TRANSITION`, `UNKNOWN`, `COMPLEX_CORRECTION`}
- Kelly bucket has < 30 OOS trades
- Any SAE pre-execution check fails

### 4.3 Data / Feature Requirements

| Feature | Source | Update Cadence |
|---|---|---|
| OHLCV closed bars (4h, 1h, 15m) | `HyperliquidFeed` WS + REST reconcile | Per bar close |
| Order book depth (±10bps, ±50bps) | `HyperliquidFeed` | Per cycle |
| Funding rate (8h normalized) | `HyperliquidFeed` | Per cycle |
| Liquidation clusters | `IntelliClaw` | Per cycle |
| Realized volatility (24h, 7d, z-score) | Computed in `HyperliquidFeed` | Per bar close |
| Wave phase + confluence | `WaveDetector` + `WaveAdapter` | Per closed bar |
| RSI divergence flags | `WaveDetector` | Per closed bar |
| Regime | `QZRegimeClassifier` → `RegimeMapper` | Per closed bar |

### 4.4 Position Sizing

Fractional Kelly from `KellySizingService`:
- `win_prob` and `payoff_ratio` from OOS-validated ablation runner output
- Sequential penalty adjustments (see §10)
- Hard cap: 10% of portfolio notional
- Minimum threshold: 0.5% of portfolio — below this, emit FLAT

### 4.5 Risk Controls

| Control | Value | Enforced By |
|---|---|---|
| Max single position | 10% portfolio | FundManager + SAE |
| Max correlated exposure | 25% portfolio | FundManager |
| Daily drawdown circuit breaker | 3% | SAE |
| Max spread at entry | 50 bps | SAE |
| Max funding rate (LONG) | 0.30% / 8h | SAE |
| Max vol z-score | 3.0 | SAE |
| Min liq cluster distance | 0.5% | SAE |
| Near swing failure penalty | −50% size | SAE (not a veto) |
| Min bars between trades (same asset) | 4 closed bars | FundManager |

### 4.6 Expected Failure Modes

- **Regime misclassification:** Wave phases are inherently ambiguous at structural transitions. `TRANSITION` phase produces `EVENT_RISK` regime → forced FLAT. Mitigated by confluence score threshold.
- **Liq spike wick contamination:** Liquidation spikes can produce false swing levels. `_filter_liq_wicks()` currently logs but does not mutate frozen `HLBar` objects. **Phase B TODO:** apply actual wick clipping.
- **Crowded funding reversal:** Elevated long funding in trend regimes is a blow-off precursor. SAE funding cap partially mitigates; full mitigation requires funding regime detection (already in `QZRegime` as `funding_crowded_long`).
- **LLM agent hallucination:** Debate agents may fabricate context not in `ObservationPack`. Mitigated by strict constraint that debate agents must cite specific `ObservationPack` fields.
- **Kelly underfitting:** < 30 OOS trades → FLAT. Risk: long wait to activate Kelly on new strategy buckets. Accepted: better than sizing with insufficient data.

### 4.7 Phase A Validation Gate

**Paper trading for 30 days with live HL data. Go criteria:**
- Sharpe ratio > 0.8 (annualized from 30-day paper track record)
- Max drawdown < 8%
- Zero SAE bypass incidents
- No `has_data_gap` propagation failures

---

## 5. Planned Strategy — Mean Reversion / Range (Phase C)

**Status:** Planned — not yet in validation queue
**Target Regime:** `RANGE` (`range_low_vol` preferred)
**Strategy Type:** Statistical mean reversion on HL perps

### 5.1 Hypothesis

In range-bound markets (bounded corrective wave structures), price oscillates between statistically defined support and resistance. A mean-reversion strategy can capture this oscillation by fading price extremes with tight stop losses just outside the range boundary.

### 5.2 High-Level Signal Logic

- Entry: Price reaches upper/lower Bollinger band (or equivalent swing deviation threshold) within a confirmed `CORRECTIVE_ABC` wave structure
- `confluence_score ≥ 0.50` across timeframes
- RSI divergence at swing extreme (bullish at low, bearish at high)
- Exit: Price returns to mid-range (50% of range width)
- Stop: Just outside the confirmed range boundary (swing high/low)

### 5.3 Key Requirements Before Activation

- Dedicated OOS ablation run on BTC-PERP range periods (segmented by `QZRegime = range_low_vol`)
- Regime detection precision/recall on range vs. trend transitions validated
- Kelly bucket populated with 30+ OOS trades in range regime only
- Phase C explicit go/no-go decision by Network Engineering

### 5.4 Anticipated Failure Modes

- Range breakout (false range classification) → stop hit at boundary
- Spread cost eats mean reversion edge in thin markets
- High-vol override (vol z-score spike mid-range) forces FLAT before reversion completes

---

## 6. Planned Strategy — Funding Rate Carry (Phase C)

**Status:** Planned — not yet in validation queue
**Target Regime:** `TREND_UP` or `TREND_DOWN` with moderate funding (not `funding_crowded_*`)
**Strategy Type:** Funding carry + delta hedge

### 6.1 Hypothesis

HyperLiquid perpetuals periodically exhibit persistent funding rate imbalances — especially in strong trend regimes — where one side (long or short) consistently pays funding. A strategy that maintains a position on the receiving side of funding while delta-hedging directional risk can extract carry with reduced directional exposure.

### 6.2 High-Level Signal Logic

- Entry condition: `funding_rate_8h` > carry threshold (to be calibrated via ablation) for the target direction
- Direction: Take the side that *receives* funding
- Delta hedge: Partially hedge directional exposure via smaller opposing spot or perp position (cross-venue or within HL)
- Exit condition: Funding rate reverts below exit threshold, or directional stop hit

### 6.3 Key Requirements Before Activation

- Funding rate time-series analysis: identify persistence horizon (mean reversion time of elevated funding)
- Cross-venue basis analysis for delta hedge feasibility
- OOS backtest segmented by `QZRegime` funding states
- SAE configuration: dedicated funding carry strategy limits (separate from trend strategy caps)

### 6.4 Anticipated Failure Modes

- Sudden funding rate reversal (especially at trend inflection)
- `funding_crowded_long` / `funding_crowded_short` QZRegime → carry blow-off → large loss on unhedged residual
- Execution slippage on hedge leg eroding carry

---

## 7. Planned Strategy — Basis / Cross-Venue Arbitrage (Phase C)

**Status:** Planned — monitoring only at Phase A/B
**Target Regime:** All — regime-agnostic (price-neutral)
**Strategy Type:** Statistical arbitrage / basis trading

### 7.1 Hypothesis

Temporary basis dislocations between HyperLiquid perpetuals and reference prices (spot on CEX, CME futures, other perp venues) create risk-free or near-risk-free arbitrage windows. Systematic monitoring and execution of convergence trades capture this spread.

### 7.2 High-Level Signal Logic

- Monitor: HL perpetual mid vs. CoinGecko/CMC reference price and aggregated perp mid across venues
- Entry: Basis exceeds `MIN_BASIS_BPS` (calibrated per asset) after fees and slippage budget
- Direction: Long the cheaper side, short the more expensive (cross-venue or HL perp vs. spot)
- Exit: Basis converges to < `EXIT_BASIS_BPS`

### 7.3 Key Requirements Before Activation

- Cross-venue execution infrastructure (API connectivity to at least one additional venue)
- Latency measurement and slippage modeling for simultaneous leg execution
- Correlation of HL perp funding with basis to avoid funding-amplified adverse moves
- Regulatory / exchange terms review for cross-venue arb eligibility (no legal advice — flag for manual review)

### 7.4 Anticipated Failure Modes

- Leg execution latency → basis moves before second leg fills
- Funding rate adverse leg on HL perp eats arb spread
- Venue-specific risk (HL downtime, counterparty insolvency on opposing venue)

---

## 8. Planned Strategy — Liquidation Cascade Fade (Phase C)

**Status:** Planned — research phase only
**Target Regime:** `EVENT_RISK` (`liquidation_cascade_risk`) — fade entry only after cascade peak
**Strategy Type:** Event-driven contrarian / mean reversion post-dislocation

### 8.1 Hypothesis

HyperLiquid's on-chain liquidation data (via `IntelliClaw`) provides real-time visibility into liquidation cluster density and cascade events. After a confirmed liquidation cascade exhausts the dense cluster (price pierces cluster, volume spike, OI drop), price frequently reverts sharply. A fade entry after cascade completion — not during — can capture the reversion.

### 8.2 High-Level Signal Logic

- Entry condition: `liq_cluster_density_above` or `_below` spikes then collapses (cascade completed), OI decreases confirming forced unwinds, price has moved ≥ `MIN_CASCADE_MOVE_PCT` from pre-cascade anchor
- Direction: Fade the cascade direction (buy after downside cascade, sell after upside cascade)
- Stop: Beyond the cascade extreme
- Exit: Mean reversion to pre-cascade anchor ± target band

### 8.3 Key Requirements Before Activation

- Validated `IntelliClaw` data quality and latency SLA
- Cascade event labeling pipeline for historical OOS testing
- Phase C only — requires robust liq wick clipping (Phase B TODO) to be complete
- Minimum 50 OOS cascade events for Kelly parameterization

### 8.4 Anticipated Failure Modes

- Cascade is not exhausted — entry into continuation move
- Low liquidity post-cascade → high slippage on entry
- Second cascade triggered by entry (stop runs)
- `_filter_liq_wicks()` not yet mutating bars (Phase B TODO) → incorrect swing detection during cascade

---

## 9. Planned Strategy — On-Chain Smart Money Flow (Phase B/C)

**Status:** Planned — requires Nansen API activation (Phase 2 signal validation)
**Target Regime:** `TREND_UP` / `TREND_DOWN` (signal supplement, not standalone strategy)
**Strategy Type:** On-chain flow signal overlay

### 9.1 Hypothesis

Labeled wallet flow data (smart money, exchange net flows, whale accumulation/distribution) provides leading indicators of institutional directional conviction that precedes price momentum. Adding on-chain flow signals to the Wave-Trend strategy's debate inputs improves regime classification precision and reduces false entry rate.

### 9.2 Signal Sources

| Source | Signal | Feed |
|---|---|---|
| Nansen (Phase 2) | Smart money net token flow | `apps/agents/src/tools/nansen_client.py` |
| Coin Metrics (Community) | Exchange net flow (BTC/ETH) | `coinmetrics_client.py` |
| Subsquid (self-hosted) | Whale wallet activity, DEX volume by size tier | `subsquid_client.py` |
| Bitcoin Full Node | UTXO age shifts, miner flow | `bitcoind` ZMQ feed |

### 9.3 Activation Condition (Nansen)

Walk-forward backtest demonstrating **>0.15 incremental Sharpe improvement** on held-out data using Nansen wallet flow signals, across ≥ 2 distinct market regimes, before API costs are approved and integration is merged.

### 9.4 Integration Point

On-chain flow signals are injected into `ObservationPack.quantitative_baseline["onchain"]` by the `OnChainFlowAnalyst` agent and consumed by debate agents as additional citation evidence — not as direct trading authority.

---

## 10. Kelly Sizing Governance

All strategies use `KellySizingService` for position sizing. The following rules apply universally.

### 10.1 Kelly Inputs

- `win_prob` and `payoff_ratio` MUST come from validated OOS statistics output by `apps/jobs/ablation_runner.py`
- Minimum 30 OOS trades per `(strategy_id, asset, regime, direction)` bucket before sizing activates
- LLM agent confidence scores are **never** used as Kelly inputs — advisory only

### 10.2 Penalty Schedule (Applied Sequentially)

| Condition | Size Penalty |
|---|---|
| `signal_quality < 0.60` | −50% |
| Funding rate > 0.10%/8h on LONG | −25% |
| Funding rate > 0.20%/8h on LONG | −50% (replaces −25%) |
| `realized_vol_zscore > 2.0` | −50% |
| Nearest liq cluster within 1.5% | −50% |
| `near_swing_failure = True` | −50% (SAE-applied) |
| Adjusted fraction < 0.5% portfolio | Emit FLAT |
| Adjusted fraction > 10% portfolio | Hard cap at 10% |

### 10.3 Kelly Governance Chain

`KellySizingService` → `TradeIntent.suggested_notional_pct` → `RiskCommitteeAgent` (may reduce only) → `FundManager` (may reduce only) → `SAE` (independent position limit check). No component in this chain may increase the Kelly-adjusted size. The final `approved_notional_pct` is always ≤ the original Kelly output.

---

## 11. Risk Controls & Circuit Breakers

### 11.1 SAE Hard Limits (All Strategies)

| Check | Hard Limit |
|---|---|
| Signal freshness | All signals < 120s old |
| Data gap | `has_data_gap = False` required |
| Position size | ≤ 10% portfolio notional |
| Notional USD | ≤ `SAE_MAX_NOTIONAL_USD` (config) |
| Leverage | ≤ `SAE_MAX_LEVERAGE` (config) |
| Spread | ≤ 50 bps |
| Funding (LONG) | < 0.30% per 8h |
| Vol z-score | ≤ 3.0 |
| Liq cluster proximity | > 0.5% from entry |
| Daily portfolio drawdown | < 3% |
| Kill switch | `KILL_SWITCH = false` required |

### 11.2 FundManager Portfolio Limits

| Constraint | Default |
|---|---|
| Max single position | 10% portfolio |
| Max correlated exposure | 25% portfolio |
| Max total gross exposure | 200% portfolio |
| Max concurrent positions | 5 |
| Min bars between trades (same asset) | 4 closed bars |

### 11.3 Kill Switch & Emergency Flatten

- `KILL_SWITCH=true` → immediately rejects all new `ExecutionApproval` objects; existing positions NOT automatically closed
- `EMERGENCY_FLATTEN=true` → closes all open positions (separate env var, explicit operator action)
- Both activations are logged to audit log with timestamp and PID
- SAE heartbeat timeout: 30 seconds → watchdog restarts SAE; SAE reconciles exchange state before accepting new approvals

---

## 12. Validation Requirements (All Strategies)

Every strategy must pass all validation gates before any capital is risked.

### 12.1 Backtest Design

- **Data source:** HL historical perp OHLCV via `HyperliquidFeed` REST (closed bars only)
- **Minimum history:** 12 months OOS window
- **In-sample / out-of-sample split:** 60% IS, 40% OOS (walk-forward preferred)
- **Fees and slippage:** Include HL taker fees + 1–2 bps estimated slippage per leg
- **Regime segmentation:** Report metrics separately per `MarketRegime` bucket
- **Liquidity filter:** Exclude bars where `depth_10bps_usd` < liquidity minimum (calibrated per asset)

### 12.2 Required Metrics

| Metric | Minimum Threshold |
|---|---|
| Sharpe ratio (annualized, OOS) | > 0.8 (Phase A gate), > 1.0 (Phase B gate) |
| Max drawdown (OOS) | < 8% (Phase A gate) |
| Win rate | Reported (no minimum — must be consistent with payoff_ratio in Kelly) |
| Expectancy (per trade) | > 0 after fees |
| Profit factor | > 1.2 |
| OOS trade count | ≥ 30 per bucket before Kelly activation |
| Calmar ratio | Reported |

### 12.3 Bias Checks

- **Lookahead bias:** All signals use closed bars only; no intrabar data in any calculation
- **Survivorship bias:** HL perp delisting history must be accounted for if multi-asset
- **Data leakage:** OOS period must be held out prior to any hyperparameter tuning on IS data
- **Parameter sensitivity:** ±20% perturbation on key parameters must not degrade OOS Sharpe by > 30%
- **Regime dependency check:** Strategy must not be profitable in only one historical regime period

### 12.4 Benchmark Comparison

All strategies compared against BTC-PERP buy-and-hold over the same OOS window. Strategy must demonstrate superior risk-adjusted returns (Sharpe) rather than just raw returns.

---

## 13. Strategy Registry & Lifecycle

### 13.1 `strategy_registry.yaml` Schema (Required Fields)

```yaml
strategies:
  - id: "wave_trend_momentum_v1"
    version: "1.0"
    status: "paper_trading"   # research | backtesting | paper_trading | live | deprecated
    instruments:
      - "BTC-PERP"
    regime_scope:
      - "TREND_UP"
      - "TREND_DOWN"
    phase: "A"
    kelly_buckets_activated: false   # true when ≥30 OOS trades per bucket
    go_decision_date: null           # set on Phase A exit gate approval
    approval_by: null                # set to operator handle on approval
    notes: "Primary Phase A strategy. Wave structure momentum on closed bars."
```

### 13.2 Lifecycle States

| State | Meaning | Capital at Risk |
|---|---|---|
| `research` | Hypothesis stage — no code, no data requirement yet | None |
| `backtesting` | In ablation runner — IS/OOS backtest in progress | None |
| `paper_trading` | Live market data, no real capital — 30-day gate | None |
| `live` | Real capital deployed with Kelly-sized positions | Yes |
| `deprecated` | Strategy retired — positions closed, no new entries | Winding down |

---

## 14. References

- SPEC.md (v2.2, April 2026) — System specification, agent architecture, SAE rules, Kelly governance
- ANALYTICS.md (v1.0, April 2026) — Analytics platform selection, data flow, schema reference
- DEVELOPMENT_PLAN.md — Phased build plan with exit gates
- AGENTS.md — Agent role definitions
- TradingAgents paper: https://arxiv.org/pdf/2412.20138
- FinArena multi-agent evaluation: https://arxiv.org/abs/2509.11420
- Quant-Zero (Kelly framework, closed-bar signal architecture): https://github.com/marcohwlam/quant-zero
- WaveEdge (wave structure detection, swing levels): https://github.com/koobraelac/wavedge
- HyperLiquid API docs: https://hyperliquid.gitbook.io/hyperliquid-docs
- This repo: https://github.com/enuno/hyperliquid-trading-firm

---

*Document version: 1.0 — April 2026*
*Maintainer: Network Engineering / repo owner*
*Review cycle: Each phase gate, or when a new strategy reaches `backtesting` state*
