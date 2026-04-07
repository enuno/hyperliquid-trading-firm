---
name: maker-order-preference-fee-reduction
description: Use when placing any perpetual order on HyperLiquid to minimize fees via maker (post-only) order preference, understand when taker execution is justified, and calculate break-even fee impact on trade edge.
category: agentic
---

# Maker Order Preference — Fee Reduction

## When This Skill Activates

Apply this skill **on every order placement decision** for HyperLiquid
perpetual positions. Fee structure directly impacts realized edge —
a strategy with a 0.10% expected move and 0.12% round-trip taker cost
has negative expected value before any other consideration.

Also apply when:
- Sizing a position where the entry method (maker vs. taker) meaningfully
  changes whether the trade has positive expected value
- Evaluating whether to close a winning position via limit or market order
- Managing a partial fill situation where the remainder must be re-queued
- Designing execution logic for any automated strategy component

---

## Core Principle

On HyperLiquid, the fee differential between maker and taker is **not
marginal — it is structural**. Maker orders add liquidity and earn a
rebate; taker orders remove liquidity and pay a fee. At meaningful
position sizes, this difference compounds across hundreds of trades into
a significant drag or tailwind on overall P&L.

> **Rule**: Default to maker (post-only) for all entries and exits
> where fill certainty is not time-critical. Reserve taker execution
> for defensive exits, cascade closures, and time-sensitive entries
> where the cost of missing the fill exceeds the fee premium.

---

## HyperLiquid Fee Structure

### Current Maker/Taker Schedule (Verify at `/info → meta` before trading)

| Tier | 30d Volume (USD) | Maker Fee | Taker Fee | Maker Rebate vs. Taker |
|---|---|---|---|
| Base | < $1M | -0.010% (rebate) | +0.035% | 0.045% per side |
| Tier 1 | $1M–10M | -0.010% (rebate) | +0.035% | 0.045% per side |
| Tier 2 | $10M–100M | -0.012% (rebate) | +0.030% | 0.042% per side |
| Tier 3 | > $100M | -0.014% (rebate) | +0.025% | 0.039% per side |

> **Always fetch the live fee schedule** via `/info` before computing
> break-even targets — HyperLiquid has updated fees historically and
> may do so again. Never hardcode fee values in strategy logic.

### Round-Trip Cost Comparison

```
# Base tier, per $10,000 notional:
maker_round_trip = (-0.010% + -0.010%) × $10,000 = -$2.00   (net rebate earned)
taker_round_trip = (+0.035% + +0.035%) × $10,000 = +$7.00   (net fee paid)

differential_per_10k = $9.00   # maker earns $9 more than taker per $10k notional
```

At $100k notional per trade, maker vs. taker is a **$90 differential per
round trip**. For a strategy doing 10 round trips/day, that is $900/day
or ~$270,000/year — entirely from order type selection.

---

## Order Type Reference

### Post-Only Limit (Maker) — `tif: "Alo"`

```json
{
  "orders": [{
    "a": 0,
    "b": true,
    "p": "91500.0",
    "s": "0.1",
    "r": false,
    "t": {"limit": {"tif": "Alo"}}
  }],
  "grouping": "na"
}
```

- `"Alo"` = **Add Liquidity Only** (post-only). Order is **rejected
  immediately** if it would cross the spread and execute as a taker.
- Earns maker rebate on fill.
- Use for: all pullback entries, all TP limit orders, non-urgent exits.
- **Handling rejection**: if `"Alo"` rejects, the price has moved through
  your limit. Reassess entry — do not automatically retry as taker
  unless the defensive exit protocol applies.

### GTC Limit (May Cross) — `tif: "Gtc"`

```json
{"t": {"limit": {"tif": "Gtc"}}}
```

- Rests on the book as maker if it doesn’t immediately cross; executes
  as **taker if it does cross** at time of placement.
- Risk: if market moves to your limit at the exact moment of placement,
  you pay taker fee unexpectedly.
- Use only when order placement timing is not your control (e.g., a
  bracket order placed simultaneously with an entry).
- **Prefer `"Alo"` over `"Gtc"` whenever maker-only execution is the
  intent.**

### Immediate-or-Cancel Market-Like — `tif: "Ioc"`

```json
{"t": {"limit": {"tif": "Ioc"}}}
```

- Fills immediately at available prices; cancels any unfilled remainder.
- Always pays taker fee.
- Use for: cascade exits, kill-switch execution, time-sensitive defensive
  closures where fill certainty outweighs fee cost.

### Market Order

```json
{"t": {"market": {}}}
```

- Guaranteed fill at best available price.
- Always pays taker fee; highest slippage risk.
- Use for: emergency exits only (cascade CRITICAL, kill-switch trigger,
  liquidation prevention). **Never use for routine entries or exits.**

---

