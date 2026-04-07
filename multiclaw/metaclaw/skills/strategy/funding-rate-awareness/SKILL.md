---
name: funding-rate-awareness
description: Use before entering or holding any perpetual futures position on HyperLiquid. Funding rate is a perpetuals-exclusive carry cost that has no analogue in spot or traditional futures. Elevated funding directly deducts from trade edge on every 8-hour settlement. This skill covers funding mechanics, carry cost calculation, regime classification, long/short asymmetry, funding-momentum as an independent alpha signal, crowding detection, and integration with position sizing and risk controls.
category: agentic
---

# Funding Rate Awareness

## When This Skill Activates

Apply this skill:

- Before entering any perpetual futures long or short position
  (funding rate determines the carry cost of the trade)
- When hold time is expected to exceed 2 hours (intra-candle scalps
  below 2 hours are funding-neutral in practice; anything held
  through a settlement window is not)
- When evaluating an existing position for continuation vs. exit:
  if funding has shifted since entry, re-evaluate carry viability
- When using funding rate as an independent alpha signal (extreme
  funding → crowded trade → mean-reversion opportunity)
- When classifying a post-trade loss to determine whether carry
  cost was the primary performance drag (FM-5 from ema-cross-failure-modes)

---

## Funding Rate Mechanics on HyperLiquid

HyperLiquid perpetuals use a **continuous funding model** that settles
hourly (not the standard 8-hour CEX cycle). Key mechanics:

```
Funding interval:    1 hour (HyperLiquid native)
Settlement:          Continuous accrual, charged/paid hourly
Premium:             Funding rate reflects the premium of perp price
                     over mark price (index-derived)
Long pays short:     When funding > 0 (perp premium: bullish positioning)
Short pays long:     When funding < 0 (perp discount: bearish positioning)
Rate normalisation:  HyperLiquid 1h rate × 8 = equivalent 8h CEX rate
```

> **Critical**: HyperLiquid quotes funding as a **1-hour rate**.
> All thresholds in this skill use the **1-hour rate** natively.
> When comparing to CEX data or academic literature (which uses
> 8-hour rates), divide the 8h rate by 8 to get the 1h equivalent.

```python
def normalise_funding_rate(rate: float, source_interval_hours: float) -> float:
    """Normalise any funding rate to HyperLiquid 1-hour equivalent."""
    return rate / source_interval_hours   # e.g., 8h rate / 8 = 1h rate
```

---

## Funding Rate Regime Classification

```python
def classify_funding_regime(
    funding_1h_pct: float,     # current 1-hour funding rate as percentage
    funding_24h_avg_pct: float, # 24-hour rolling average 1h funding
    oi_current: float,          # current open interest (USD)
    oi_7d_avg: float,           # 7-day average open interest (USD)
) -> dict:
    """
    Classify current funding regime.
    Returns regime class, direction pressure, and carry cost assessment.
    """
    abs_rate   = abs(funding_1h_pct)
    oi_ratio   = oi_current / oi_7d_avg if oi_7d_avg > 0 else 1.0
    crowded_oi = oi_ratio >= 1.40   # OI 40% above 7d avg = crowded

    # Annualised rate (informational)
    annualised_pct = funding_1h_pct * 24 * 365

    if abs_rate <= 0.005:
        regime = "NEUTRAL"
        carry_concern = "none"
        alpha_signal  = "none"
    elif abs_rate <= 0.015:
        regime = "MILD"
        carry_concern = "low"
        alpha_signal  = "none"
    elif abs_rate <= 0.030:
        regime = "ELEVATED"
        carry_concern = "moderate"
        alpha_signal  = "watch"
    elif abs_rate <= 0.060:
        regime = "HIGH"
        carry_concern = "high"
        alpha_signal  = "contrarian_watch" if crowded_oi else "watch"
    else:
        regime = "EXTREME"
        carry_concern = "critical"
        alpha_signal  = "contrarian_signal"

    # Persistence check: elevated for > 12h → structural, not transient
    persistent = (abs(funding_24h_avg_pct) >= 0.020)

    direction_pressure = (
        "LONG_CROWDED"  if funding_1h_pct > 0.020 else
        "SHORT_CROWDED" if funding_1h_pct < -0.020 else
        "BALANCED"
    )

    return {
        "regime":             regime,
        "funding_1h_pct":     funding_1h_pct,
        "funding_24h_avg":    funding_24h_avg_pct,
        "annualised_pct":     round(annualised_pct, 1),
        "carry_concern":      carry_concern,
        "alpha_signal":       alpha_signal,
        "direction_pressure": direction_pressure,
        "crowded_oi":         crowded_oi,
        "oi_ratio":           round(oi_ratio, 2),
        "persistent":         persistent,
    }
```

