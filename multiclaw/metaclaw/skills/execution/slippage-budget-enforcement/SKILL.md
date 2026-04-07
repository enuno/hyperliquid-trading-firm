---
name: slippage-budget-enforcement
description: Use when executing any taker (Ioc or market) order on HyperLiquid to calculate the maximum allowable slippage budget, enforce price tolerance before submission, detect post-fill slippage violations, and abort or resize orders that would exceed the session slippage cap.
category: agentic
---

# Slippage Budget Enforcement

## When This Skill Activates

Apply this skill **on every taker order** (`tif: "Ioc"` or market) before
submission and again after fill confirmation. Also apply when:

- A maker (`Alo`) order has been rejected and taker execution is being
  considered as fallback
- A cascade exit or kill-switch triggers a market order and a worst-case
  slippage estimate is needed for position sizing the exit
- Session-level slippage has accumulated and a new taker order would
  breach the session cap
- Book depth has thinned significantly and the expected fill price for
  a given size must be estimated before committing

---

## Core Principle

Slippage on taker orders is **not random noise** — it is a predictable
function of order size relative to available book depth. Large taker
orders walk the book, consuming successive price levels and filling at
proggressively worse prices. On HyperLiquid’s thin-book perp markets,
a $50k market order in low-liquidity conditions can incur 10–20 bps of
slippage — equivalent to paying taker fee *twice*.

> **Rule**: Before submitting any taker order, simulate the fill by
> walking the live order book. If the simulated slippage exceeds the
> order’s slippage budget, either reduce order size or abort.
> Never submit a taker order blind.

---

## Slippage Budget Framework

### Per-Order Slippage Budget

The per-order slippage budget is derived from the trade’s expected edge
minus the taker fee already accounted for in `maker-order-preference-fee-reduction`:

```python
def per_order_slippage_budget_bps(
    expected_move_bps: float,       # from strategy signal
    taker_fee_bps: float = 3.5,     # base tier: 0.035% = 3.5 bps
    min_net_edge_bps: float = 2.0,  # minimum edge to keep after all costs
) -> float:
    """
    Maximum slippage that still leaves a minimum net edge after
    taker fee and slippage are both deducted.
    """
    budget = expected_move_bps - taker_fee_bps - min_net_edge_bps
    return max(0.0, budget)  # 0.0 = no slippage tolerance; do not trade

# Example: expected move = 15 bps, taker fee = 3.5 bps, min edge = 2 bps
# slippage_budget = 15 - 3.5 - 2.0 = 9.5 bps
#
# Example: expected move = 8 bps
# slippage_budget = 8 - 3.5 - 2.0 = 2.5 bps  (very tight; consider maker entry)
#
# Example: expected move = 5 bps
# slippage_budget = 5 - 3.5 - 2.0 = -0.5 → clamped to 0.0
# → Do not use taker. Taker fee alone consumes more than expected move minus min edge.
```

### Session Slippage Cap

Beyond per-order budgets, enforce a hard **session-level slippage cap**
to prevent cumulative slippage from silently eroding P&L:

```python
SESSION_SLIPPAGE_CAP_BPS = 20.0   # total across all taker fills in session
SESSION_SLIPPAGE_WARN_BPS = 15.0  # warning threshold: reduce taker aggression

# Session tracking (in-memory; reset at session start):
class SlippageTracker:
    def __init__(self):
        self.session_slippage_bps: float = 0.0
        self.taker_fills: list = []

    def record_fill(self, expected_price: float, fill_price: float,
                    side: str, notional_usd: float) -> float:
        if side == "buy":
            slippage_bps = (fill_price - expected_price) / expected_price * 10000
        else:
            slippage_bps = (expected_price - fill_price) / expected_price * 10000
        slippage_bps = max(0.0, slippage_bps)  # only count adverse slippage
        self.session_slippage_bps += slippage_bps
        self.taker_fills.append({
            "expected_price": expected_price,
            "fill_price": fill_price,
            "slippage_bps": slippage_bps,
            "notional_usd": notional_usd,
        })
        return slippage_bps

    def can_place_taker(self, estimated_slippage_bps: float) -> tuple[bool, str]:
        projected = self.session_slippage_bps + estimated_slippage_bps
        if projected >= SESSION_SLIPPAGE_CAP_BPS:
            return False, "session_cap_breached"
        if self.session_slippage_bps >= SESSION_SLIPPAGE_WARN_BPS:
            return True, "warning_reduce_size"
        return True, "ok"
```

