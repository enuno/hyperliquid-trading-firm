---
name: rsi-reversal-regime-dependency
description: Use when evaluating any RSI-based reversal or mean-reversion signal on HyperLiquid perpetuals. RSI reversals have strong regime dependency — they work in ranging/mean-reverting conditions and fail catastrophically in trending conditions. This skill documents the full regime filter stack, divergence confirmation requirements, failure modes specific to RSI reversals in perpetuals, and how RSI signals coordinate with EMA cross signals in mixed-regime conditions.
category: agentic
---

# RSI Reversal Regime Dependency

## When This Skill Activates

Apply this skill:

- Before acting on any RSI overbought (> 70) or oversold (< 30)
  reversal signal on HyperLiquid perpetuals
- When RSI divergence (price makes new high/low but RSI does not)
  is observed and a reversal entry is being considered
- When a mean-reversion or fade strategy is being evaluated for
  a trending asset — RSI is the most common source of premature
  fade entries in trending markets
- When coordinating RSI signals with EMA cross signals in the same
  session — the two strategy types have opposing regime requirements
  and must not generate conflicting simultaneous positions
- When classifying a post-trade loss from a reversal strategy to
  determine whether regime filters should be tightened

---

## Core Principle: RSI Is a Regime-Conditional Indicator

RSI does not measure absolute overbought or oversold conditions.
It measures the *speed and magnitude of recent price changes*
relative to the lookback period. In a strong trend, RSI can remain
above 70 for extended periods — this is not an error, it is the
expected output of a fast-moving trending market.

**The fundamental regime split:**

| Regime | RSI Behavior | RSI Signal Validity | Strategy Action |
|---|---|---|---|
| Ranging / mean-reverting | RSI oscillates 30-70, reverts quickly | High — oversold/overbought are actionable | RSI reversals valid |
| Trending (established) | RSI holds 60-85 (bull) or 15-40 (bear) | Low — readings are regime artifacts | RSI reversals invalid; use EMA cross |
| Trending (mature/exhaustion) | RSI diverges from price at extremes | Medium — divergence only, not level | RSI divergence entries valid with confirmation |
| Post-cascade / high fragility | RSI collapses then bounces rapidly | Very low — cascade-driven distortion | No RSI entries during cascade |

> **Rule**: Never fade an RSI extreme in a trending market.
> An RSI reading of 78 in an established uptrend is not
> overbought — it is confirmation the trend is strong.
> The same reading in a ranging market is a valid short setup.

---

## Regime Classification for RSI Signals

```python
def classify_rsi_regime(
    adx_14: float,
    bb_width_pct: float,
    bb_width_20p_median: float,
    hh_hl_count: int,             # from trending-bull-entry-timing
    atr_current: float,
    atr_20p_median: float,
    cascade_score: int,           # from liquidation-cascade-risk
) -> dict:
    """
    Classify the current regime for RSI signal validity.
    Returns regime class and whether RSI reversal signals are
    permitted, divergence-only, or fully blocked.
    """
    # Cascade override: always block during cascade
    if cascade_score >= 5:
        return {
            "regime": "CASCADE",
            "rsi_reversal_permitted": False,
            "divergence_permitted": False,
            "reason": f"Cascade score={cascade_score} >= 5. No RSI entries during cascade.",
        }

    trending     = adx_14 >= 25.0
    strong_trend = adx_14 >= 35.0
    mature_trend = hh_hl_count >= 7
    ranging      = adx_14 < 20.0 and bb_width_pct <= bb_width_20p_median * 1.10
    compressed   = bb_width_pct < bb_width_20p_median * 0.75  # pre-breakout

    if strong_trend and not mature_trend:
        return {
            "regime": "STRONG_TREND",
            "rsi_reversal_permitted": False,
            "divergence_permitted": False,
            "reason": f"ADX={adx_14:.1f} >= 35 (strong trend). RSI extremes are "
                      "regime artifacts, not reversal signals. Use EMA cross instead.",
        }

    if trending and mature_trend:
        return {
            "regime": "MATURE_TREND",
            "rsi_reversal_permitted": False,
            "divergence_permitted": True,   # divergence only
            "reason": f"ADX={adx_14:.1f}, HH/HL_count={hh_hl_count} >= 7. "
                      "Trend mature: reversal entries require RSI divergence confirmation.",
        }

    if trending and not mature_trend:
        return {
            "regime": "EARLY_TREND",
            "rsi_reversal_permitted": False,
            "divergence_permitted": False,
            "reason": f"ADX={adx_14:.1f} trend established but not mature. "
                      "RSI reversals invalid. Wait for ranging regime.",
        }

    if compressed:
        return {
            "regime": "COMPRESSION",
            "rsi_reversal_permitted": False,
            "divergence_permitted": False,
            "reason": "BB width compressed below 75% of median. Pre-breakout compression: "
                      "RSI signals unreliable before directional resolution.",
        }

    if ranging:
        return {
            "regime": "RANGING",
            "rsi_reversal_permitted": True,
            "divergence_permitted": True,
            "reason": f"ADX={adx_14:.1f} < 20, BB width within median. "
                      "Ranging regime: RSI reversals valid with confirmation.",
        }

    # Transitional / ambiguous regime
    return {
        "regime": "TRANSITIONAL",
        "rsi_reversal_permitted": False,
        "divergence_permitted": False,
        "reason": f"ADX={adx_14:.1f} transitional (20-25). Regime ambiguous: "
                  "wait for confirmation before RSI entries.",
    }
```