### Regime Reference Table

| Regime | 1h Rate | 8h Equiv | Annualised | Carry Concern | Action |
|---|---|---|---|---|---|
| NEUTRAL | ≤ 0.005% | ≤ 0.040% | ≤ 4.4% | None | No constraint |
| MILD | 0.005–0.015% | 0.040–0.120% | 4.4–13.1% | Low | Monitor |
| ELEVATED | 0.015–0.030% | 0.120–0.240% | 13.1–26.3% | Moderate | Reduce hold time |
| HIGH | 0.030–0.060% | 0.240–0.480% | 26.3–52.6% | High | Block longs; short carry positive |
| EXTREME | > 0.060% | > 0.480% | > 52.6% | Critical | Block all longs; evaluate contrarian short |

---

## Carry Cost Calculation

Quantify the exact funding cost before committing to a position:

```python
def calculate_carry_cost(
    position_size_usd: float,
    funding_1h_pct: float,
    direction: str,              # "long" or "short"
    expected_hold_hours: float,
    leverage: float = 1.0,
) -> dict:
    """
    Calculate total carry cost for a position over its expected hold.
    For longs: carry cost is positive (paid) when funding > 0.
    For shorts: carry income is positive (received) when funding > 0.
    """
    notional = position_size_usd * leverage

    # Number of hourly settlements over hold period
    settlements = expected_hold_hours   # 1 settlement per hour

    # Rate from long perspective: positive = long pays
    long_rate_per_hour = funding_1h_pct / 100   # convert pct to decimal

    if direction == "long":
        carry_per_hour_usd = notional * long_rate_per_hour
    else:
        carry_per_hour_usd = -notional * long_rate_per_hour   # short receives when funding > 0

    total_carry_usd  = carry_per_hour_usd * settlements
    carry_pct_of_pos = (total_carry_usd / position_size_usd) * 100

    return {
        "direction":          direction,
        "position_usd":       position_size_usd,
        "notional_usd":       notional,
        "funding_1h_pct":     funding_1h_pct,
        "expected_hold_h":    expected_hold_hours,
        "carry_per_hour_usd": round(carry_per_hour_usd, 4),
        "total_carry_usd":    round(total_carry_usd, 4),
        "carry_pct_of_pos":   round(carry_pct_of_pos, 4),
        "carry_is_cost":      carry_per_hour_usd > 0,
        "carry_is_income":    carry_per_hour_usd < 0,
    }
```

### Carry Break-Even Calculation

Before entry, compute the minimum price move required just to recover
carry cost — this is the **carry-adjusted break-even**:

```python
def carry_adjusted_breakeven(
    entry_price: float,
    funding_1h_pct: float,
    direction: str,
    expected_hold_hours: float,
    leverage: float = 1.0,
) -> dict:
    """
    Minimum price move to recover carry cost at expected hold duration.
    If breakeven move > realistic ATR-based target, the trade lacks edge.
    """
    carry_decimal = (funding_1h_pct / 100) * expected_hold_hours

    if direction == "long":
        breakeven_move_pct = carry_decimal * leverage
        breakeven_price    = entry_price * (1 + breakeven_move_pct)
    else:
        breakeven_move_pct = -carry_decimal * leverage
        breakeven_price    = entry_price * (1 + breakeven_move_pct)

    return {
        "entry_price":          entry_price,
        "carry_breakeven_price": round(breakeven_price, 4),
        "breakeven_move_pct":   round(breakeven_move_pct * 100, 4),
        "hold_hours":           expected_hold_hours,
    }
```