---

## Book Walk Simulation

Before submitting any taker order, simulate the fill by walking the
live `l2Book` to estimate expected fill price and slippage:

```python
def simulate_taker_fill(
    l2book: dict,
    side: str,           # "buy" consumes asks; "sell" consumes bids
    order_size_usd: float,
    mid_price: float,
) -> dict:
    """
    Walk the order book to estimate average fill price and slippage
    for a taker order of order_size_usd notional.
    Returns fill estimate with slippage_bps and fill_coverage_pct.
    """
    levels = l2book["levels"][1] if side == "buy" else l2book["levels"][0]
    # levels format: [{"px": price_str, "sz": size_str, "n": num_orders}, ...]
    # buy: walk asks ascending; sell: walk bids descending

    remaining_usd = order_size_usd
    total_cost    = 0.0
    total_filled  = 0.0

    for level in levels:
        level_px   = float(level["px"])
        level_sz   = float(level["sz"])   # size in base asset
        level_usd  = level_sz * level_px

        fill_usd   = min(remaining_usd, level_usd)
        fill_sz    = fill_usd / level_px

        total_cost   += fill_sz * level_px
        total_filled += fill_sz
        remaining_usd -= fill_usd

        if remaining_usd <= 0:
            break

    if total_filled == 0:
        return {"feasible": False, "reason": "no_book_depth"}

    avg_fill_price = total_cost / total_filled
    fill_coverage  = (order_size_usd - remaining_usd) / order_size_usd

    if side == "buy":
        slippage_bps = (avg_fill_price - mid_price) / mid_price * 10000
    else:
        slippage_bps = (mid_price - avg_fill_price) / mid_price * 10000

    return {
        "feasible": fill_coverage >= 0.95,   # require 95% fill or reject
        "avg_fill_price": avg_fill_price,
        "slippage_bps": max(0.0, slippage_bps),
        "fill_coverage_pct": fill_coverage * 100,
        "unfilled_usd": remaining_usd,
        "levels_consumed": sum(1 for _ in levels),  # approximate
    }
```

### Interpreting Book Walk Results

| Result | Condition | Action |
|---|---|---|
| `feasible: True`, slippage ≤ budget | Full fill, within budget | Submit order as sized |
| `feasible: True`, slippage > budget | Full fill but too costly | Reduce size until slippage ≤ budget |
| `feasible: False`, coverage < 95% | Insufficient depth | Reduce size to available depth × 0.80 |
| `feasible: False`, no depth | Book empty / extreme cascade | Abort. Use `liquidation-cascade-risk` protocol |

---

## Size Reduction to Meet Slippage Budget

When the simulated slippage exceeds budget, binary-search for the
maximum order size that stays within budget:

```python
def max_size_within_budget(
    l2book: dict,
    side: str,
    mid_price: float,
    slippage_budget_bps: float,
    initial_size_usd: float,
    min_size_usd: float = 100.0,
) -> float:
    """
    Binary search for largest order size whose simulated slippage
    is <= slippage_budget_bps. Returns 0.0 if min_size_usd also exceeds budget.
    """
    lo, hi = min_size_usd, initial_size_usd
    for _ in range(12):   # 12 iterations -> 0.02% precision
        mid_size = (lo + hi) / 2
        result = simulate_taker_fill(l2book, side, mid_size, mid_price)
        if not result["feasible"] or result["slippage_bps"] > slippage_budget_bps:
            hi = mid_size
        else:
            lo = mid_size
    # Final check at lo:
    result = simulate_taker_fill(l2book, side, lo, mid_price)
    if not result["feasible"] or result["slippage_bps"] > slippage_budget_bps:
        return 0.0   # even minimum size exceeds budget; abort
    return lo
```

