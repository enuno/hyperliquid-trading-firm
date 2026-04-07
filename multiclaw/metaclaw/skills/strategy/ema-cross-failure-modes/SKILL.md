---
name: ema-cross-failure-modes
description: Use when evaluating, entering, managing, or reviewing any EMA crossover strategy signal on HyperLiquid perpetuals. Documents the complete taxonomy of EMA cross failure modes, the pre-entry regime filters that suppress false signals, and the post-entry management rules that limit damage when failure occurs despite filtering. Apply before any EMA-based entry and during any post-trade analysis of a losing EMA cross trade.
category: agentic
---

# EMA Cross Failure Modes

## When This Skill Activates

Apply this skill:

- Before acting on any EMA crossover signal — run the full pre-entry
  filter checklist before sizing or submitting an order
- When a prior EMA cross trade is being reviewed post-close —
  classify which failure mode occurred to update strategy parameters
- When backtesting an EMA cross strategy — use the failure mode
  taxonomy to segment results by regime and identify which regimes
  are generating most of the losses
- When calibrating EMA period parameters — understand which failure
  modes are amplified or reduced by faster vs. slower parameter choices
- When evaluating whether a current market condition is suitable for
  any trend-following strategy (not just EMA cross specifically)

---

## What EMA Cross Strategies Are and Are Not

An EMA crossover strategy generates an entry signal when a faster
exponential moving average crosses above (long) or below (short) a
slower EMA. The edge hypothesis is that the crossover captures the
early phase of a sustained directional move, and that the position
can be held until either a profit target or stop-loss is reached.

**The edge exists only in trending, directional regimes.** EMA cross
is a trend-following primitive — it has no edge in ranging, choppy,
or mean-reverting markets. The failure modes below are all expressions
of the same root cause: **the strategy was applied in a regime where
its edge assumption does not hold**.

> **Core rule**: An EMA cross signal is a hypothesis that a trend is
> beginning. The filters below are tests of that hypothesis. If the
> filters do not confirm, the signal is noise — do not act on it.

---

## Failure Mode Taxonomy

### FM-1: Whipsaw in Ranging Market

**Description**: Price oscillates around the EMA levels without
establishing directional momentum. The fast EMA crosses the slow
EMA repeatedly in both directions over short intervals, generating
a sequence of small losses that cumulatively exceed any individual
win.

**Market conditions that cause FM-1**:
- ADX < 20 (no trend strength)
- Bollinger Band width at multi-week low (price compression)
- Price has been range-bound for 10+ candles at the signal timeframe
- Recent ATR is below the 20-period ATR median (volatility contraction)

**Damage profile**: Many small losses (0.5-1.5× SL each), high
trade frequency, negative expectancy across the sequence. Individual
losses appear manageable but the sequence destroys edge.

**Detection filter**:
```python
def filter_fm1_whipsaw(
    adx_14: float,
    bb_width_pct: float,          # current BB width as % of price
    bb_width_20p_median: float,   # 20-period median BB width
    atr_current: float,
    atr_20p_median: float,
) -> dict:
    """
    Returns filter_pass=False if ranging/choppy conditions detected.
    Any single failing condition is sufficient to block the signal.
    """
    adx_ok        = adx_14 >= 20.0
    bb_width_ok   = bb_width_pct >= bb_width_20p_median * 0.85
    atr_ok        = atr_current >= atr_20p_median * 0.80

    filter_pass = adx_ok and bb_width_ok and atr_ok
    return {
        "filter_pass":    filter_pass,
        "failure_mode":   "FM-1" if not filter_pass else None,
        "adx_14":         adx_14,
        "adx_ok":         adx_ok,
        "bb_width_ok":    bb_width_ok,
        "atr_ok":         atr_ok,
        "reason": (
            None if filter_pass else
            f"Ranging market detected: ADX={adx_14:.1f} "
            f"({'ok' if adx_ok else 'FAIL < 20'}), "
            f"BB_width={'ok' if bb_width_ok else 'FAIL compressed'}, "
            f"ATR={'ok' if atr_ok else 'FAIL contracted'}."
        ),
    }
```

---

### FM-2: Late Entry at Trend Exhaustion