---

## Long/Short Asymmetry in Funding

Funding creates a structural asymmetry between long and short entries
that must be evaluated independently for each direction:

```python
LONG_FUNDING_BLOCK_THRESHOLD  = 0.030   # 1h rate: block new longs above this
LONG_FUNDING_CAUTION_THRESHOLD = 0.015  # 1h rate: reduce size above this

SHORT_FUNDING_INCOME_FLOOR    = 0.020   # 1h rate: shorts receive carry income above this
SHORT_FUNDING_INCOME_ENHANCED = 0.050   # 1h rate: meaningful carry income; enhances short edge

def evaluate_funding_for_direction(
    funding_1h_pct: float,
    direction: str,
    expected_hold_hours: float,
) -> dict:
    """
    Evaluate whether funding rate is compatible with the proposed direction.
    Returns permitted flag, sizing adjustment, and carry income/cost assessment.
    """
    if direction == "long":
        if funding_1h_pct >= LONG_FUNDING_BLOCK_THRESHOLD:
            return {
                "permitted":        False,
                "sizing_adj":       0.0,
                "carry_type":       "COST",
                "reason": f"Funding {funding_1h_pct:.3f}% >= block threshold "
                          f"{LONG_FUNDING_BLOCK_THRESHOLD:.3f}%. Long carry cost "
                          f"too high. Expected carry over {expected_hold_hours}h: "
                          f"{funding_1h_pct * expected_hold_hours:.3f}% of notional.",
            }
        elif funding_1h_pct >= LONG_FUNDING_CAUTION_THRESHOLD:
            # Reduce size proportionally: at 2× the caution threshold, 50% size
            reduction_factor = 1.0 - (
                (funding_1h_pct - LONG_FUNDING_CAUTION_THRESHOLD) /
                (LONG_FUNDING_BLOCK_THRESHOLD - LONG_FUNDING_CAUTION_THRESHOLD)
            ) * 0.5
            return {
                "permitted":        True,
                "sizing_adj":       round(reduction_factor, 2),
                "carry_type":       "COST_CAUTION",
                "reason": f"Funding {funding_1h_pct:.3f}% in caution zone. "
                          f"Reduce long size to {reduction_factor*100:.0f}% of normal.",
            }
        else:
            return {
                "permitted":  True,
                "sizing_adj": 1.0,
                "carry_type": "NEUTRAL_OR_INCOME",
                "reason":     f"Funding {funding_1h_pct:.3f}% below caution threshold. "
                              "Long carry acceptable.",
            }

    else:  # short
        if funding_1h_pct >= SHORT_FUNDING_INCOME_ENHANCED:
            return {
                "permitted":        True,
                "sizing_adj":       1.10,  # allow slight size increase: carry enhances edge
                "carry_type":       "INCOME_ENHANCED",
                "reason": f"Funding {funding_1h_pct:.3f}% >= {SHORT_FUNDING_INCOME_ENHANCED:.3f}%. "
                          "Short receives enhanced carry income. Edge structurally improved.",
            }
        elif funding_1h_pct >= SHORT_FUNDING_INCOME_FLOOR:
            return {
                "permitted":        True,
                "sizing_adj":       1.0,
                "carry_type":       "INCOME",
                "reason": f"Funding {funding_1h_pct:.3f}% above income floor. "
                          "Short receives positive carry income.",
            }
        elif funding_1h_pct < -0.030:
            # Negative funding: shorts pay, longs receive — unusual
            return {
                "permitted":        False,
                "sizing_adj":       0.0,
                "carry_type":       "REVERSE_COST",
                "reason": f"Funding {funding_1h_pct:.3f}% strongly negative. "
                          "Short pays carry (long-favoured funding). Block short.",
            }
        else:
            return {
                "permitted":  True,
                "sizing_adj": 1.0,
                "carry_type": "NEUTRAL",
                "reason":     "Funding neutral for short direction.",
            }
```

---

## Funding as an Alpha Signal (Contrarian)