---

## Pre-Submission Enforcement Checklist

Run this checklist **in order** before every taker order submission:

```
1. Compute per-order slippage budget:
   budget_bps = per_order_slippage_budget_bps(expected_move_bps)
   └── budget_bps == 0.0?  → ABORT. Taker fee alone kills the edge.

2. Check session cap:
   can_place, status = tracker.can_place_taker(estimated_slippage_bps)
   ├── can_place == False  → ABORT. Session slippage cap reached.
   └── status == "warning_reduce_size"  → Halve order size before continuing.

3. Simulate book walk:
   sim = simulate_taker_fill(l2book, side, order_size_usd, mid_price)
   ├── sim.feasible == False  → Reduce size per depth or ABORT.
   └── sim.slippage_bps > budget_bps  → Run max_size_within_budget().
                                        ├── adjusted_size > 0  → Continue at adjusted size.
                                        └── adjusted_size == 0  → ABORT.

4. Submit order at adjusted_size with price_tolerance:
   worst_acceptable_price = mid_price ± (budget_bps / 10000 * mid_price)
   # Use this as the limit price on an Ioc order to cap worst-case fill:
   # {"t": {"limit": {"tif": "Ioc"}}, "p": worst_acceptable_price, ...}
   # Do NOT use pure market orders unless cascade/kill-switch override.

5. Post-fill: record actual slippage via tracker.record_fill()
   └── actual_slippage_bps > budget_bps?  → Log violation. Flag for review.
```

---

## Defensive Override: Cascade and Kill-Switch Exits

When a **CRITICAL cascade exit** or **kill-switch** fires, the slippage
budget framework is **suspended** — fill certainty takes absolute
priority over cost:

```python
def submit_defensive_exit(
    side: str,
    size_usd: float,
    mid_price: float,
    reason: str,   # "cascade_critical", "kill_switch", "stop_breach"
) -> dict:
    # No budget check. No book walk. Submit market order immediately.
    order = {
        "orders": [{
            "a": asset_index,
            "b": side == "buy",
            "p": "0",       # market order price field (ignored)
            "s": str(size_base_asset),
            "r": True,      # reduce-only
            "t": {"market": {}}
        }],
        "grouping": "na"
    }
    # Log defensive override for RL replay buffer:
    log_event({
        "event": "defensive_exit",
        "reason": reason,
        "size_usd": size_usd,
        "slippage_budget_suspended": True,
        "estimated_slippage_bps": simulate_taker_fill(
            l2book, side, size_usd, mid_price
        ).get("slippage_bps", "unknown"),
    })
    return order
```

Log the estimated slippage **even on defensive exits** so the RL replay
buffer learns the true cost of cascade conditions and can incorporate
that into future position-sizing decisions.

---

## Slippage by Asset and Condition Reference

Typical observed slippage ranges on HyperLiquid for a **$10k taker
order** under different book conditions (verify from live fills):

| Asset | Normal Book | Thin Book | During Cascade |
|---|---|---|---|
| BTC | 0.2–0.5 bps | 1–3 bps | 5–20 bps |
| ETH | 0.3–0.8 bps | 1.5–4 bps | 8–25 bps |
| SOL | 0.5–1.5 bps | 3–8 bps | 15–40 bps |
| Mid-cap alts | 1–3 bps | 5–15 bps | 20–100+ bps |

> These are **illustrative estimates**, not guarantees. Always use the
> live book walk simulation for actual order sizing. Slippage during
> cascades can exceed these ranges significantly.

---

## Failure Modes to Avoid

- **Submitting market orders without book walk**: Market orders on thin
  books can fill 10–50 bps worse than expected. Even for defensive exits,
  estimate the slippage and log it — the data informs future sizing.
- **Setting slippage tolerance as a fixed percentage**: A fixed 0.1%
  tolerance ignores current book depth, asset liquidity, and order size.
  Slippage tolerance must be computed per-order from the budget framework.
