---
name: liquidation-cascade-risk
description: Use when open interest is elevated, leverage is concentrated near key price levels, or market depth is thinning — to detect, avoid, and opportunistically trade liquidation cascade events on HyperLiquid perpetuals.
category: agentic
---

# Liquidation Cascade Risk

## When This Skill Activates

Apply this skill whenever **any** of the following pre-cascade signals are
present on HyperLiquid perpetual markets:

- Open interest (OI) has increased **> 15%** over the prior 24h while price
  is range-bound or declining
- OI-weighted average leverage on the asset is estimated **> 10×** (infer
  from OI / market cap ratio when direct leverage data is unavailable)
- Price approaches a **known liquidation cluster level** (derived from OI
  distribution or historical wicks)
- Bid-side depth within **0.5%** of mid has dropped **> 30%** versus the
  prior 1h average (thin book = amplified cascade velocity)
- Funding rate has been **> 0.05%/h for ≥ 6 consecutive hours** (extreme
  carry = crowded long leverage)
- A large liquidation event (**> $5M notional** on any single asset) has
  already fired — first liquidation often triggers cascade
- CVD (cumulative volume delta) diverging strongly negative vs. price
  (hidden sell pressure before a long-side cascade)

---

## Core Principle

Liquidation cascades are **reflexive, self-reinforcing events**: forced long
closures drive price down, which liquidates more longs, which drives price
further down. On thin-book perpetual markets like HyperLiquid, a cascade can
clear **3–8% of price in under 60 seconds** with near-zero mean-reversion
in the first 30 seconds.

> **Rule**: Never hold a leveraged long into a confirmed cascade. Size
> aggressively to exit at the *first* liquidation signal, not after
> confirmation. Being wrong costs slippage; being right saves the position.

---

## Signal Classification and Cascade Probability

### Pre-Cascade Regime Indicators

| Signal | Threshold | Cascade Probability Uplift |
|---|---|---|
| OI growth (24h) | > 15% | +20% |
| OI growth (24h) | > 30% | +40% |
| Funding (1h) sustained | > 0.05% for 6h+ | +25% |
| Book depth drop (bid, 0.5%) | > 30% vs 1h avg | +30% |
| Price near OI cluster | within 0.3% | +35% |
| First large liquidation fired | > $5M notional | +50% |
| CVD divergence | strong negative | +20% |

Probabilities are **additive uplift estimates**, not independent probabilities.
When 3+ signals are simultaneously active, treat cascade risk as **HIGH** and
apply the full defensive protocol below.

### Cascade Severity Classification

| Severity | Expected Price Drop | Duration | Recovery Pattern |
|---|---|---|---|
| Minor | 1–2% | 1–5 min | V-shape, fast recovery |
| Moderate | 2–5% | 5–20 min | Partial recovery, new lower range |
| Major | 5–10% | 20–60 min | Dead-cat bounce, re-test lows |
| Systemic | > 10% | Hours | Extended downtrend, OI reset |

---

## Step-by-Step Pre-Cascade Protocol

### 1. Fetch OI and Liquidation Data

```
GET /info → meta + assetCtxs
  → assetCtxs[i].openInterest       (current OI in base asset)
  → assetCtxs[i].funding            (current predicted 1h rate)
  → assetCtxs[i].markPrice          (mark price for cluster proximity)

GET /info → liquidations (via WebSocket: subscribe to l2Book + trades)
  → monitor for large single-fill liquidation events
```

Compute OI change:
```
oi_change_pct = (oi_now - oi_24h_ago) / oi_24h_ago * 100
```

### 2. Assess Book Depth Fragility

```
GET /info → l2Book(coin)
  → sum bid sizes within 0.5% below mid  = bid_depth_near
  → compare to 1h rolling average         = bid_depth_avg_1h

fragility_score = max(0, 1 - (bid_depth_near / bid_depth_avg_1h))
# fragility_score > 0.30 = dangerously thin book
```

### 3. Score Active Signals and Classify Risk