**Description**: The EMA crossover fires after the underlying move
has already extended significantly. Price is already far from value
(VWAP, recent swing structure), momentum indicators are in overbought/
oversold territory, and the trade enters near the trend's termination
point rather than its beginning. The position immediately moves into
loss as the trend reverses or consolidates sharply.

**Market conditions that cause FM-2**:
- RSI > 75 (long signal) or RSI < 25 (short signal) at entry
- Price > 2.0× ATR from VWAP
- Higher timeframe (4H or daily) trend shows 8+ consecutive
  higher-highs / lower-lows (trend maturity — see `trending-bull-entry-timing`)
- Funding rate strongly positive on a long signal (crowd already long)

**Damage profile**: One medium loss (1.5-3× SL) as price reverses
immediately after entry. Often the most psychologically damaging
failure mode because the signal looked "obvious" at entry.

**Detection filter**:
```python
def filter_fm2_late_entry(
    rsi_14: float,
    direction: str,               # "long" or "short"
    price: float,
    vwap: float,
    atr_current: float,
    hh_hl_count: int,             # from trending-bull-entry-timing
    funding_rate_1h_pct: float,   # from high-funding-carry-avoidance
) -> dict:
    rsi_long_ok    = direction != "long"  or rsi_14 <= 75.0
    rsi_short_ok   = direction != "short" or rsi_14 >= 25.0
    rsi_ok         = rsi_long_ok and rsi_short_ok

    vwap_dist_atr  = abs(price - vwap) / atr_current
    vwap_ok        = vwap_dist_atr <= 2.0

    trend_mature   = hh_hl_count >= 8
    maturity_ok    = not trend_mature

    funding_ok     = not (
        direction == "long"  and funding_rate_1h_pct >  0.025  # crowded long
    ) and not (
        direction == "short" and funding_rate_1h_pct < -0.025  # crowded short
    )

    filter_pass = rsi_ok and vwap_ok and maturity_ok and funding_ok
    return {
        "filter_pass":   filter_pass,
        "failure_mode":  "FM-2" if not filter_pass else None,
        "rsi_14":        rsi_14,
        "vwap_dist_atr": vwap_dist_atr,
        "hh_hl_count":   hh_hl_count,
        "funding_1h":    funding_rate_1h_pct,
        "checks": {
            "rsi_ok":      rsi_ok,
            "vwap_ok":     vwap_ok,
            "maturity_ok": maturity_ok,
            "funding_ok":  funding_ok,
        },
        "reason": (
            None if filter_pass else
            "Late entry / trend exhaustion: " +
            ", ".join([
                k for k, v in {
                    f"RSI={rsi_14:.1f}": not rsi_ok,
                    f"VWAP_dist={vwap_dist_atr:.1f}x_ATR": not vwap_ok,
                    f"trend_mature({hh_hl_count}_legs)": not maturity_ok,
                    f"funding={funding_rate_1h_pct:.3f}%": not funding_ok,
                }.items() if v
            ])
        ),
    }
```

---

### FM-3: False Cross from Spike / Wick

**Description**: A momentary price spike (news event, liquidation
cascade, large single order) drives the fast EMA through the slow
EMA temporarily. The cross is not confirmed by sustained price
action — price snaps back within 1-3 candles, leaving the position
on the wrong side of the pre-spike range.

**Market conditions that cause FM-3**:
- The triggering candle has a wick > 2× its body
- Volume on the trigger candle is > 3× the 20-period average (spike,
  not accumulation)
- The cross occurs within 30 minutes of a major news event or
  scheduled economic release
- Cascade score ≥ 3 (book fragility elevated — the spike may be a
  partial cascade, not trend initiation)

**Damage profile**: One sharp loss as price retraces the spike.
SL is often hit before the position can be managed.