---

## RSI Signal Types and Requirements

### Type 1: Level-Based Reversal (Ranging Regime Only)

A simple RSI overbought (> 70) or oversold (< 30) entry. Valid
**only** in a confirmed ranging regime (ADX < 20).

```python
def evaluate_rsi_level_signal(
    rsi_14: float,
    direction: str,              # "long" (from oversold) or "short" (from overbought)
    regime: dict,                # from classify_rsi_regime()
    price: float,
    range_high: float,           # resistance level of current range
    range_low: float,            # support level of current range
    funding_1h_pct: float,       # from high-funding-carry-avoidance
) -> dict:
    if not regime["rsi_reversal_permitted"]:
        return {
            "signal_valid": False,
            "reason": f"Regime blocks RSI reversal: {regime['reason']}",
        }

    # RSI threshold check
    oversold_ok  = direction == "long"  and rsi_14 <= 30.0
    overbought_ok = direction == "short" and rsi_14 >= 70.0
    rsi_level_ok = oversold_ok or overbought_ok

    # Price at range boundary confirmation
    if direction == "long":
        at_range_boundary = price <= range_low * 1.005   # within 0.5% of support
    else:
        at_range_boundary = price >= range_high * 0.995  # within 0.5% of resistance

    # Funding check for longs (crowded long at range low is fragile)
    funding_ok = not (direction == "long" and funding_1h_pct > 0.020)

    signal_valid = rsi_level_ok and at_range_boundary and funding_ok
    return {
        "signal_valid":      signal_valid,
        "signal_type":       "RSI_LEVEL",
        "rsi_14":            rsi_14,
        "at_range_boundary": at_range_boundary,
        "funding_ok":        funding_ok,
        "reason": (
            "RSI level signal confirmed." if signal_valid else
            "; ".join(filter(None, [
                f"RSI={rsi_14:.1f} not at threshold" if not rsi_level_ok else None,
                "price not at range boundary"         if not at_range_boundary else None,
                f"funding={funding_1h_pct:.3f}% crowded long" if not funding_ok else None,
            ]))
        ),
    }
```

### Type 2: RSI Divergence (Mature Trend or Ranging)

Bullish divergence: price makes a lower low but RSI makes a higher
low. Bearish divergence: price makes a higher high but RSI makes a
lower high. More reliable than level-based entries; valid in mature
trends as a potential exhaustion signal.

```python
def evaluate_rsi_divergence(
    price_swing_1: float,        # older swing high/low
    price_swing_2: float,        # newer swing high/low
    rsi_swing_1: float,          # RSI at older swing
    rsi_swing_2: float,          # RSI at newer swing
    divergence_type: str,        # "bullish" or "bearish"
    regime: dict,
    candles_between_swings: int, # time between swings (validity window)
    volume_at_swing_2: float,
    volume_20p_avg: float,
) -> dict:
    if not regime["divergence_permitted"]:
        return {
            "divergence_valid": False,
            "reason": f"Regime does not permit divergence entries: {regime['reason']}",
        }

    # Validate divergence structure
    if divergence_type == "bullish":
        price_diverges = price_swing_2 < price_swing_1   # lower low in price
        rsi_diverges   = rsi_swing_2   > rsi_swing_1     # higher low in RSI
    else:
        price_diverges = price_swing_2 > price_swing_1   # higher high in price
        rsi_diverges   = rsi_swing_2   < rsi_swing_1     # lower high in RSI

    structure_ok = price_diverges and rsi_diverges

    # Time validity: swings too close = noise; too far = stale divergence
    time_ok = 5 <= candles_between_swings <= 50

    # Volume confirmation: second swing should have lower volume
    # (exhaustion) for divergence to be meaningful
    volume_declining = volume_at_swing_2 < volume_20p_avg * 0.85

    divergence_valid = structure_ok and time_ok and volume_declining
    return {
        "divergence_valid":    divergence_valid,
        "signal_type":         "RSI_DIVERGENCE",
        "divergence_type":     divergence_type,
        "price_diverges":      price_diverges,
        "rsi_diverges":        rsi_diverges,
        "time_ok":             time_ok,
        "volume_declining":    volume_declining,
        "candles_between":     candles_between_swings,
        "reason": (
            f"{divergence_type.capitalize()} divergence confirmed." if divergence_valid else
            "; ".join(filter(None, [
                "No divergence structure"          if not structure_ok else None,
                f"{candles_between_swings} candles between swings (req 5-50)" if not time_ok else None,
                "Volume not declining at swing 2"  if not volume_declining else None,
            ]))
        ),
    }
```

