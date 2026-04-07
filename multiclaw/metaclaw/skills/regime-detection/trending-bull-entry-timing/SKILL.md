---
name: trending-bull-entry-timing
description: Use when price is in a confirmed uptrend with rising OI and healthy funding to identify optimal long entry timing, pullback depth, and trend invalidation levels on HyperLiquid perpetuals.
category: agentic
---

# Trending Bull Entry Timing

## When This Skill Activates

Apply this skill when **all three core conditions** are simultaneously true:

1. **Trend confirmation**: Price is making higher highs and higher lows on
   the **1h timeframe** over the prior 12+ candles
2. **OI trend alignment**: Open interest is rising alongside price (smart
   money adding to longs, not short-covering driving the move)
3. **Funding is sustainable**: 1h funding rate is **< 0.03%** (carry cost
   does not structurally erode the trade — see `high-funding-carry-avoidance`)

Also apply when transitioning out of a **post-cascade re-entry** (see
`liquidation-cascade-risk`) where OI has flushed and price structure is
rebuilding — these are the highest-probability trending bull setups.

---

## Core Principle

In a trending bull regime, the primary edge is **buying pullbacks to
structural support, not chasing breakouts**. Price in a trend oscillates
between expansion (breakout legs) and contraction (retracement to support).
The highest reward-to-risk entries occur during contraction phases —
when sentiment is briefly bearish and weak hands are shaken out — not at
the moment of maximum bullish conviction.

> **Rule**: Enter at structure, not at momentum. The worst time to enter
> a trending market is when it feels the most bullish.

---

## Trend Regime Classification

Before sizing or timing any entry, classify the current trend regime:

| Regime | Criteria | Entry Approach |
|---|---|---|
| **Nascent trend** | < 3 HH/HL sequences; OI just turning up; funding neutral | Small initial size (0.4×); requires confirmation candle |
| **Established trend** | 3–8 HH/HL sequences; OI steadily rising; funding < 0.02%/h | Standard size (0.8–1.0×); pullback entries preferred |
| **Mature trend** | 8+ HH/HL sequences; OI at 30d high; funding 0.02–0.03%/h | Reduced size (0.5×); tighter stops; proximity to exhaustion |
| **Exhausted trend** | OI plateauing or declining vs. prior high; funding > 0.03%/h | No new longs; manage existing; watch for reversal |

Reclassify regime every **4h** or after any candle that closes below the
prior swing low — a lower low invalidates the HH/HL structure regardless
of other indicators.

---

## Entry Timing Framework

### Step 1 — Identify the Trend Anchor Levels

For each trending asset, maintain three dynamic levels updated after every
new swing high confirmation:

```
swing_high_current   = most recent confirmed HH (candle with lower highs on both sides)
swing_low_prior      = most recent confirmed HL (the last pullback low)
trend_leg_size       = swing_high_current - swing_low_prior

# Fibonacci retracement targets for pullback entries:
fib_382 = swing_high_current - (trend_leg_size * 0.382)   # shallow pullback
fib_500 = swing_high_current - (trend_leg_size * 0.500)   # mid pullback
fib_618 = swing_high_current - (trend_leg_size * 0.618)   # deep pullback
fib_786 = swing_high_current - (trend_leg_size * 0.786)   # maximum pullback

# Invalidation level (stop reference):
trend_invalidation   = swing_low_prior - (trend_leg_size * 0.05)  # 5% below prior HL
```

### Step 2 — Classify Pullback Depth

| Pullback Depth | Fib Level | Signal Quality | Size Multiplier |
|---|---|---|---|
| < 23.6% retracement | Above fib_236 | Weak — trend may be exhausting (no new ATH imminent) | 0.3× |
| 23.6–38.2% | fib_236 to fib_382 | Moderate — strong trend, shallow pullback | 0.6× |
| 38.2–50.0% | fib_382 to fib_500 | **Optimal** — healthy correction, high continuation probability | 1.0× |
| 50.0–61.8% | fib_500 to fib_618 | Good — deeper correction, still valid in established trend | 0.9× |
| 61.8–78.6% | fib_618 to fib_786 | Caution — near structural limit; require volume confirmation | 0.5× |
| > 78.6% retracement | Below fib_786 | Trend likely broken — apply invalidation protocol | 0× |

### Step 3 — Entry Confirmation Trigger

Never enter purely on price reaching a Fibonacci level. Require **one
confirmation signal** from the following, observed on the **15m or 1h
chart** at the retracement level:

- **Bullish engulfing candle**: current candle body fully engulfs the prior
  bearish candle body at or near the fib level
- **Volume spike on bounce**: volume on the bounce candle is **> 1.5×** the
  20-candle average volume (institutional absorption visible)
- **CVD inflection**: cumulative volume delta turns positive after being
  negative during the pullback (sellers exhausted, buyers taking control)
- **OI holds or rises during pullback**: OI did not decrease during the
  retracement (longs held, not closed — conviction maintained)
- **Bid depth rebuild**: l2Book bid depth within 0.5% of price has
  returned to > 90% of its pre-pullback level

