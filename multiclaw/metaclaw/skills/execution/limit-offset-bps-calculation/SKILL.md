---
name: limit-offset-bps-calculation
description: Use when placing any post-only limit order on HyperLiquid to calculate the optimal price offset from mid that maximizes fill probability while preserving maker status, accounting for spread, volatility, book depth, and asset tick size.
category: agentic
---

# Limit Order Offset (BPS) Calculation

## When This Skill Activates

Apply this skill **every time an `Alo` (post-only) limit order price must
be determined** before submission. The skill answers: *how many basis
points inside or outside the spread should the limit price be placed?*

Also apply when:
- An `Alo` order was rejected (price crossed spread) and a new offset
  must be computed before reposting
- Fill rate on resting limit orders is unacceptably low and offset
  calibration needs review
- A new asset is being traded for the first time and no historical
  offset data exists yet
- Spread has widened significantly (low liquidity period, news event)
  and the standard offset is stale

---

## Core Principle

A post-only limit order placed **too far from mid** rests on the book
for a long time and may never fill — opportunity cost. Placed **too
close to mid** it risks crossing the spread on a momentary tick and
being rejected as a taker (or, with `Gtc`, accidentally paying taker
fee). The optimal offset is the minimum distance from mid that reliably
lands inside the book as a resting maker order given current spread and
volatility, without being so far away that fill probability collapses.

> **Rule**: Place limit orders at `mid ± offset_bps` where `offset_bps`
> is computed fresh from live spread and recent volatility at the time
> of each order. Never use a hardcoded static offset across all market
> conditions.

---

## Inputs Required

Fetch all of the following from HyperLiquid before computing offset:

```python
# From WebSocket l2Book or REST /info → l2Book(coin):
best_bid   = l2book["levels"][0][0]["px"]   # highest bid price
best_ask   = l2book["levels"][1][0]["px"]   # lowest ask price
mid_price  = (best_bid + best_ask) / 2
raw_spread_bps = (best_ask - best_bid) / mid_price * 10000

# From REST /info → meta + assetCtxs:
mark_price = asset_ctx["markPrice"]         # oracle mark; use for offset anchor
tick_size  = asset_meta["szDecimals"]       # price precision (decimal places)

# From recent trade history (last 50–100 trades, 5m window):
import statistics
trade_prices  = [t["px"] for t in recent_trades]
volatility_bps = statistics.stdev(trade_prices) / mid_price * 10000
# Short-window volatility: 1-sigma move in the last 5m in basis points
```

---

## Offset Calculation

### Base Offset Formula

```python
def compute_limit_offset_bps(
    raw_spread_bps: float,
    volatility_bps: float,             # 5m 1-sigma in bps
    side: str,                         # "buy" or "sell"
    order_urgency: str = "normal",     # "normal", "patient", "urgent"
    book_fragility: float = 0.0,       # 0–1; from liquidation-cascade-risk
) -> float:
    """
    Returns the offset in basis points from mid.
    Positive offset = deeper into the book (better fill safety, worse fill rate).
    """
    # Half-spread is the minimum safe distance to guarantee maker status
    half_spread_bps = raw_spread_bps / 2

    # Safety buffer: 1 tick worth of extra clearance beyond half-spread
    # Prevents rejection on micro-moves at the moment of submission
    safety_buffer_bps = max(0.5, half_spread_bps * 0.10)

    # Volatility buffer: scale with recent short-window vol to avoid
    # being crossed during order transit latency (~50–200ms on HL)
    vol_buffer_bps = volatility_bps * 0.20   # 20% of 1-sigma 5m vol

    # Base offset: half-spread + safety + vol buffer
    base_offset = half_spread_bps + safety_buffer_bps + vol_buffer_bps

    # Urgency modifier:
    urgency_multiplier = {
        "urgent":  0.5,    # closer to mid; accept higher rejection risk for better fill
        "normal":  1.0,    # standard
        "patient": 1.5,    # deeper in book; lower rejection risk; slower fill
    }[order_urgency]

    # Book fragility modifier: widen offset when book is thin
    # (thin books = higher vol transit risk = needs more clearance)
    fragility_multiplier = 1.0 + (book_fragility * 0.5)

    offset_bps = base_offset * urgency_multiplier * fragility_multiplier

    # Clamp: never closer than 0.5 bps (tick noise floor)
    #        never farther than 5.0 bps (fill probability collapses)
    return max(0.5, min(5.0, offset_bps))
```

### Applying Offset to Order Price

```python
def compute_limit_price(
    mid_price: float,
    offset_bps: float,
    side: str,
    tick_size_decimals: int,
) -> float:
    """
    Buy orders: place BELOW mid (offset into bid side)
    Sell orders: place ABOVE mid (offset into ask side)
    Round to asset tick size to avoid rejection for invalid price precision.
    """
    offset_price = mid_price * (offset_bps / 10000)

    if side == "buy":
        raw_price = mid_price - offset_price
    else:  # sell
        raw_price = mid_price + offset_price

    # Round to valid tick size (round down for buys, up for sells
    # to stay on the correct side of mid after rounding)
    factor = 10 ** tick_size_decimals
    if side == "buy":
        return math.floor(raw_price * factor) / factor
    else:
        return math.ceil(raw_price * factor) / factor
```