```python
def cascade_risk_level(signals: dict) -> str:
    score = 0
    if signals['oi_change_24h_pct'] > 30:   score += 3
    elif signals['oi_change_24h_pct'] > 15: score += 2
    if signals['funding_elevated_hours'] >= 6: score += 2
    if signals['book_fragility'] > 0.30:    score += 3
    if signals['near_oi_cluster']:          score += 3
    if signals['large_liq_fired']:          score += 4
    if signals['cvd_diverging']:            score += 2

    if score >= 8:  return 'CRITICAL'   # exit all longs immediately
    if score >= 5:  return 'HIGH'       # reduce longs 50–75%
    if score >= 3:  return 'ELEVATED'   # reduce longs 25–40%
    return 'NORMAL'
```

### 4. Execute Defensive Action by Risk Level

| Risk Level | Score | Immediate Action |
|---|---|---|
| NORMAL | 0–2 | No change; maintain standard position monitoring |
| ELEVATED | 3–4 | Reduce long exposure 25–40%; widen stops |
| HIGH | 5–7 | Reduce long exposure 50–75%; cancel resting longs |
| CRITICAL | 8+ | Close **all** longs immediately via market order; pause new longs |

> **CRITICAL override**: When `large_liq_fired` signal fires (+4 score), the
> CRITICAL threshold can be hit with only one other signal active. Do not
> wait for full scoring — execute exit the moment a confirmed large
> liquidation event is observed AND any one other signal is active.

---

## During a Cascade — Live Event Protocol

Once a cascade is confirmed (price dropping > 1% in < 2 min with rising
liquidation volume):

### Do NOT
- Add to long positions to "average down" — cascades have no floor until
  OI is cleared; the market will liquidate your averaging attempt too
- Place resting limit bids in the cascade path — bids will be hit
  immediately, not providing price improvement but capturing falling knives
- Use stop-loss orders inside the cascade — stop-limit orders may not fill;
  use **market orders** for exit during a cascade
- Attempt to short the cascade if not already positioned — entry during a
  cascade is extremely high slippage; the best edge is pre-positioning

### Do
- Execute all long exits via **market order** (not limit) — slippage cost
  is always lower than the cost of not exiting during a major cascade
- Monitor the liquidation feed for **cascade exhaustion signals**:
  - Liquidation volume decelerating (fewer liquidations per 30s)
  - Bid depth beginning to rebuild in the l2Book
  - Funding rate dropping sharply (extreme shorts beginning to dominate)
  - CVD turning positive (buyers absorbing supply)
- Log the cascade start price, trough price, and recovery level for the
  evolution curriculum agent's liquidation-cascade task family

---

## Post-Cascade Re-Entry Protocol

Cascades create **re-entry opportunities** once OI has been flushed and
liquidation pressure exhausts. The post-cascade long is one of the
highest-probability setups in perpetual markets.

### Re-Entry Criteria (all must be met)

1. **OI has declined ≥ 15%** from pre-cascade peak (deleveraging confirmed)
2. **Funding has normalised** to < 0.02%/h (crowded longs cleared)
3. **Bid depth has recovered** to ≥ 80% of pre-cascade 1h average
4. **Price has stabilised** — no new lows for ≥ 5 consecutive 1m candles
5. **CVD is turning positive** — net buying pressure visible on tape

### Re-Entry Sizing

Post-cascade re-entries use **reduced initial size** due to residual
uncertainty about whether the cascade is fully exhausted:

```
re_entry_size = base_size * 0.5   # initial leg

# Add second leg when:
#   price holds above entry for > 15 min AND
#   OI begins rising again (new longs building = recovery confirmed)
re_entry_size_full = base_size * 1.0
```

Stop-loss: place **below the cascade trough**, not below entry — the trough
is the structural low; a breach invalidates the recovery thesis.

---

## Failure Modes to Avoid

- **Treating every OI spike as a cascade warning**: OI can rise sustainably
  in genuine trend regimes. Require ≥ 2 signals before elevating risk level.
- **Exiting too early on minor cascades**: Score < 5 with no large liq fired
  does not warrant full exit. Over-trading defensive exits erodes alpha.
- **Re-entering before OI flush is confirmed**: Premature re-entry during
  a "dead-cat bounce" inside a larger cascade is the single most common
  post-cascade loss. OI *must* be declining before re-entry.