> Require **at least 1** confirmation signal. If 2+ signals align at the
> same level, apply a **1.2× size bonus** (max 1.2× base, never exceed
> risk budget regardless).

### Step 4 — Entry Execution

In an established trending market, use **limit orders**, not market orders,
to capture the pullback without paying the spread:

```
# Place limit order grid at the target fib zone:
limit_entry_primary   = fib_500            # centre of optimal zone
limit_entry_secondary = fib_618            # secondary fill if primary misses

# Order split:
primary_order_size   = adjusted_size * 0.65
secondary_order_size = adjusted_size * 0.35

# Cancel secondary if primary fills and price reverses past fib_618:
secondary_cancel_trigger = fib_618 - (trend_leg_size * 0.02)
```

Set a **GTC (good-till-cancelled) limit** with a 4h expiry. If price does
not pull back to the target zone within 4h, cancel and reassess — chasing
an extension that has already run past the entry zone is a breakout buy,
not a pullback buy, and carries a different risk profile.

---

## Position Management in Trend

### Stop Placement

```
# Hard stop: below trend invalidation level
stop_loss = trend_invalidation  # 5% below prior swing low

# Soft stop (close position, do not use stop-limit in cascade risk):
# Close manually if 1h candle closes below swing_low_prior
```

Use the **hard stop as a worst-case catastrophic protection only**. The
soft stop (manual close on 1h candle close below swing low) should fire
first in normal market conditions. Hard stops placed too close inside the
cascade zone will be hunted; place them clearly below structural support.

### Take-Profit Structure

In a trending regime, **partial profit-taking** outperforms single-target
exits because trends can extend far beyond initial projections:

```
# Measured move projection from entry:
leg_extension_100 = entry_price + trend_leg_size * 1.000   # equal leg
leg_extension_127 = entry_price + trend_leg_size * 1.272   # 1.272 extension
leg_extension_162 = entry_price + trend_leg_size * 1.618   # golden ratio extension

# Profit-taking schedule:
tp1_size = position_size * 0.35   # at 1.0× extension — lock in base profit
tp2_size = position_size * 0.40   # at 1.272× extension — core profit
tp3_size = position_size * 0.25   # trail remainder; close at 1.618× or trend break
```

After TP1 fires, **move stop to breakeven** on the remaining position.
After TP2 fires, **trail stop to prior 4h swing low** to ride the remainder.

### Trend Continuation Check (Every 4h)

```python
def trend_still_valid(candles_1h: list, oi_now: float, oi_4h_ago: float,
                      funding_1h: float) -> bool:
    hh_hl_count = count_higher_high_higher_low_sequences(candles_1h[-24:])
    oi_rising   = oi_now >= oi_4h_ago * 0.98     # allow 2% OI noise
    funding_ok  = funding_1h < 0.03
    return hh_hl_count >= 2 and oi_rising and funding_ok

# If trend_still_valid() returns False:
#   - Do not open new positions
#   - Move existing stops to breakeven
#   - Re-evaluate regime classification
```

---

## Regime Transition Handling

### Bull → Exhaustion Signals

When ANY of the following appear, demote regime to EXHAUSTED and apply
corresponding entry restrictions:

- Price makes a new high but **OI does not confirm** (OI flat or declining
  at new price high = distribution, not accumulation)
- Funding rate crosses above **0.03%/h** and holds for 2+ intervals
- A higher high is made but **volume is declining** on the breakout candle
  (volume divergence — weakening buying pressure)
- Price closes back inside a prior consolidation range after a breakout
  attempt (false breakout — likely regime change)
- The prior swing low is **breached on a 1h close** (HH/HL structure broken)

### Bull → Post-Cascade Re-Entry

When the `liquidation-cascade-risk` skill's CRITICAL protocol fires and
flattens all longs during an active trend, this skill governs re-entry
once the 5 post-cascade criteria are met (see `liquidation-cascade-risk`):

- Re-enter using **nascent trend sizing** (0.4×) initially
- Rebuild to full size only after 2 new HH/HL sequences are confirmed
  post-cascade (trend has re-established, not just bounced)
- Apply the same Fib entry framework from the post-cascade swing low as
  the new trend anchor

---

## Failure Modes to Avoid

- **Chasing breakouts at trend extension**: Entering at the moment of
  maximum bullish sentiment — new ATH, parabolic move, social media
  euphoria — is the single most common trending-market loss. The setup is
  already priced; the reward-to-risk has collapsed. Wait for the pullback.
- **Using a single Fib level as a hard entry without confirmation**: Price
  touches fib_618 dozens of times in a trend without reversing. The Fib
  level is a *zone of interest*, not a guaranteed bounce. Confirmation
  signal is mandatory.
- **Ignoring OI divergence**: A price uptrend with declining OI is
  short-covering, not genuine bull accumulation. Short-covering rallies
  exhaust faster and reverse sharper. Always check OI direction matches
  price direction before classifying as trending bull.