---

## RSI Failure Modes Specific to Perpetuals

### RFM-1: Trend Fade Loss

**Description**: RSI overbought/oversold signal taken in a trending
market. The trend continues, RSI remains elevated/depressed for
extended periods, and the position is stopped out multiple times
as the trader repeatedly fades the trend.

**Identification**: ADX ≥ 25 at entry. Loss came from repeated
stop-outs on the same direction (e.g., three short entries on
high RSI in an uptrend).

**Prevention**: `classify_rsi_regime()` returns STRONG_TREND or
EARLY_TREND → block all RSI reversal entries.

---

### RFM-2: Divergence in Continuation

**Description**: Bearish/bullish RSI divergence fires in a strong
trend as a "normal" consolidation pause rather than a genuine
exhaustion. Price pauses, RSI pulls back slightly (creating
divergence structure), then the trend resumes with a large move
against the divergence trade.

**Identification**: Divergence was valid structurally but the ADX
remained above 30 throughout, or HH/HL count was below 6
(trend not yet mature). The divergence was a mid-trend pause,
not an exhaustion signal.

**Prevention**: Only permit divergence entries when
`hh_hl_count >= 7` AND `adx_14 < 40` (strong but not
acceleration phase). ADX > 40 indicates active acceleration —
no divergence is reliable at acceleration phase.

```python
MAX_ADX_FOR_DIVERGENCE = 40.0   # above this, trend is accelerating; divergence unreliable
MIN_HH_HL_FOR_DIVERGENCE = 7    # below this, trend not mature enough for exhaustion signal
```

---

### RFM-3: Cascade Reversal Trap

**Description**: A liquidation cascade drives RSI to extreme oversold
(< 20) levels rapidly. The extreme RSI reading looks like a textbook
reversal setup. An entry is taken, but price continues down as the
cascade proceeds through further liquidation levels.

**Identification**: RSI dropped from > 50 to < 25 within 3-5 candles
(cascade speed, not organic selling). OI dropped simultaneously
(liquidations, not shorts being established). Cascade score ≥ 5
at or before entry.

**Prevention**: `cascade_score >= 5` → block all RSI entries in
`classify_rsi_regime()`. Wait for cascade score to fall below 3
and OI to stabilise before re-evaluating RSI signals.

---

### RFM-4: Funding Bleed on Range Longs

**Description**: RSI oversold range long taken with elevated funding.
The trade is directionally correct (price does bounce from range low)
but the carry cost on the long side erodes the net profit, converting
a nominal win into a breakeven or small loss. Repeated applications
cumulatively destroy edge even when price prediction is accurate.

**Identification**: Post-trade review shows positive price move but
negative or zero net PnL. Funding rate was > 0.020% per hour at
entry and sustained throughout.

**Prevention**: `funding_ok` check in `evaluate_rsi_level_signal()`
blocks long entries when `funding_1h_pct > 0.020%`. RSI range longs
in elevated funding are not valid setups regardless of price action.

---

## Coordination with EMA Cross Signals

RSI reversals and EMA cross signals have **opposing regime requirements**.
Conflicts must be resolved before any position is sized:

```python
def coordinate_rsi_ema_signals(
    rsi_signal: dict,    # from evaluate_rsi_level_signal() or evaluate_rsi_divergence()
    ema_signal: dict,    # from ema-cross-failure-modes pre-entry filter
    regime: dict,        # from classify_rsi_regime()
) -> dict:
    """
    Resolve conflicts between RSI reversal and EMA cross signals.
    Returns the permitted signal type (if any) and the resolution.
    """
    rsi_valid = rsi_signal.get("signal_valid") or rsi_signal.get("divergence_valid", False)
    ema_valid = ema_signal.get("entry_permitted", False)

    # Both valid simultaneously: regime conflict
    if rsi_valid and ema_valid:
        # Prefer EMA cross in transitional regimes (trend taking over)
        # Prefer RSI in confirmed ranging (ADX < 20)
        if regime["regime"] == "RANGING":
            return {
                "permitted_signal": "RSI",
                "resolution": "Confirmed ranging: RSI reversal preferred over EMA cross.",
            }
        else:
            return {
                "permitted_signal": "EMA",
                "resolution": "Non-ranging regime: EMA cross preferred; RSI signal suppressed.",
            }

    if rsi_valid and not ema_valid:
        return {"permitted_signal": "RSI", "resolution": "Only RSI signal valid."}

    if ema_valid and not rsi_valid:
        return {"permitted_signal": "EMA", "resolution": "Only EMA signal valid."}

    return {"permitted_signal": None, "resolution": "No valid signal from either system."}
```

**Conflict resolution rule**: In a ranging market, RSI wins. In any
non-ranging market (ADX ≥ 20), EMA wins. Never hold simultaneous
RSI reversal and EMA trend positions on the same asset.

---

## RSI Period and Threshold Calibration

Default RSI-14 with 70/30 thresholds is a starting point, not a
universal truth. Calibrate to the asset and timeframe:

| Asset Volatility | Timeframe | Recommended RSI Period | OB/OS Thresholds | Rationale |
|---|---|---|---|---|
| High (BTC, ETH) | 15m | RSI-9 | 75 / 25 | Faster signals needed; tight thresholds reduce false signals on volatile candles |
| High (BTC, ETH) | 1H | RSI-14 | 70 / 30 | Standard; well-validated |
| High (BTC, ETH) | 4H | RSI-21 | 68 / 32 | Slower timeframe: wider thresholds reduce whipsaw |
| High-beta alts | 1H | RSI-14 | 75 / 25 | High-beta assets reach extreme RSI more easily; raise thresholds |
| High-beta alts | 4H | RSI-21 | 72 / 28 | Same rationale; slower period |

---

## Position Sizing Override for RSI Reversals

RSI reversal trades in ranging markets carry a specific sizing
constraint distinct from Kelly-optimal sizing:

```python
RSI_REVERSAL_KELLY_MULTIPLIER_CAP = 0.25   # never exceed quarter Kelly
# Rationale: RSI reversals have lower average RR ratio (typically 1.5:1)
# than trend-following entries (typically 2:1 or better).
# Lower RR means Kelly optimal fraction is lower; quarter Kelly cap
# prevents oversizing on trades with structurally lower edge.

RSI_REVERSAL_MAX_CONCURRENT = 2   # max simultaneous RSI reversal positions
# Rationale: RSI reversal trades on different assets in the same
# ranging regime are often correlated (broad market ranging). Two
# simultaneous RSI reversal positions is the practical maximum before
# correlated stop-out risk becomes unacceptable.
```

---

## Worked Example — Divergence Entry in Mature Trend

```
Asset: BTC-PERP, 4H timeframe
Signal: Bearish RSI divergence (price new high, RSI lower high)
Timestamp: 2026-04-07T12:00Z

Regime classification inputs:
  ADX_14:         32.1    (trending but not strong_trend > 35)
  BB_width:       2.3%    (median 1.9%, ratio 1.21 — expanded)
  HH_HL_count:    8       (mature trend >= 7: MATURE_TREND)
  Cascade score:  1       (normal)

Regime: MATURE_TREND
  rsi_reversal_permitted: False
  divergence_permitted:   True

Divergence evaluation:
  price_swing_1:  $87,200  (previous high)
  price_swing_2:  $88,500  (new price high — higher high)
  rsi_swing_1:    74.2     (RSI at previous high)
  rsi_swing_2:    68.8     (RSI at new price high — lower RSI high)
  divergence_type: bearish
  candles_between: 18      (within 5-50 range)
  volume_swing_2:  $1.2B   (20p avg $1.6B — declining: 0.75x)

  price_diverges:    True  ($88,500 > $87,200: higher high)
  rsi_diverges:      True  (68.8 < 74.2: lower RSI high)
  time_ok:           True  (18 candles)
  volume_declining:  True  ($1.2B < $1.6B * 0.85 = $1.36B)

Divergence result: VALID

ADX check: 32.1 < MAX_ADX_FOR_DIVERGENCE=40 ✔
HH/HL check: 8 >= MIN_HH_HL=7 ✔

Additional checks:
  Cascade score:  1   (< 5) ✔
  Funding 1h:     -0.005% (slightly negative — no carry concern for short) ✔

Decision: DIVERGENCE ENTRY PERMITTED (BTC short, 4H)
Sizing: Kelly quarter (0.25 multiplier cap for RSI/divergence entries)
SL: Above swing_2 high + 0.5× ATR
TP: Previous swing high minus ATR (1.5:1 RR minimum)
```