- **Ignoring cross-asset contagion**: BTC cascade → ETH cascade within
  1–3 minutes is the historical norm. Apply CRITICAL protocol to all
  correlated assets when BTC cascade fires, not just BTC.
- **Using cascade as a routine short entry**: Cascades are violent; short
  entries mid-cascade have extreme slippage and risk sharp V-shape reversals.
  The short opportunity was in **pre-positioning**, not during the event.
- **Forgetting the funding kill-switch interaction**: The
  `high-funding-carry-avoidance` skill's kill-switch
  (`funding > 0.15% AND drawdown > 1.5%`) should already have reduced
  exposure before a cascade fires. If it has not, treat any cascade signal
  as an immediate override regardless of score.

---

## Integration with Other Skills and Controls

### Skill Dependencies

- **`high-funding-carry-avoidance`**: A prerequisite check. If funding
  carry avoidance has not already reduced long exposure in a high-funding
  regime, liquidation cascade risk is structurally higher. Run funding
  check first; cascade check is the second defensive layer.
- **`kelly-position-sizing-perps`** (risk/): Post-cascade re-entry sizing
  must still pass through Kelly/risk-budget constraints. The 0.5× initial
  re-entry is a cascade-specific overlay on top of base sizing.

### Risk Engine Integration

```json
{
  "event": "cascade_risk_assessment",
  "asset": "BTC",
  "timestamp_utc": "2026-04-07T22:30:00Z",
  "oi_change_24h_pct": 22.4,
  "funding_1h": 0.061,
  "funding_elevated_hours": 7,
  "book_fragility": 0.41,
  "near_oi_cluster": true,
  "large_liq_fired": false,
  "cvd_diverging": true,
  "cascade_score": 7,
  "risk_level": "HIGH",
  "action_taken": "reduced_long_60pct",
  "position_before_usd": 15000,
  "position_after_usd": 6000
}
```

Log this record to `logs/metaclaw/records/` on every cascade assessment
that results in a position change so it enters the RL replay buffer.

---

## Quick Decision Tree

```
Is cascade_score >= 8 OR (large_liq_fired AND any other signal active)?
├── YES → CRITICAL: market-exit ALL longs immediately. Halt new longs.
│
└── NO  → Is cascade_score >= 5?
          ├── YES → HIGH: reduce longs 50–75%. Cancel resting long orders.
          │
          └── NO  → Is cascade_score >= 3?
                    ├── YES → ELEVATED: reduce longs 25–40%. Widen stops.
                    └── NO  → NORMAL: monitor. No action required.

Post-exit: monitor for cascade exhaustion.
  All 5 re-entry criteria met?
  ├── YES → Re-enter at 0.5× base size. Add second leg after 15m hold.
  └── NO  → Remain flat. Do not chase recovery.
```

---

## HyperLiquid-Specific Notes

- **WebSocket liquidation feed**: Subscribe to `trades` channel and filter
  for `"liquidation": true` in the trade object. HyperLiquid does not have
  a dedicated liquidation stream; liquidation fills appear in the standard
  trades feed with a liquidation flag.
- **Mark price vs. last price**: Liquidations trigger at **mark price**
  (oracle-weighted), not last trade price. During thin-book cascades, last
  price can lag mark price by 0.5–2%. Use `assetCtxs[i].markPrice` for
  liquidation cluster proximity calculations, not mid from the l2Book.
- **Cross-margin cascade amplification**: HyperLiquid cross-margin accounts
  allow a cascade on one asset to liquidate positions on correlated assets
  if overall margin falls below maintenance. Monitor
  `marginSummary.totalRawUsd` and `marginSummary.totalMaintMargin` ratio;
  if ratio < 1.3, pre-emptively reduce all cross-margin longs regardless
  of per-asset cascade score.
- **Vault LPs are cascade beneficiaries**: HyperLiquid vault LPs earn from
  liquidation fees and benefit from OI resets. This skill applies only to
  **directional perpetual positions**, not vault LP allocations.
- **Order book reset after cascade**: HyperLiquid's order book fully
  refreshes after a cascade event. The first 30 seconds of l2Book data
  post-cascade is unreliable for depth assessment — wait 60 seconds before
  using book depth as a re-entry signal.