- **Reusing a stale book walk result**: The l2Book snapshot used for
  simulation must be fetched **at submission time**, not cached from the
  last polling cycle. In volatile markets, book depth changes in < 1s.
- **Not splitting large taker orders**: If `max_size_within_budget()`
  returns a size much smaller than the target, consider splitting into
  multiple smaller taker orders spaced 500ms–1s apart to allow the
  book to replenish between fills. Never send all size simultaneously
  against a thin book.
- **Ignoring `fill_coverage_pct`**: A simulated fill that only covers
  70% of the order size will leave 30% unfilled as `Ioc` remainder.
  That remainder may need a separate maker order to complete, changing
  the execution plan and cost model.
- **Double-counting slippage and taker fee**: Slippage (adverse price
  movement through the book) and taker fee (exchange charge on notional)
  are separate costs. The slippage budget framework accounts for both
  independently. Do not lump them together in a single "cost" estimate.

---

## Integration with Other Skills

- **`maker-order-preference-fee-reduction`** (execution/): Determines
  *whether* taker execution is warranted. This skill governs *how much*
  slippage is acceptable once taker is chosen. Always run in sequence.
- **`limit-offset-bps-calculation`** (execution/): Governs the maker
  path. If this skill’s budget check returns `0.0` (taker not viable),
  fall back to that skill to place an `Alo` limit instead.
- **`liquidation-cascade-risk`** (regime-detection/): Cascade CRITICAL
  overrides this skill’s budget enforcement. Also provides `book_fragility`
  which sets the expectation for how bad slippage will be before the
  book walk is run.
- **`kelly-position-sizing-perps`** (risk/): Position size output from
  Kelly sizing is the `initial_size_usd` input to `max_size_within_budget()`.
  If the book cannot absorb the Kelly size within the slippage budget,
  the executed size must be reduced; the risk model must be informed of
  the actual executed size for exposure tracking.

---

## Audit JSONL Schema

```json
{
  "event": "taker_order_slippage_check",
  "asset": "SOL",
  "timestamp_utc": "2026-04-07T22:00:00Z",
  "side": "sell",
  "target_size_usd": 25000,
  "expected_move_bps": 18.0,
  "taker_fee_bps": 3.5,
  "slippage_budget_bps": 12.5,
  "book_walk_slippage_bps": 7.2,
  "book_walk_coverage_pct": 100.0,
  "within_budget": true,
  "adjusted_size_usd": 25000,
  "worst_acceptable_price": 138.143,
  "session_slippage_bps_before": 4.1,
  "session_slippage_cap_bps": 20.0,
  "defensive_override": false,
  "order_result": "filled",
  "actual_fill_price": 138.155,
  "actual_slippage_bps": 6.8,
  "budget_violation": false
}
```

---

## Quick Decision Tree

```
Taker order needed — enforce slippage budget:
│
├── Is this a DEFENSIVE EXIT (cascade/kill-switch/stop breach)?
│     └── YES → Submit market order. Log estimated slippage. Skip budget checks.
│
└── Normal taker execution path:
      │
      ├── 1. budget = per_order_slippage_budget_bps(expected_move)
      │         └── budget == 0? → ABORT. Use Alo instead.
      │
      ├── 2. can_place, status = tracker.can_place_taker(estimated_slippage)
      │         ├── can_place False? → ABORT. Session cap hit.
      │         └── status "warning"? → Halve size. Continue.
      │
      ├── 3. sim = simulate_taker_fill(l2book, side, size, mid)
      │         ├── sim.slippage > budget? → max_size_within_budget()
      │         │         ├── adjusted > 0? → Use adjusted size.
      │         │         └── adjusted == 0? → ABORT. Use Alo.
      │         └── sim.feasible False? → Reduce to depth × 0.80. Re-simulate.
      │
      └── 4. Submit Ioc at worst_acceptable_price.
               Post-fill: tracker.record_fill(). Log audit event.
```