---

## Offset Calibration by Market Condition

### Spread Regime Classification

Classify current spread before applying offset to set urgency defaults:

| Spread (bps) | Regime | Suggested Urgency | Notes |
|---|---|---|---|
| < 1.0 | Tight | `normal` | Liquid; standard offset works well |
| 1.0–2.5 | Normal | `normal` | Typical for mid-cap perps |
| 2.5–5.0 | Wide | `patient` | Low liquidity; widen offset or wait |
| 5.0–10.0 | Very wide | `patient` + size reduction | Consider deferring non-urgent entries |
| > 10.0 | Illiquid | Defer or use `Ioc` taker if urgent | Maker fill unlikely at reasonable offset |

> When spread > 10 bps and the entry is time-critical, the cost of
> waiting for a maker fill (missing the move) may exceed taker fee.
> Defer to `maker-order-preference-fee-reduction` for the explicit
> taker-vs-maker decision; this skill only handles the offset calculation
> for the maker path.

### Volatility Regime Adjustment

| 5m Volatility (bps) | Vol Regime | vol_buffer_bps | Effect on Offset |
|---|---|---|---|
| < 2 | Low vol | 0.4 | Offset stays near minimum |
| 2–5 | Normal vol | 0.4–1.0 | Standard offset range |
| 5–10 | Elevated vol | 1.0–2.0 | Offset widens meaningfully |
| 10–20 | High vol | 2.0–4.0 | Approach upper clamp; consider `patient` |
| > 20 | Extreme vol | Clamp at 5.0 | Near-cascade conditions; see `liquidation-cascade-risk` |

---

## Asset-Specific Tick Size Reference

HyperLiquid enforces strict price precision per asset. Submitting an
order with more decimal places than allowed causes immediate rejection.

```python
# Always fetch live from /info → meta:
asset_tick_map = {
    asset["name"]: asset["szDecimals"]
    for asset in meta["universe"]
}

# Common values at time of writing (verify live — do not hardcode):
# BTC:  1 decimal place  (e.g. 91450.0)
# ETH:  2 decimal places (e.g. 1791.40)
# SOL:  3 decimal places (e.g. 138.250)
# ARB:  5 decimal places (e.g. 0.47820)
# DOGE: 6 decimal places (e.g. 0.072340)
```

The `compute_limit_price()` function above handles rounding automatically
when `tick_size_decimals` is passed correctly. **Always fetch tick size
from live `meta`, never hardcode it.**

---

## Worked Examples

### Example 1 — BTC, Normal Conditions

```
Inputs:
  mid_price       = 91,500.00
  best_bid        = 91,494.00
  best_ask        = 91,506.00
  raw_spread_bps  = 12 / 91,500 * 10,000 = 1.31 bps
  volatility_bps  = 3.2 bps  (last 5m trades)
  side            = "buy"
  urgency         = "normal"
  book_fragility  = 0.10

Calculation:
  half_spread     = 0.655 bps
  safety_buffer   = max(0.5, 0.655 * 0.10) = 0.50 bps
  vol_buffer      = 3.2 * 0.20 = 0.64 bps
  base_offset     = 0.655 + 0.50 + 0.64 = 1.795 bps
  urgency_mult    = 1.0
  fragility_mult  = 1.0 + (0.10 * 0.5) = 1.05
  offset_bps      = 1.795 * 1.0 * 1.05 = 1.885 bps  → clamped to range: 1.885

Limit price:
  offset_price    = 91,500 * (1.885 / 10,000) = 1.725
  raw_price       = 91,500 - 1.725 = 91,498.275
  tick_size       = 1 decimal → floor to 91,498.2

Order submitted: BUY limit 91,498.2  (Alo, tif="Alo")
```

### Example 2 — ETH, Elevated Volatility

```
Inputs:
  mid_price       = 1,792.00
  raw_spread_bps  = 2.80 bps
  volatility_bps  = 8.5 bps  (elevated; approaching news event)
  side            = "sell" (TP exit)
  urgency         = "patient"
  book_fragility  = 0.25

Calculation:
  half_spread     = 1.40 bps
  safety_buffer   = max(0.5, 1.40 * 0.10) = 0.50 bps
  vol_buffer      = 8.5 * 0.20 = 1.70 bps
  base_offset     = 1.40 + 0.50 + 1.70 = 3.60 bps
  urgency_mult    = 1.5  (patient)
  fragility_mult  = 1.0 + (0.25 * 0.5) = 1.125
  offset_bps      = 3.60 * 1.5 * 1.125 = 6.075 bps  → clamped to 5.0 bps

Limit price:
  offset_price    = 1,792 * (5.0 / 10,000) = 0.896
  raw_price       = 1,792 + 0.896 = 1,792.896
  tick_size       = 2 decimals → ceil to 1,792.90

Order submitted: SELL limit 1,792.90  (Alo, tif="Alo")
```

