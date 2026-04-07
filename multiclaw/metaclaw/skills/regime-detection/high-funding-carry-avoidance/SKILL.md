---
name: high-funding-carry-avoidance
description: Use when perpetual funding rates are elevated to avoid paying carry on directional longs, size entries appropriately, or flip to funding-harvesting posture.
category: agentic
---

# High Funding Rate — Carry Avoidance

## When This Skill Activates

Apply this skill whenever **any** of the following conditions are observed on
HyperLiquid perpetual markets:

- 1h funding rate ≥ **0.05%** (≥ 0.36% per day, ≥ ~131% annualised)
- 8h predicted funding ≥ **0.10%** on the target asset
- Funding has been positive and above 0.03%/h for **≥ 3 consecutive intervals**
- Open interest is rising while price is consolidating (carry-funded leverage buildup)
- Basis (perp − spot) spread > **0.3%** on any liquid asset

---

## Core Principle

Funding carry is a **silent tax on directional longs** (and a rebate on shorts).
In high-funding regimes, a position that is right on direction can still lose
money or underperform a simple spot hold due to carry bleed. Every entry
decision must be adjusted for the current funding regime before sizing.

> **Rule**: Never enter or hold a leveraged long in a high-funding regime
> without explicitly accounting for carry cost in your expected-value calculation.

---

## Step-by-Step Carry Assessment

### 1. Fetch Current Funding Data

Before entering any perpetual position, retrieve:

```
GET /info  →  fundingHistory(coin, startTime, endTime)
GET /info  →  meta + assetCtxs  →  funding field (current predicted)
```

Compute:
- **Current 1h rate**: from `assetCtxs[i].funding`
- **Daily carry cost (long)**: `funding_1h × 24` (approximate; funding compounds)
- **8h carry cost**: `funding_1h × 8`
- **Break-even move required**: `carry_per_8h / (1 / leverage)` — the price must move
  this much in your favour just to cover funding over the next 8h interval

### 2. Classify Funding Regime

| Funding (1h) | Regime | Long Posture |
|---|---|---|
| < 0.01% | Neutral | Normal sizing, no carry adjustment |
| 0.01%–0.03% | Mildly elevated | Reduce size 10–20%; prefer shorter hold |
| 0.03%–0.05% | Elevated | Reduce size 25–40%; tighten TP targets |
| 0.05%–0.10% | High | Avoid new longs; consider short/flat |
| > 0.10% | Extreme | No new longs; actively harvest funding if short |

### 3. Carry-Adjusted Position Sizing

Apply a carry discount to the base Kelly/risk-budget sizing:

```
carry_discount = max(0.0, 1.0 - (funding_1h_bps / 5.0))
adjusted_size  = base_size × carry_discount
```

Where `funding_1h_bps` = funding rate in basis points (e.g. 0.05% → 5 bps).

At 5 bps/h: discount = 0%, position = 0 (do not enter long).
At 3 bps/h: discount = 40%, position = 60% of base size.
At 1 bps/h: discount = 80%, position = 20% reduction.

### 4. Adjust Take-Profit Targets

In elevated regimes, compress TP targets to account for carry bleed:

```
hold_hours_expected = estimated_time_to_target_hours
total_carry_cost    = funding_1h × hold_hours_expected

# Shift TP inward by carry cost:
adjusted_tp = raw_tp - (entry_price × total_carry_cost)
```

If `adjusted_tp < breakeven`, **abort the trade** — carry will consume the
edge before price reaches the target.

---

## Funding Harvesting Mode (Short Side)

When funding is extreme (> 0.10%/h sustained), consider a **neutral funding
harvest** rather than a directional trade:

1. **Short the perpetual** at current market price (size: 0.5–1.0× normal)
2. **Long equivalent notional in spot** (or USDC-settled vault) to eliminate
   directional exposure
3. **Net position**: delta-neutral, earns funding rebate every 1h
4. **Unwind when**: funding drops below 0.03%/h OR basis compresses to < 0.1%

> ⚠ **Liquidation risk**: Ensure the short leg has adequate margin even if
> price spikes 15–20% before funding normalises. Use ≤ 2× leverage on short leg.

---

## Failure Modes to Avoid

- **Ignoring funding on short holds**: Even 4h hold at 0.05%/h = 0.2% drag;
  at 5× leverage this is 1% of capital — larger than typical TP on a scalp.
- **Using predicted funding as settled**: Predicted funding can change every
  minute; confirmed settlement occurs at 0h, 8h, 16h UTC on HyperLiquid.
  Never assume predicted = settled for P&L accounting.
- **Entering a long to "fade" high funding**: Fading high funding by longing
  is a high-risk contrarian play. High funding can persist for days in
  strong bull regimes. Only fade funding if **price is already showing reversal
  structure** (lower-high on 1h, OI declining, spot/perp basis narrowing).
- **Forgetting cross-asset contagion**: If BTC perp funding is extreme, ETH and
  alt perp funding typically follows within 1–2 intervals. Apply regime check
  **per asset**, not just to the primary trade target.
- **Funding harvest without delta hedge**: Running a short perpetual without a
  corresponding spot long creates directional risk disguised as a carry trade.

---

## Integration with Risk Controls

- **Kill-switch trigger**: If funding spikes above 0.15%/h AND position is
  long AND position is in drawdown > 1.5%, close immediately — carry will
  compound losses faster than recovery is likely.
- **Max carry budget per session**: Total carry cost across all open longs
  must not exceed **0.5%** of total portfolio NAV per 8h interval.
- **Reporting**: Log `funding_regime`, `carry_cost_per_8h`, and
  `carry_adjusted_size` for every entry in the audit JSONL:
  ```json
  {
    "event": "entry",
    "asset": "BTC",
    "funding_1h": 0.042,
    "carry_regime": "elevated",
    "carry_cost_8h_pct": 0.336,
    "base_size_usd": 10000,
    "carry_discount": 0.664,
    "adjusted_size_usd": 6640
  }
  ```

---

## Quick Decision Tree

```
Is 1h funding > 0.05%?
├── YES → Is this a NEW long entry?
│         ├── YES → ABORT entry. Consider short or flat.
│         └── NO  → Existing long? Apply kill-switch check. If drawdown > 1.5%, close.
│
└── NO  → Is 1h funding between 0.03% and 0.05%?
          ├── YES → Apply carry discount to size. Compress TP.
          └── NO  → Funding neutral. Proceed with standard sizing.
```

---

## HyperLiquid-Specific Notes

- Funding settles every **1 hour** on HyperLiquid (not 8h like many CEXes).
  This makes carry bleed **8× faster** than on Binance/Bybit at equivalent
  quoted rates. Adjust all carry calculations accordingly.
- `assetCtxs[i].funding` returns the **predicted** rate for the current interval;
  use `fundingHistory` for confirmed settled rates.
- Cross-margin accounts: funding payments reduce margin balance directly.
  Monitor `marginSummary.totalRawUsd` in the WebSocket user state feed to
  detect margin erosion from carry before it triggers a liquidation.
- HyperLiquid vault positions are **not** subject to perpetual funding —
  vault LP returns come from trading fees, not carry. Do not apply this
  skill to vault allocation decisions.