## Break-Even Fee Calculation

Before placing any order, compute whether the expected move justifies
the fee cost at the chosen order type:

```python
def fee_break_even(
    expected_move_pct: float,
    entry_tif: str,        # "Alo" or "Ioc"/market
    exit_tif: str,         # "Alo" or "Ioc"/market
    maker_fee: float = -0.00010,   # fetch live; base tier default
    taker_fee: float = 0.00035,
    leverage: float = 1.0,
) -> dict:
    entry_fee = maker_fee if entry_tif == "Alo" else taker_fee
    exit_fee  = maker_fee if exit_tif  == "Alo" else taker_fee
    round_trip_fee = entry_fee + exit_fee

    # On a leveraged position, fees are on notional but P&L is on margin:
    fee_on_margin = round_trip_fee * leverage

    net_edge = expected_move_pct - round_trip_fee   # on notional
    net_edge_on_margin = (expected_move_pct / leverage) - round_trip_fee  # ROE basis

    return {
        "round_trip_fee_pct": round_trip_fee * 100,
        "net_edge_on_notional_pct": net_edge * 100,
        "net_edge_on_margin_pct": net_edge_on_margin * 100,
        "is_positive_ev": net_edge > 0,
        "minimum_move_to_break_even_pct": round_trip_fee * 100,
    }

# Example: 0.10% expected move, maker entry + maker exit, 5x leverage
# round_trip_fee = -0.010% + -0.010% = -0.020% (net rebate)
# net_edge_on_notional = 0.10% - (-0.020%) = +0.120%  → positive EV
#
# Same trade with taker entry + taker exit:
# round_trip_fee = 0.035% + 0.035% = 0.070%
# net_edge_on_notional = 0.10% - 0.070% = +0.030%  → still positive, but 4x smaller edge
```

### Minimum Edge Requirements by Order Type Combination

| Entry | Exit | Round-Trip Cost | Min Move to Break Even |
|---|---|---|---|
| Maker (`Alo`) | Maker (`Alo`) | -0.020% (rebate) | Any positive move |
| Maker (`Alo`) | Taker (`Ioc`) | +0.025% | > 0.025% |
| Taker (`Ioc`) | Maker (`Alo`) | +0.025% | > 0.025% |
| Taker (`Ioc`) | Taker (`Ioc`) | +0.070% | > 0.070% |
| Market | Market | +0.070% + slippage | > 0.070% + slippage |

> **Implication**: Taker-in / taker-out strategies require a **minimum
> 0.07% move** just to cover fees before slippage. Scalps targeting
> < 0.10% moves should only be attempted with maker execution on both
> legs, or the fee structure eliminates the edge entirely.

---

## Execution Decision Framework

### Entry Order Selection

```
Is this entry time-critical (cascade re-entry, breakout momentum)?
├── YES → Is the expected move > 0.10%?
│         ├── YES → Use Ioc taker. Fee justified by urgency + edge.
│         └── NO  → Skip entry. Taker fee eats the edge; wait for pullback.
└── NO  → Use Alo post-only limit at target price.
              If Alo rejects: reassess. Do NOT auto-retry as taker.
```

### Exit Order Selection

```
Is this a defensive/emergency exit (cascade, kill-switch, stop-loss breach)?
├── YES → Use market order or Ioc. Fill certainty > fee cost.
└── NO  → Is the TP target more than 0.05% from current price?
              ├── YES → Use Alo post-only limit at TP level.
              └── NO  → Consider Ioc if the fill window is very tight
                          and missing the target risks a reversal.
```

### Partial Fill Handling

When an `"Alo"` order partially fills and the remainder is sitting on
the book:

1. **Do not cancel and repost as taker** unless a defensive exit
   trigger has fired
2. Check if the remainder is within **0.1% of current mid** — if so,
   allow it to rest and fill naturally
3. If price has moved > 0.3% away from the resting order, cancel
   and reassess entry level — the setup may no longer be valid
4. Log partial fills to audit JSONL so the RL replay buffer captures
   the fill quality distribution for this strategy

---

## Fee Impact on Strategy-Level P&L

### Compounding Fee Drag Across Trade Frequency

```python
def annual_fee_impact(
    trades_per_day: int,
    avg_notional_per_trade: float,
    taker_pct: float = 1.0,    # fraction of trades using taker
    maker_fee: float = -0.00010,
    taker_fee: float = 0.00035,
) -> dict:
    maker_pct = 1.0 - taker_pct
    avg_fee = (maker_pct * maker_fee + taker_pct * taker_fee) * 2  # round-trip
    daily_fee = avg_fee * avg_notional_per_trade * trades_per_day
    annual_fee = daily_fee * 365
    return {"daily_usd": daily_fee, "annual_usd": annual_fee}

# Example: 5 trades/day, $20k notional each, 100% taker:
# annual_fee = 0.070% × $20,000 × 5 × 365 = $25,550/year paid in fees
#
# Same strategy, 100% maker:
# annual_fee = -0.020% × $20,000 × 5 × 365 = -$7,300/year (rebate earned)
#
# Differential: $32,850/year from order type choice alone
```