---

## Fill Rate Monitoring and Self-Calibration

MetaClaw’s skills auto-evolve from deployment experience. To enable
this skill to improve its offset calibration over time, log sufficient
data for the RL replay buffer:

```json
{
  "event": "limit_order_offset_calc",
  "asset": "BTC",
  "timestamp_utc": "2026-04-07T22:00:00Z",
  "side": "buy",
  "mid_price": 91500.00,
  "raw_spread_bps": 1.31,
  "volatility_bps_5m": 3.2,
  "book_fragility": 0.10,
  "urgency": "normal",
  "offset_bps_computed": 1.885,
  "limit_price": 91498.2,
  "order_result": "filled",        // "filled", "partial", "expired", "rejected"
  "fill_latency_seconds": 14.3,    // time from placement to fill
  "fill_price": 91498.2,
  "slippage_bps": 0
}
```

### Fill Rate Thresholds for Recalibration

If the rolling 50-order fill rate for a given asset falls outside the
acceptable range, recalibrate the offset multipliers:

| Fill Rate | Diagnosis | Recalibration Action |
|---|---|---|
| > 95% | Offset too deep | Reduce `urgency_multiplier` by 0.1; or reduce `safety_buffer` |
| 80–95% | Optimal range | No change |
| 60–80% | Offset borderline | Review spread regime; check for persistent wide spread |
| < 60% | Offset too tight | Increase `vol_buffer` coefficient (0.20 → 0.25); or switch urgency to `patient` |
| High rejection rate | Alo crossing spread | Increase `safety_buffer` to 1.0 bps; review mid-price staleness |

---

## Failure Modes to Avoid

- **Using a static offset across all assets and conditions**: BTC at
  1 bps spread needs a different offset than DOGE at 8 bps spread.
  Offset must be computed per-asset per-order from live data.
- **Anchoring to `mid_price` from a stale snapshot**: Mid-price from
  the last REST poll may be 200–500ms old on a fast market. Use the
  WebSocket `l2Book` subscription for real-time mid when placing orders
  in volatile conditions (`volatility_bps > 5`).
- **Ignoring tick size rounding direction**: Rounding a buy limit price
  *up* instead of *down* can push it above best ask, crossing the spread
  and triggering `Alo` rejection. Always floor buy prices and ceil sell
  prices after offset application.
- **Applying the upper clamp (5.0 bps) as a routine offset**: The 5.0 bps
  clamp is a safety ceiling, not a target. Consistently hitting the clamp
  means market conditions are too volatile or illiquid for maker execution;
  the correct response is to defer the order, not to accept a 5 bps
  penalty as standard.
- **Not refreshing offset on order re-queue**: If an `Alo` order expires
  or is cancelled and must be reposted, **recompute the offset from fresh
  data**. Market conditions at repost time may be materially different
  from the original placement.
- **Conflating offset with slippage**: Offset is the deliberate distance
  placed *into the book* on the maker side. Slippage is unintended price
  deviation on taker fills. They are separate quantities; do not use
  slippage tolerance parameters to govern maker order offsets.

---

## Integration with Other Skills

- **`maker-order-preference-fee-reduction`** (execution/): Run first to
  decide *whether* to use `Alo`. This skill runs second to decide *where*
  to place the `Alo` order. They are always used together.
- **`slippage-budget-enforcement`** (execution/): For taker orders, that
  skill governs the price tolerance. This skill is maker-path only.
- **`liquidation-cascade-risk`** (regime-detection/): Passes
  `book_fragility` score as an input to this skill’s offset formula.
  Higher fragility → wider offset → less chance of `Alo` rejection
  from a volatile book.
- **`trending-bull-entry-timing`** (regime-detection/): Provides
  the Fibonacci target price as the *anchor* for the offset calculation.
  This skill computes the final submitted price around that anchor.

---

## Quick Decision Tree

```
Need to place an Alo limit order — what price?
│
├── 1. Fetch live l2Book → best_bid, best_ask, mid_price
├── 2. Compute raw_spread_bps and volatility_bps (last 5m trades)
├── 3. Get book_fragility from liquidation-cascade-risk if available
├── 4. Classify spread regime (tight / normal / wide / illiquid)
│     └── Illiquid (> 10 bps)? → Defer or escalate to taker decision
├── 5. Set urgency: normal (default) / patient (wide spread or low urgency)
├── 6. Run compute_limit_offset_bps() → offset_bps
├── 7. Run compute_limit_price() with tick_size from live meta → limit_price
├── 8. Submit order with tif="Alo" at computed limit_price
│
├── Alo FILLS → log event with fill_latency. Done.
├── Alo REJECTS → price moved. Recompute offset from fresh data. Reassess entry.
└── Alo EXPIRES (GTC timeout) → Recompute. Re-evaluate setup validity.
```