**Detection filter**:
```python
def filter_fm3_false_spike(
    trigger_candle_body_pct: float,  # |close - open| / open
    trigger_candle_wick_pct: float,  # total wick / body ratio
    volume_ratio: float,              # trigger candle vol / 20p avg vol
    minutes_to_news_event: float,     # 0 if no event; large if far
    cascade_score: int,               # from liquidation-cascade-risk
) -> dict:
    wick_ok    = trigger_candle_wick_pct <= 2.0
    volume_ok  = volume_ratio <= 3.0
    news_ok    = minutes_to_news_event > 30 or minutes_to_news_event == 0
    cascade_ok = cascade_score < 3

    filter_pass = wick_ok and volume_ok and news_ok and cascade_ok
    return {
        "filter_pass":  filter_pass,
        "failure_mode": "FM-3" if not filter_pass else None,
        "checks": {
            "wick_ok":    wick_ok,
            "volume_ok":  volume_ok,
            "news_ok":    news_ok,
            "cascade_ok": cascade_ok,
        },
        "reason": (
            None if filter_pass else
            "Spike/false cross detected: " +
            ", ".join([
                k for k, v in {
                    f"wick_ratio={trigger_candle_wick_pct:.1f}x": not wick_ok,
                    f"vol_ratio={volume_ratio:.1f}x": not volume_ok,
                    f"near_news_event ({minutes_to_news_event:.0f}min)": not news_ok,
                    f"cascade_score={cascade_score}": not cascade_ok,
                }.items() if v
            ])
        ),
    }
```

---

### FM-4: Counter-Trend Cross in Strong Opposing Trend

**Description**: The EMA cross fires in the direction opposite to the
dominant higher-timeframe trend. The signal is a pullback or
correction being misread as a new trend by the shorter-timeframe
EMAs. The higher-timeframe trend reasserts, stopping out the position.

**Market conditions that cause FM-4**:
- Daily or 4H EMA alignment is opposite to the signal direction
- Higher-timeframe structure shows the signal direction is against
  the prevailing swing (e.g., 1H long signal during 4H downtrend)
- Price is below the 200 EMA on the signal timeframe for a long
  signal, or above it for a short signal

**Damage profile**: Medium loss (1.5-2× SL) as the higher-timeframe
trend overcomes the minor countertrend move. Sometimes produces the
largest individual losses in the strategy's history.

**Detection filter**:
```python
def filter_fm4_counter_trend(
    signal_direction: str,            # "long" or "short"
    htf_ema_fast: float,              # e.g. 20 EMA on 4H
    htf_ema_slow: float,              # e.g. 50 EMA on 4H
    htf_price: float,                 # current price on 4H
    ema_200_signal_tf: float,         # 200 EMA on signal timeframe
    current_price: float,
) -> dict:
    # Higher timeframe trend direction
    htf_trend = "long" if htf_ema_fast > htf_ema_slow else "short"
    htf_aligned = htf_trend == signal_direction

    # 200 EMA filter on signal timeframe
    if signal_direction == "long":
        ema_200_ok = current_price > ema_200_signal_tf
    else:
        ema_200_ok = current_price < ema_200_signal_tf

    filter_pass = htf_aligned and ema_200_ok
    return {
        "filter_pass":   filter_pass,
        "failure_mode":  "FM-4" if not filter_pass else None,
        "htf_trend":     htf_trend,
        "htf_aligned":   htf_aligned,
        "ema_200_ok":    ema_200_ok,
        "reason": (
            None if filter_pass else
            "Counter-trend signal: " +
            ", ".join([
                k for k, v in {
                    f"HTF_trend={htf_trend}_vs_signal={signal_direction}": not htf_aligned,
                    f"price_vs_200EMA={'below' if signal_direction == 'long' else 'above'}": not ema_200_ok,
                }.items() if v
            ])
        ),
    }
```

---

### FM-5: Funding-Suppressed Edge in Perpetuals

**Description**: Perpetuals-specific failure mode with no analogue
in spot or futures markets. An EMA long signal fires in an elevated
funding regime where longs pay shorts a significant continuous carry
cost. The nominal price move required to break even is now larger
than the strategy's historical average TP distance. The edge is
not zero — it is negative after carry costs.

**Market conditions that cause FM-5**:
- 1h funding rate > 0.03% for a long signal (annualises to > 26%)
- 8h funding rate > 0.10% for a long signal
- Funding has been elevated for > 3 consecutive 8h periods
  (structural, not transient)
- OI has been increasing while funding rises (leveraged long
  overcrowding — vulnerable to forced unwind)

**Damage profile**: Slow bleed on otherwise valid trend entries.
P&L gradually erodes even on winning trades; losing trades lose
more than the SL because carry accumulates to the close time.
See `high-funding-carry-avoidance` for quantification.