### Fee Attribution in Backtesting

All backtests **must** model fees at the order-type level, not as a
flat percentage:

```python
# In agentharness.py backtest loop:
def apply_fee(notional: float, order_type: str, fee_schedule: dict) -> float:
    if order_type in ("Alo", "maker"):
        return notional * fee_schedule["maker"]   # negative = rebate
    elif order_type in ("Ioc", "market", "taker"):
        return notional * fee_schedule["taker"]   # positive = cost
    raise ValueError(f"Unknown order type: {order_type}")
```

Backtests that assume a flat fee (e.g. 0.02% per side) overstate the
cost of maker strategies and understate the cost of taker strategies.
The distortion can flip a maker strategy from positive to negative
Sharpe and vice versa.

---

## Failure Modes to Avoid

- **Auto-retrying `Alo` rejections as taker**: An `Alo` rejection means
  the market moved through your limit price before the order landed.
  Retrying as taker chases a move that has already happened and pays
  the full fee spread on a potentially overextended entry.
- **Using market orders for TP exits**: Market orders on exit pay taker
  fee and incur slippage. A TP level that is already > 0.05% away from
  current price should always be a resting `Alo` limit — there is no
  urgency on a profitable exit that warrants paying taker fees.
- **Ignoring fee structure in scalp strategy design**: Any strategy
  targeting < 0.05% moves with taker execution is structurally
  unprofitable at base tier fees. Fee structure must be an input to
  strategy design, not an afterthought.
- **Assuming fees are constant**: HyperLiquid has changed its fee schedule
  historically. Always fetch the live schedule from `/info → meta` at
  session start and invalidate any cached fee values older than 24h.
- **Overlooking the fee-on-notional vs. fee-on-margin distinction**:
  At 10× leverage, a 0.035% taker fee on notional is 0.35% on margin.
  A strategy targeting a 0.30% ROE on margin is immediately underwater
  on a taker round trip at 10× leverage. Always state and calculate
  fees on the correct basis for the strategy’s risk framework.
- **Misclassifying `Gtc` as a guaranteed maker order**: `Gtc` will cross
  the spread and pay taker if placed when market price is inside the
  order price. Only `Alo` guarantees post-only execution. Use `Alo`
  when maker fee is the intent.

---

## Integration with Other Skills

- **`limit-offset-bps-calculation`** (execution/): Defines how far
  inside/outside the spread to place `Alo` orders to maximise fill
  probability without crossing. Run that skill first to determine the
  limit price; this skill determines the `tif` parameter.
- **`liquidation-cascade-risk`** (regime-detection/): CRITICAL and HIGH
  cascade protocols override maker preference. During cascade exits,
  fill certainty always takes priority over fee optimization.
- **`high-funding-carry-avoidance`** (regime-detection/): Kill-switch
  exits triggered by funding + drawdown conditions use market/`Ioc`
  orders regardless of fee impact. Fee optimization never delays a
  risk-mandated exit.

---

## Audit JSONL Schema

```json
{
  "event": "order_placement",
  "asset": "BTC",
  "timestamp_utc": "2026-04-07T22:00:00Z",
  "side": "buy",
  "notional_usd": 15000,
  "order_type": "Alo",
  "limit_price": 91450.00,
  "tif": "Alo",
  "fee_rate_pct": -0.010,
  "fee_usd": -1.50,
  "fill_status": "filled",
  "fill_price": 91450.00,
  "slippage_bps": 0,
  "rationale": "pullback_entry_fib_500",
  "defensive_override": false
}
```

Log `defensive_override: true` whenever taker execution is chosen
for a risk-mandated reason. This allows the RL replay buffer to
learn the correct fee-vs-fill-certainty tradeoff rather than penalising
all taker executions uniformly.

---

## Quick Decision Tree

```
New order to place — what tif?
│
├── DEFENSIVE EXIT (cascade/kill-switch/stop breach)?
│     └── YES → Market or Ioc. Fee irrelevant. Speed is everything.
│
├── TIME-CRITICAL ENTRY (breakout/post-cascade re-entry)?
│     ├── YES + expected move > 0.10% → Ioc taker. Justified.
│     └── YES + expected move ≤ 0.10% → Skip. Fee kills the edge.
│
└── ALL OTHER ENTRIES AND EXITS → Alo post-only limit.
      ├── Alo fills → earn maker rebate. Log fee_rate = -0.010%.
      └── Alo rejects → price moved. Reassess. Do NOT retry as taker.
```