Extreme funding rates indicate extreme positioning crowding. When the
crowd is heavily one-sided, the trade against the crowd — the
**funding mean-reversion short** (when funding is extreme positive)
or **funding mean-reversion long** (when funding is extreme negative)
— has structural carry income on top of the contrarian price thesis.

```python
CONTRARIAN_FUNDING_THRESHOLD    = 0.050   # 1h rate: extreme crowding
CONTRARIAN_OI_ELEVATION_FACTOR  = 1.40    # OI must be 40% above 7d avg
CONTRARIAN_PERSISTENCE_HOURS    = 12      # elevated funding must persist > 12h

def evaluate_funding_contrarian_signal(
    funding_1h_pct: float,
    funding_24h_avg_pct: float,
    oi_current: float,
    oi_7d_avg: float,
    hours_above_threshold: float,   # continuous hours funding has been elevated
    cascade_score: int,             # from liquidation-cascade-risk
    regime_adx: float,              # from classify_rsi_regime / ema-cross
) -> dict:
    """
    Evaluate whether extreme funding constitutes an actionable contrarian signal.
    Requires: extreme rate + elevated OI + persistence + no active cascade.
    """
    rate_extreme  = abs(funding_1h_pct) >= CONTRARIAN_FUNDING_THRESHOLD
    oi_elevated   = (oi_current / oi_7d_avg) >= CONTRARIAN_OI_ELEVATION_FACTOR
    persistent    = hours_above_threshold >= CONTRARIAN_PERSISTENCE_HOURS
    no_cascade    = cascade_score < 4
    ranging_regime = regime_adx < 25.0   # contrarian signals weakest in strong trends

    all_conditions = rate_extreme and oi_elevated and persistent and no_cascade

    signal_type = (
        "CONTRARIAN_SHORT" if funding_1h_pct > 0 else
        "CONTRARIAN_LONG"
    ) if all_conditions else None

    return {
        "contrarian_signal":       signal_type is not None,
        "signal_type":             signal_type,
        "rate_extreme":            rate_extreme,
        "oi_elevated":             oi_elevated,
        "persistent":              persistent,
        "no_cascade":              no_cascade,
        "ranging_regime":          ranging_regime,
        "regime_note": (
            "Trending regime: contrarian signal has lower edge vs ranging"
            if not ranging_regime and all_conditions else None
        ),
        "reason": (
            f"Contrarian {signal_type} signal: funding={funding_1h_pct:.3f}%, "
            f"OI ratio={oi_current/oi_7d_avg:.2f}x, "
            f"persistent={hours_above_threshold:.0f}h"
            if signal_type else
            "; ".join(filter(None, [
                f"rate {funding_1h_pct:.3f}% not extreme" if not rate_extreme else None,
                f"OI ratio {oi_current/oi_7d_avg:.2f}x < 1.40"  if not oi_elevated else None,
                f"only {hours_above_threshold:.0f}h elevated (< 12h)" if not persistent else None,
                f"cascade score {cascade_score} >= 4"              if not no_cascade else None,
            ]))
        ),
    }
```

### Why Contrarian Funding Trades Work

1. **Carry income**: The contrarian side receives funding on every
   settlement — shorting extreme positive funding earns 0.050%+/h
   *while waiting* for the mean-reversion
2. **Crowding risk**: Extreme long positioning means the pool of
   new long buyers is exhausted; any catalyst triggers a cascade
   of stops and liquidations (amplified by FM-6 from EMA skill)
3. **Persistence requirement**: A single spike to extreme funding
   may resolve within hours. Only persistent crowding (12h+)
   reflects structural rather than transient positioning

> **Warning**: Contrarian funding signals are not trend-fade signals.
> The contrarian position is sized conservatively (max 0.15 Kelly)
> and held with a tight ATR stop. It is a carry income + crowding
> unwind play, not a price prediction.

---

## Funding Monitor: Real-Time Position Management

For open positions, funding must be monitored continuously:

```python
def monitor_open_position_funding(
    entry_funding_1h_pct: float,   # funding rate at entry
    current_funding_1h_pct: float, # current funding rate
    direction: str,
    hold_hours_elapsed: float,
    total_carry_paid_pct: float,   # cumulative carry paid so far
    unrealised_pnl_pct: float,     # current unrealised PnL as % of position
) -> dict:
    """
    Assess whether an open position should be exited based on
    funding rate changes since entry.
    """
    funding_worsened = (
        direction == "long"  and current_funding_1h_pct > entry_funding_1h_pct + 0.010
        or
        direction == "short" and current_funding_1h_pct < entry_funding_1h_pct - 0.010
    )

    # Carry erosion check: if total carry paid > 50% of unrealised PnL,
    # carry is significantly impairing the trade
    carry_eroding = (
        total_carry_paid_pct > 0 and
        unrealised_pnl_pct > 0 and
        total_carry_paid_pct > unrealised_pnl_pct * 0.50
    )

    # Funding worsened to block level mid-trade
    funding_now_blocked = (
        direction == "long"  and current_funding_1h_pct >= LONG_FUNDING_BLOCK_THRESHOLD
    )

    action = (
        "EXIT_IMMEDIATELY" if funding_now_blocked and unrealised_pnl_pct < 0.005 else
        "CONSIDER_EXIT"    if (funding_worsened or carry_eroding) else
        "HOLD"
    )

    return {
        "action":               action,
        "funding_worsened":     funding_worsened,
        "carry_eroding":        carry_eroding,
        "funding_now_blocked":  funding_now_blocked,
        "total_carry_paid_pct": total_carry_paid_pct,
        "unrealised_pnl_pct":   unrealised_pnl_pct,
        "reason": (
            f"Funding shifted from {entry_funding_1h_pct:.3f}% to "
            f"{current_funding_1h_pct:.3f}% since entry. "
            f"Carry paid {total_carry_paid_pct:.3f}%, "
            f"unrealised PnL {unrealised_pnl_pct:.3f}%."
        ),
    }
```

---

## Pre-Entry Funding Gate (Master Function)

```python
def funding_pre_entry_gate(
    funding_1h_pct: float,
    funding_24h_avg_pct: float,
    oi_current: float,
    oi_7d_avg: float,
    direction: str,
    expected_hold_hours: float,
    entry_price: float,
    position_size_usd: float,
    leverage: float,
    cascade_score: int,
) -> dict:
    """
    Single gate function. Returns entry_permitted, sizing_adjustment,
    carry_cost_usd, and carry_breakeven_price.
    All must be checked before any position entry.
    """
    # Step 1: Regime
    regime = classify_funding_regime(
        funding_1h_pct, funding_24h_avg_pct, oi_current, oi_7d_avg
    )

    # Step 2: Direction evaluation
    direction_eval = evaluate_funding_for_direction(
        funding_1h_pct, direction, expected_hold_hours
    )

    # Step 3: Carry cost
    carry = calculate_carry_cost(
        position_size_usd, funding_1h_pct, direction,
        expected_hold_hours, leverage
    )

    # Step 4: Break-even
    breakeven = carry_adjusted_breakeven(
        entry_price, funding_1h_pct, direction, expected_hold_hours, leverage
    )

    entry_permitted = direction_eval["permitted"]

    return {
        "entry_permitted":      entry_permitted,
        "funding_regime":       regime["regime"],
        "direction_eval":       direction_eval,
        "sizing_adjustment":    direction_eval["sizing_adj"],
        "carry_cost_usd":       carry["total_carry_usd"],
        "carry_pct_of_pos":     carry["carry_pct_of_pos"],
        "breakeven_price":      breakeven["carry_breakeven_price"],
        "breakeven_move_pct":   breakeven["breakeven_move_pct"],
        "direction_pressure":   regime["direction_pressure"],
        "crowded_oi":           regime["crowded_oi"],
        "contrarian_eligible":  regime["alpha_signal"] in ("contrarian_watch", "contrarian_signal"),
        "reason":               direction_eval["reason"],
    }
```

---

## Failure Modes: Funding-Specific Losses

### FFM-1: Carry Accumulation (Hold-Time Blindness)