**Detection filter**:
```python
def filter_fm5_funding_suppression(
    direction: str,
    funding_1h_pct: float,
    funding_8h_pct: float,
    consecutive_elevated_periods: int,  # from high-funding-carry-avoidance
    oi_trend: str,                       # "increasing" | "stable" | "decreasing"
) -> dict:
    """
    For shorts, elevated funding is beneficial (shorts receive).
    This filter primarily protects long entries.
    """
    if direction == "short":
        # Shorts benefit from elevated funding; inverse check for extreme negative funding
        filter_pass = funding_1h_pct >= -0.03   # extreme negative funding = carry cost for shorts
        reason = f"Extreme negative funding={funding_1h_pct:.3f}% harms short carry" if not filter_pass else None
        return {"filter_pass": filter_pass, "failure_mode": "FM-5" if not filter_pass else None, "reason": reason}

    # Long entry checks
    funding_1h_ok  = funding_1h_pct  <= 0.030
    funding_8h_ok  = funding_8h_pct  <= 0.100
    duration_ok    = consecutive_elevated_periods <= 3
    oi_ok          = not (oi_trend == "increasing" and funding_1h_pct > 0.020)

    filter_pass = funding_1h_ok and funding_8h_ok and duration_ok and oi_ok
    return {
        "filter_pass":  filter_pass,
        "failure_mode": "FM-5" if not filter_pass else None,
        "checks": {
            "funding_1h_ok":  funding_1h_ok,
            "funding_8h_ok":  funding_8h_ok,
            "duration_ok":    duration_ok,
            "oi_ok":          oi_ok,
        },
        "reason": (
            None if filter_pass else
            f"Funding-suppressed edge: 1h={funding_1h_pct:.3f}%, "
            f"8h={funding_8h_pct:.3f}%, "
            f"elevated_periods={consecutive_elevated_periods}, "
            f"OI_trend={oi_trend}. Carry cost erodes long edge."
        ),
    }
```

---

### FM-6: Liquidation Cascade Distortion

**Description**: The EMA cross fires during or immediately after a
liquidation cascade. The price move that generated the cross was
driven by forced selling/buying, not organic directional conviction.
Once cascade liquidations exhaust, price reverts sharply to
pre-cascade levels, stopping out any position entered on the
cascade-generated signal.

**Market conditions that cause FM-6**:
- Cascade score ≥ 5 at or immediately before signal time
- Open interest dropped > 3% in the preceding 30 minutes
- Funding rate spiked then snapped back within 1-2 periods
  (hallmark of cascade-driven liquidation, not genuine trend)
- Book fragility HIGH or CRITICAL (from `liquidation-cascade-risk`)

**Damage profile**: Sharp entry followed by immediate reversal.
SL is often hit within 1-3 candles. Sometimes the largest
individual loss in the strategy's history.

**Detection filter**:
```python
def filter_fm6_cascade_distortion(
    cascade_score: int,              # from liquidation-cascade-risk
    oi_change_30m_pct: float,        # % change in OI in last 30 min
    funding_snapped_back: bool,      # True if funding spiked + reverted in <2 periods
    book_fragility: str,             # "LOW"|"MODERATE"|"HIGH"|"CRITICAL"
) -> dict:
    cascade_ok         = cascade_score < 5
    oi_ok              = oi_change_30m_pct > -3.0   # negative = OI dropped (liq event)
    funding_snap_ok    = not funding_snapped_back
    fragility_ok       = book_fragility not in ("HIGH", "CRITICAL")

    filter_pass = cascade_ok and oi_ok and funding_snap_ok and fragility_ok
    return {
        "filter_pass":  filter_pass,
        "failure_mode": "FM-6" if not filter_pass else None,
        "checks": {
            "cascade_ok":      cascade_ok,
            "oi_ok":           oi_ok,
            "funding_snap_ok": funding_snap_ok,
            "fragility_ok":    fragility_ok,
        },
        "reason": (
            None if filter_pass else
            f"Cascade distortion: score={cascade_score}, "
            f"OI_change_30m={oi_change_30m_pct:.1f}%, "
            f"funding_snap={funding_snapped_back}, "
            f"fragility={book_fragility}. "
            "EMA cross driven by forced liquidations, not organic trend."
        ),
    }
```