---

## Audit JSONL Schema

```json
{
  "event": "rsi_signal_evaluation",
  "timestamp_utc": "2026-04-07T12:00:00Z",
  "asset": "BTC",
  "timeframe": "4H",
  "signal_type": "RSI_DIVERGENCE",
  "direction": "short",
  "signal_valid": true,
  "regime": "MATURE_TREND",
  "rsi_reversal_permitted": false,
  "divergence_permitted": true,
  "adx_14": 32.1,
  "hh_hl_count": 8,
  "cascade_score": 1,
  "rsi_swing_1": 74.2,
  "rsi_swing_2": 68.8,
  "price_swing_1": 87200,
  "price_swing_2": 88500,
  "candles_between_swings": 18,
  "volume_declining": true,
  "funding_1h_pct": -0.005,
  "kelly_multiplier_cap": 0.25,
  "reason": "Bearish divergence confirmed in mature trend. All checks passed."
}
```

---

## Integration with Other Skills

- **`ema-cross-failure-modes`** (strategy/): `coordinate_rsi_ema_signals()`
  resolves conflicts when both strategy systems produce signals
  simultaneously. RSI wins in confirmed ranging (ADX < 20);
  EMA wins in all other regimes. The two skills share ADX and
  RSI inputs — compute once and pass to both.
- **`trending-bull-entry-timing`** (regime-detection/): Provides
  `hh_hl_count` used in `classify_rsi_regime()` (mature trend
  gate) and `evaluate_rsi_divergence()` (minimum leg count for
  valid divergence).
- **`liquidation-cascade-risk`** (regime-detection/): `cascade_score`
  is a hard block in `classify_rsi_regime()`. Any cascade score
  >= 5 prevents all RSI entries regardless of other regime
  conditions.
- **`high-funding-carry-avoidance`** (regime-detection/): `funding_1h_pct`
  used in `evaluate_rsi_level_signal()` to block crowded long
  range entries. Also feeds RFM-4 prevention.
- **`kelly-position-sizing-perps`** (risk/): RSI reversal entries
  are capped at `RSI_REVERSAL_KELLY_MULTIPLIER_CAP = 0.25`
  regardless of the Kelly formula output. Pass this as the
  `kelly_multiplier` ceiling when sizing RSI reversal trades.
- **`max-concurrent-positions`** (risk/): RSI reversal trades
  are subject to `RSI_REVERSAL_MAX_CONCURRENT = 2`. Track
  active RSI reversal positions separately from trend positions.

---

## Quick Decision Tree

```
RSI signal fires (overbought, oversold, or divergence observed):
│
├── 1. Classify regime (run in parallel with regime inputs):
│     trending-bull-entry-timing  → hh_hl_count
│     liquidation-cascade-risk    → cascade_score
│     regime = classify_rsi_regime(adx, bb_width, hh_hl_count,
│                                    atr, cascade_score)
│
├── 2. Route by signal type:
│   ├── Level signal (RSI < 30 or > 70):
│   │     regime.rsi_reversal_permitted? → No → SKIP signal
│   │     evaluate_rsi_level_signal()
│   │     signal_valid? → No → SKIP signal
│   └── Divergence signal:
│         regime.divergence_permitted? → No → SKIP signal
│         adx < 40 AND hh_hl_count >= 7? → No → SKIP signal
│         evaluate_rsi_divergence()
│         divergence_valid? → No → SKIP signal
│
├── 3. Coordinate with EMA signals:
│     Any active EMA cross signal on same asset?
│     coordinate_rsi_ema_signals() → resolve conflict
│
├── 4. Signal valid and no conflict:
│     Kelly sizing with multiplier capped at 0.25
│     → max-concurrent-positions (RSI reversal count ≤ 2)
│     → slippage-budget-enforcement → order submission
│
└── 5. On position close (if loss):
      Classify failure mode: RFM-1, RFM-2, RFM-3, or RFM-4
      Log to audit. Update rolling failure frequency.
```