**Description**: A valid directional trade is held well beyond its
expected hold time as the trader waits for a larger profit target.
Funding accrues continuously, converting a profitable trade into a
breakeven or loss even as the price prediction is eventually
correct.

**Example**: Long BTC-PERP at 0.025% funding, held 24h while
waiting for a 1% move. Carry cost: 0.025% × 24 = 0.60% of notional.
A 0.5% unrealised profit becomes a 0.1% loss net of carry.

**Prevention**: Set `expected_hold_hours` conservatively at entry.
Monitor via `monitor_open_position_funding()` on a timer. Exit
if `carry_eroding = True` before the target is reached.

---

### FFM-2: Funding Spike at Entry

**Description**: Funding rate spikes immediately after entry (common
during a volatile breakout that creates rapid long crowding). The
trade was entered with acceptable funding but the rate moved to the
block threshold within 1-2 hours.

**Prevention**: `monitor_open_position_funding()` must run on every
hourly settlement. If `funding_now_blocked = True` and the trade is
not yet meaningfully profitable, treat as an EXIT_IMMEDIATELY signal.

---

### FFM-3: Negative Funding Trap for Shorts

**Description**: A short position is entered in a market where
funding is negative (shorts pay, longs receive). The directional
trade may be correct, but carry is working against the short side.
Losses from both carry and adverse price movement compound.

**Prevention**: `evaluate_funding_for_direction()` returns `permitted: False`
when `funding_1h_pct < -0.030`. Never short into persistently
negative funding without a very high-conviction, fast-moving thesis
with stop-loss tight enough that carry is negligible.

---

### FFM-4: Contrarian Position Pre-Cascade

**Description**: A contrarian funding short is entered on an
extreme funding signal, but the extreme funding is driven by a
positioning buildup that precedes a cascade rather than a
normal crowding unwind. Price spikes higher before the
cascade occurs, stopping out the contrarian short.

**Prevention**: `cascade_score` gate in `evaluate_funding_contrarian_signal()`:
block contrarian entries when cascade_score ≥ 4. Contrarian
sizing cap of 0.15 Kelly prevents a stop-out from being catastrophic.

---

## Worked Example — Pre-Entry Gate on ETH-PERP Long

```
Asset: ETH-PERP, 1H timeframe
Signal: RSI oversold level reversal (from rsi-reversal-regime-dependency)
Direction: Long
Timestamp: 2026-04-07T14:00Z

Funding inputs:
  funding_1h_pct:      0.026%
  funding_24h_avg:     0.022%
  oi_current:          $2.8B
  oi_7d_avg:           $2.1B
  cascade_score:       2

Regime classification:
  abs_rate=0.026% → ELEVATED
  oi_ratio = 2.8B / 2.1B = 1.33 (below 1.40 crowded threshold)
  persistent = 24h avg 0.022% >= 0.020 → True
  direction_pressure: LONG_CROWDED (0.026% > 0.020%)
  alpha_signal: watch

Direction evaluation (long):
  funding 0.026% >= CAUTION=0.015, < BLOCK=0.030
  reduction_factor = 1.0 - ((0.026-0.015)/(0.030-0.015)) * 0.5
                   = 1.0 - (0.011/0.015) * 0.5
                   = 1.0 - 0.367 = 0.633
  sizing_adj: 0.63 (reduce to 63% of normal size)
  permitted: True (COST_CAUTION)

Carry cost (example $10,000 position, 2× leverage, 6h hold):
  notional:       $20,000
  carry/hour:     $20,000 × 0.026/100 = $5.20/h
  total 6h carry: $31.20 (0.312% of $10,000 position)

Break-even price:
  entry: $3,150
  carry move needed: 0.026% × 6h × 2 leverage = 0.312%
  break-even: $3,150 × 1.00312 = $3,159.83

Decision:
  entry_permitted: True (with reduced size)
  sizing_adjustment: 0.63
  carry_cost: $31.20 over 6h
  breakeven: $3,159.83 (requires 0.31% move just to recover carry)

Coordinator check (with RSI skill):
  RSI reversal signal valid: True (ADX < 20, ranging regime)
  Funding gate: permitted with 0.63 sizing
  Final position: 63% of normal RSI reversal size
  TP must exceed $3,159.83 before valid risk/reward
```