---

## Master Pre-Entry Filter

Run all six filters in sequence before any EMA cross entry.
All six must pass. A failure at any level blocks the entry.

```python
def ema_cross_pre_entry_filter(
    # FM-1 inputs
    adx_14: float,
    bb_width_pct: float,
    bb_width_20p_median: float,
    atr_current: float,
    atr_20p_median: float,
    # FM-2 inputs
    rsi_14: float,
    direction: str,
    price: float,
    vwap: float,
    hh_hl_count: int,
    # FM-3 inputs
    trigger_candle_wick_pct: float,
    volume_ratio: float,
    minutes_to_news_event: float,
    # FM-4 inputs
    htf_ema_fast: float,
    htf_ema_slow: float,
    htf_price: float,
    ema_200_signal_tf: float,
    # FM-5 inputs
    funding_1h_pct: float,
    funding_8h_pct: float,
    consecutive_elevated_periods: int,
    oi_trend: str,
    # FM-6 inputs
    cascade_score: int,
    oi_change_30m_pct: float,
    funding_snapped_back: bool,
    book_fragility: str,
) -> dict:
    results = {
        "FM-1": filter_fm1_whipsaw(adx_14, bb_width_pct, bb_width_20p_median, atr_current, atr_20p_median),
        "FM-2": filter_fm2_late_entry(rsi_14, direction, price, vwap, atr_current, hh_hl_count, funding_1h_pct),
        "FM-3": filter_fm3_false_spike(0.0, trigger_candle_wick_pct, volume_ratio, minutes_to_news_event, cascade_score),
        "FM-4": filter_fm4_counter_trend(direction, htf_ema_fast, htf_ema_slow, htf_price, ema_200_signal_tf, price),
        "FM-5": filter_fm5_funding_suppression(direction, funding_1h_pct, funding_8h_pct, consecutive_elevated_periods, oi_trend),
        "FM-6": filter_fm6_cascade_distortion(cascade_score, oi_change_30m_pct, funding_snapped_back, book_fragility),
    }

    failures = {k: v for k, v in results.items() if not v["filter_pass"]}
    all_pass  = len(failures) == 0

    return {
        "entry_permitted": all_pass,
        "failures":        failures,
        "failure_count":   len(failures),
        "reason": (
            "All EMA cross filters passed." if all_pass else
            f"{len(failures)} filter(s) failed: " +
            "; ".join(f"{k}: {v['reason']}" for k, v in failures.items())
        ),
        "per_filter": results,
    }
```

---

## Post-Entry Management Rules

When a signal passes all six filters and an entry is taken, these
management rules limit damage if the trade develops into a failure
despite passing the pre-entry checks:

```
Rule M-1: Time-Based Stop
  If position is open for > 3× the average winning trade duration
  with less than 25% of TP distance covered, close at market.
  Reason: valid trends move quickly; slow non-moving positions are
  FM-1 or FM-4 failures that passed the filter near the threshold.

Rule M-2: EMA Re-Cross Exit
  If the fast EMA re-crosses the slow EMA in the opposite direction
  of the trade while in profit, close at market immediately.
  Do not wait for TP. Reason: re-cross signals trend exhaustion;
  returning a partial profit is better than watching it evaporate.

Rule M-3: Funding Regime Change Exit
  If funding regime transitions to ELEVATED or EXTREME while a
  long position is open and unrealised PnL is positive, close
  at market. Do not hold through a funding regime change.
  Reason: FM-5 conditions can develop post-entry; the edge
  computation at entry assumed a different carry cost.

Rule M-4: Cascade Score Escalation Exit
  If cascade score rises to ≥ 5 (HIGH) while a position is open,
  evaluate closing if unrealised PnL is positive. If unrealised
  PnL is negative, hold to SL (do not close at a worse price
  than SL). Reason: FM-6 conditions can develop post-entry;
  protect profits but don’t panic-close into a worse loss.

Rule M-5: Trailing Stop Activation
  Once price has moved 1.0× ATR in the trade direction from entry,
  move SL to breakeven. Once price has moved 1.5× ATR, activate
  a trailing stop at 0.75× ATR behind the highest achieved price.
  Reason: converts a potential FM-2 late loss into a breakeven or
  small win on a trade that initially moved correctly.
```