- **Setting stops inside the OI cluster / liquidation zone**: Stops placed
  just below a round number or prior swing low will be taken out by
  stop-hunt wicks before the real trend resumes. Invalidation level must
  be placed **below** the structural zone, not inside it.
- **Continuing to apply trending-bull entries after regime demotes to
  EXHAUSTED**: Once OI diverges from price or funding exceeds 0.03%/h,
  the trending-bull playbook no longer applies. Defer to
  `high-funding-carry-avoidance` and `liquidation-cascade-risk` skills.
- **Over-trading pullbacks in a nascent trend**: In a nascent trend (< 3
  HH/HL sequences), each pullback has a significant probability of being
  the final leg before reversal. Size accordingly (0.4×); do not apply
  full trending-bull sizing until the trend is established.

---

## Integration with Risk Controls

- **Max single-position size**: trending-bull entries are capped at the
  standard Kelly/risk-budget output from `kelly-position-sizing-perps`.
  The Fib size multipliers in this skill are applied *on top of* that
  calculation, never as a bypass of risk limits.
- **Concurrent positions**: if trending-bull setups are active on multiple
  correlated assets (e.g. BTC + ETH both pulling back simultaneously),
  total correlated exposure must not exceed **2× single-asset risk budget**.
  Scale individual sizes proportionally.
- **Session pause after stop-out**: if the trend invalidation stop fires,
  pause all new trending-bull entries on that asset for **1h**. A stop
  trigger means the trend thesis is invalidated; re-entry requires a fresh
  HH/HL sequence to re-establish, not an immediate re-entry hoping the
  stop was a wick.

### Audit JSONL Schema

```json
{
  "event": "trending_bull_entry",
  "asset": "ETH",
  "timestamp_utc": "2026-04-07T22:00:00Z",
  "regime": "established",
  "hh_hl_count": 5,
  "oi_change_4h_pct": 3.2,
  "funding_1h": 0.018,
  "swing_high": 1850.00,
  "swing_low_prior": 1740.00,
  "trend_leg_size": 110.00,
  "fib_382": 1807.82,
  "fib_500": 1795.00,
  "fib_618": 1782.18,
  "entry_price": 1791.40,
  "pullback_depth_fib": 0.531,
  "pullback_classification": "optimal",
  "confirmation_signals": ["bullish_engulfing", "cvd_inflection"],
  "base_size_usd": 12000,
  "fib_size_multiplier": 1.2,
  "adjusted_size_usd": 14400,
  "stop_loss": 1734.50,
  "tp1": 1960.00,
  "tp2": 1990.00,
  "tp3_trail": true
}
```

---

## Quick Decision Tree

```
Is price making HH/HL on 1h with rising OI and funding < 0.03%/h?
├── NO  → Not a trending bull regime. Do not apply this skill.
└── YES → Classify regime: nascent / established / mature / exhausted
              ├── EXHAUSTED → No new longs. Manage existing. Exit skill.
              └── ACTIVE    → Is price currently in a pullback?
                              ├── NO  → Wait. Do not chase. Set limit orders
                              │         at fib_382–fib_618 zone.
                              └── YES → What is pullback depth?
                                          ├── < 23.6% → 0.3× size. Weak setup.
                                          ├── 38–61.8% → Optimal zone.
                                          │           Is confirmation signal present?
                                          │           ├── YES → Enter. Apply size
                                          │           │         multiplier from table.
                                          │           └── NO  → Wait for confirmation.
                                          └── > 78.6% → Trend likely broken. Do not enter.

After entry:
  TP1 fires? → Move stop to breakeven.
  TP2 fires? → Trail stop to prior 4h swing low.
  1h close below swing low? → Close remainder immediately.
```

---

## HyperLiquid-Specific Notes

- **Mark price for Fib calculations**: Use `assetCtxs[i].markPrice` as the
  reference price for all Fibonacci level calculations, not the mid-price
  from `l2Book`. Mark price is oracle-weighted and more stable; mid-price
  can be manipulated by thin-book prints during low-liquidity periods.
- **OI data cadence**: `assetCtxs` OI updates on every REST `/info` poll
  (recommended poll interval: 10s). For real-time OI trend confirmation,
  use the WebSocket `activeAssetCtx` subscription which pushes on any
  change rather than polling.
- **Limit order placement**: HyperLiquid supports post-only limit orders
  (`tif: "Alo"` in the order object). Use `"Alo"` for all pullback
  entries to guarantee maker rebate and avoid accidental market-order
  fills during volatile pullback candles.
- **1h candle construction**: HyperLiquid does not natively serve OHLCV
  candles via the public API at time of writing. Construct 1h candles
  from the `trades` WebSocket feed or use `candleSnapshot` if available
  in the current API version. Validate candle source before applying
  HH/HL detection logic.
- **Cross-margin stop execution**: In cross-margin mode, stop-loss orders
  are executed as reduce-only limit orders. During a fast cascade, these
  may not fill. Pre-position the soft stop as a **monitored alert** with
  a manual market-order close, not as a resting order, to ensure
  execution in adverse conditions.