---

## Integration with Other Skills

- **`ema-cross-failure-modes`** (strategy/): FM-5 (funding drain on
  EMA cross longs) is prevented by running `funding_pre_entry_gate()`
  before every EMA long entry. The EMA cross pre-entry filter calls
  the funding gate as one of its six sub-checks. Share
  `funding_1h_pct` and `oi_current` data computed once per cycle.
- **`rsi-reversal-regime-dependency`** (strategy/): RFM-4 (funding
  bleed on range longs) uses `evaluate_funding_for_direction()`.
  `funding_ok` in `evaluate_rsi_level_signal()` maps to
  `permitted = True` from this gate. RSI range longs must not
  be taken when `direction_pressure = LONG_CROWDED`.
- **`high-funding-carry-avoidance`** (regime-detection/): That skill
  provides a binary block signal for extreme carry cases; this
  skill provides the full graduated response (block/caution/size
  reduction/income). Use the regime-detection skill for fast
  filtering; use this skill for precise sizing calculation.
- **`liquidation-cascade-risk`** (regime-detection/): `cascade_score`
  is used in `evaluate_funding_contrarian_signal()` to prevent
  entering contrarian trades ahead of a cascade-driven short squeeze.
  Cascades and extreme funding co-occur frequently — always check
  both simultaneously.
- **`kelly-position-sizing-perps`** (risk/): The `sizing_adjustment`
  from `evaluate_funding_for_direction()` is applied as a
  multiplicative cap on the Kelly fraction. Kelly output ×
  funding_sizing_adj = final position fraction.
- **`drawdown-kill-switch-trigger`** (risk/): Extreme funding
  regimes (EXTREME class, funding > 0.060%) elevate the system's
  overall risk level and should lower the drawdown threshold
  for kill-switch activation during the elevated period.

---

## Audit JSONL Schema

```json
{
  "event": "funding_pre_entry_gate",
  "timestamp_utc": "2026-04-07T14:00:00Z",
  "asset": "ETH",
  "direction": "long",
  "funding_1h_pct": 0.026,
  "funding_24h_avg_pct": 0.022,
  "funding_regime": "ELEVATED",
  "oi_ratio": 1.33,
  "crowded_oi": false,
  "direction_pressure": "LONG_CROWDED",
  "entry_permitted": true,
  "sizing_adjustment": 0.63,
  "carry_cost_usd": 31.20,
  "carry_pct_of_pos": 0.312,
  "breakeven_price": 3159.83,
  "breakeven_move_pct": 0.312,
  "cascade_score": 2,
  "contrarian_eligible": false,
  "reason": "Funding 0.026% in caution zone. Reduce long size to 63% of normal."
}
```

---

## Quick Decision Tree

```
Any perpetual position entry considered:
│
├── 1. Run funding_pre_entry_gate() with current data
│     ├── entry_permitted = False → BLOCK. No entry.
│     └── entry_permitted = True
│           ├── sizing_adjustment < 1.0 → reduce size proportionally
│           └── sizing_adjustment > 1.0 → short carry income (max 1.10)
│
├── 2. Carry cost check:
│     carry_pct_of_pos > 0.50% for expected hold → reconsider hold time
│     breakeven_move_pct > 0.5 × ATR(expected_hold_h) → edge likely insufficient
│
├── 3. Contrarian check (if not entering directional):
│     contrarian_eligible = True → run evaluate_funding_contrarian_signal()
│     All 4 conditions met → contrarian signal valid, size at 0.15 Kelly max
│
├── 4. Position open → hourly monitor:
│     monitor_open_position_funding() on every settlement
│     action = EXIT_IMMEDIATELY → close immediately
│     action = CONSIDER_EXIT → evaluate vs. price target proximity
│
└── 5. On close (if carry was material):
      Log FFM class if carry was primary drag (total_carry_paid > 30% of gross PnL loss)
      Update rolling funding_regime frequency for the asset
```