---

## Failure Mode by EMA Parameter Sensitivity

Different EMA period choices amplify different failure modes:

| EMA Pair (Fast/Slow) | Primary Failure Mode Risk | Secondary Failure Mode Risk | Suitable Timeframe |
|---|---|---|---|
| 9 / 21 | FM-1 (whipsaw), FM-3 (spikes) | FM-6 (cascade) | 15m–1H trending only |
| 13 / 34 (Fibonacci) | FM-1 (moderate), FM-2 (late) | FM-4 (counter-trend) | 1H–4H |
| 20 / 50 | FM-2 (late entry), FM-4 | FM-5 (funding) | 4H–Daily |
| 50 / 200 | FM-2 (very late), FM-4 | FM-6 (low risk) | Daily |

> Faster pairs generate more signals and more FM-1/FM-3 failures.
> Slower pairs generate fewer signals but are more vulnerable to
> FM-2 (entering near exhaustion) because the cross lags the move.
> No EMA pair eliminates all failure modes — regime filtering
> is always required.

---

## Failure Mode Attribution for Post-Trade Analysis

After every EMA cross loss, classify the failure mode using this
triage tree and log it. Over time, failure mode frequency reveals
which regime conditions most harm the strategy:

```
Post-Trade Triage:
│
├── Was ADX < 20 or BB width compressed at entry?
│     Yes → FM-1 (Whipsaw). Filter was near threshold or disabled.
│
├── Did price reverse sharply within 1-2 candles of entry?
│   ├── Was there a spike/wick on the trigger candle?
│   │     Yes → FM-3 (False Spike)
│   └── Was OI dropping or cascade score elevated?
│         Yes → FM-6 (Cascade Distortion)
│
├── Did price continue the trend for a while then reverse
│   before reaching TP?
│   ├── Was RSI > 75 or HH/HL count > 7 at entry?
│   │     Yes → FM-2 (Late Entry)
│   └── Was HTF trend opposite to signal direction?
│         Yes → FM-4 (Counter-Trend)
│
├── Did the trade bleed slowly rather than hitting SL sharply?
│     Yes + funding elevated → FM-5 (Funding Suppression)
│
└── None of the above clearly apply → Random adverse outcome.
      Log as FM-0 (Baseline Variance). Not a filter failure.
```

---

## Worked Example — Signal Rejected by FM-4 + FM-5

```
Signal: ETH-PERP, 1H chart, EMA 13/34 long cross
Timestamp: 2026-04-07T14:00Z

Filter inputs:
  ADX_14:                    28.4      FM-1: ok
  BB_width_pct:              1.8%      FM-1: ok (median 1.6%, ratio 1.12)
  ATR_current:               $42       FM-1: ok
  RSI_14:                    71.2      FM-2: ok (< 75)
  VWAP_dist_atr:             1.4x      FM-2: ok (< 2.0)
  HH_HL_count (4H):          6         FM-2: ok (< 8)
  Trigger wick ratio:        1.3x      FM-3: ok
  Volume ratio:              1.8x      FM-3: ok
  Funding_1h:                0.031%    FM-2: funding_ok=False (> 0.025 crowded)
                                       FM-5: funding_1h_ok=False (> 0.030)
  HTF 4H EMA_20:             $2,850    FM-4: htf_ema_fast < htf_ema_slow -> bearish
  HTF 4H EMA_50:             $2,920    FM-4: htf_trend=short vs signal=long -> FAIL
  EMA_200 (1H):              $2,760    FM-4: price=$2,870 > EMA_200 -> ok
  Cascade_score:             2         FM-6: ok
  OI_change_30m:             +0.4%     FM-6: ok
  Book_fragility:            MODERATE  FM-6: ok

Filter results:
  FM-1: PASS
  FM-2: FAIL — funding_ok=False (funding_1h=0.031% indicates crowded long)
  FM-3: PASS
  FM-4: FAIL — HTF 4H trend is SHORT vs 1H long signal
  FM-5: FAIL — funding_1h=0.031% > 0.030 threshold, carry suppresses long edge
  FM-6: PASS

Decision: ENTRY REJECTED (3 filter failures: FM-2, FM-4, FM-5)
Reason: Counter-trend on 4H; crowded long funding at 0.031%;
        carry cost erodes long edge at current funding regime.
```

---

## Audit JSONL Schema

```json
{
  "event": "ema_cross_filter_evaluation",
  "timestamp_utc": "2026-04-07T14:00:00Z",
  "asset": "ETH",
  "timeframe": "1H",
  "ema_pair": "13/34",
  "signal_direction": "long",
  "entry_permitted": false,
  "failure_count": 3,
  "failures": ["FM-2", "FM-4", "FM-5"],
  "reason": "FM-2: funding crowded; FM-4: HTF counter-trend; FM-5: carry suppressed",
  "per_filter": {
    "FM-1": {"filter_pass": true},
    "FM-2": {"filter_pass": false, "reason": "funding_1h=0.031%"},
    "FM-3": {"filter_pass": true},
    "FM-4": {"filter_pass": false, "reason": "HTF_trend=short_vs_signal=long"},
    "FM-5": {"filter_pass": false, "reason": "1h=0.031%, carry erodes long edge"},
    "FM-6": {"filter_pass": true}
  },
  "signal_price": 2870.00,
  "adx_14": 28.4,
  "rsi_14": 71.2,
  "funding_1h_pct": 0.031,
  "cascade_score": 2,
  "htf_trend": "short"
}
```

---

## Integration with Other Skills

- **`trending-bull-entry-timing`** (regime-detection/): Provides
  `hh_hl_count` (FM-2 late entry check) and regime classification
  (nascent / established / mature). FM-2 late entry filter directly
  consumes the HH/HL leg count from that skill.
- **`high-funding-carry-avoidance`** (regime-detection/): Provides
  `funding_1h_pct`, `funding_8h_pct`, `consecutive_elevated_periods`,
  `funding_regime`, and `carry_discount`. FM-2 and FM-5 filters both
  consume funding data. Run carry-avoidance skill first; pass its
  output directly to FM-2 and FM-5 inputs.
- **`liquidation-cascade-risk`** (regime-detection/): Provides
  `cascade_score` and `book_fragility`. FM-3 and FM-6 both consume
  cascade data. Run cascade risk skill first; pass output to FM-3
  and FM-6 inputs.
- **`kelly-position-sizing-perps`** (risk/): EMA cross filter must
  pass (`entry_permitted=True`) before Kelly sizing is computed.
  The filter evaluation is cheap; Kelly sizing is expensive. Do not
  run Kelly until the filter confirms the signal is valid.
- **`rsi-reversal-regime-dependency`** (strategy/): FM-2 uses RSI
  as an exhaustion indicator. If the RSI reversal skill is active
  in the same session, coordinate to ensure RSI thresholds are
  consistent across both skills.
- **`drawdown-kill-switch-trigger`** (risk/): FM-6 cascade distortion
  check should run in parallel with the kill-switch tier evaluation.
  A cascade score ≥ 8 triggers both a kill-switch tier escalation
  AND an FM-6 filter failure — belt and suspenders.

---

## Quick Decision Tree

```
EMA cross signal fires:
│
├── 1. Gather regime inputs (run in parallel):
│     trending-bull-entry-timing  → hh_hl_count, regime_class
│     high-funding-carry-avoidance → funding_1h, funding_8h,
│                                     consecutive_periods, regime
│     liquidation-cascade-risk    → cascade_score, book_fragility,
│                                     oi_change_30m
│
├── 2. Run ema_cross_pre_entry_filter() with all inputs
│     entry_permitted == False? → SKIP signal. Log rejection.
│                                  Do not size. Do not order.
│
├── 3. entry_permitted == True:
│     Pass to kelly-position-sizing-perps
│     → max-concurrent-positions
│     → slippage-budget-enforcement
│     → maker-order-preference / limit-offset-bps-calculation
│
├── 4. While in position — monitor post-entry rules M-1 through M-5:
│     M-1: time stop, M-2: re-cross exit, M-3: funding change exit,
│     M-4: cascade escalation exit, M-5: trailing stop activation
│
└── 5. On position close — classify failure mode (if loss):
      Run post-trade triage. Log failure_mode to audit.
      Update rolling FM frequency counts.
      If FM frequency > 30% of losses for any single mode:
        flag for strategy parameter review.
```
