---
name: kelly-position-sizing-perps
description: Use when sizing any perpetual position on HyperLiquid to compute the Kelly-optimal notional, apply fractional Kelly for risk management, cap by portfolio exposure limits, and adjust for leverage, funding carry cost, and correlation to existing positions.
category: agentic
---

# Kelly Position Sizing — Perpetuals

## When This Skill Activates

Apply this skill **before every new position entry** on HyperLiquid
perpetuals to determine the maximum allowable notional size. Also apply when:

- Scaling into an existing position (second leg, post-cascade re-entry)
- Evaluating whether a strategy signal has sufficient edge to justify
  any position at all
- Adjusting position size after a regime change (funding spike, OI surge,
  book fragility increase)
- Computing correlated exposure caps when multiple positions are open
  simultaneously across related assets
- Backtesting a strategy and needing a principled sizing model to avoid
  over-fit fixed-fraction assumptions

---

## Core Principle

The Kelly Criterion maximises the long-run geometric growth rate of
capital by sizing each bet as a fraction of bankroll proportional to
edge divided by odds. Applied naively to leveraged perpetuals, full
Kelly produces positions that are **far too large** for practical risk
management — it optimises for long-run median outcome but accepts
short-run ruin probability that is unacceptable in a live trading
system. **Fractional Kelly** (typically ¼ to ½ Kelly) captures most
of the growth rate benefit while dramatically reducing drawdown and
ruin risk.

> **Rule**: Compute full Kelly as the theoretical maximum. Apply a
> Kelly fraction of 0.25–0.50. Then enforce hard portfolio caps
> regardless of Kelly output. The Kelly formula is a ceiling, never
> a floor.

---

## Kelly Formula for Perpetuals

### Base Kelly Fraction

For a binary win/loss trade model (entry → TP or SL):

```python
def kelly_fraction(
    win_rate: float,          # estimated probability of hitting TP before SL
    avg_win_pct: float,       # average win as % of notional (TP distance)
    avg_loss_pct: float,      # average loss as % of notional (SL distance)
) -> float:
    """
    Standard Kelly formula: f* = (p * b - q) / b
    where:
      p = win_rate
      q = 1 - win_rate
      b = avg_win_pct / avg_loss_pct  (reward-to-risk ratio)
    Returns fraction of bankroll to risk (0.0 to 1.0).
    Returns 0.0 if edge is zero or negative (do not trade).
    """
    if avg_loss_pct <= 0 or avg_win_pct <= 0:
        return 0.0
    b = avg_win_pct / avg_loss_pct
    q = 1.0 - win_rate
    f_star = (win_rate * b - q) / b
    return max(0.0, f_star)

# Example: 55% win rate, 2% TP, 1% SL (2:1 RR)
# b = 2.0
# f* = (0.55 * 2.0 - 0.45) / 2.0 = (1.10 - 0.45) / 2.0 = 0.325
# Full Kelly = 32.5% of bankroll at risk on this trade
# Quarter Kelly = 8.125% of bankroll at risk
```

### Converting Kelly Fraction to Notional Size

```python
def kelly_notional(
    portfolio_nav_usd: float,    # total account equity (totalRawUsd from marginSummary)
    kelly_f: float,              # full Kelly fraction from kelly_fraction()
    kelly_multiplier: float,     # fractional Kelly: 0.25 (conservative) to 0.50 (moderate)
    avg_loss_pct: float,         # SL distance as % of notional
    leverage: float,             # target leverage for the position
    carry_discount: float = 1.0, # from high-funding-carry-avoidance (0.0-1.0)
) -> dict:
    """
    Converts Kelly fraction to a notional position size in USD.
    Accounts for leverage (Kelly sizes the *risk*, not the notional),
    fractional Kelly multiplier, and carry cost discount.
    """
    # Kelly sizes the fraction of NAV to PUT AT RISK (i.e., the SL dollar amount)
    risk_usd = portfolio_nav_usd * kelly_f * kelly_multiplier

    # Apply carry discount (from high-funding-carry-avoidance skill)
    risk_usd_adjusted = risk_usd * carry_discount

    # Convert risk amount to notional via SL distance:
    # risk_usd = notional * avg_loss_pct  =>  notional = risk_usd / avg_loss_pct
    notional_usd = risk_usd_adjusted / avg_loss_pct

    # Margin required at target leverage:
    margin_required_usd = notional_usd / leverage

    return {
        "full_kelly_f": kelly_f,
        "applied_kelly_f": kelly_f * kelly_multiplier,
        "risk_usd": risk_usd_adjusted,
        "notional_usd": notional_usd,
        "margin_required_usd": margin_required_usd,
        "effective_leverage": leverage,
    }

# Example: $100k NAV, f*=0.325, quarter Kelly (0.25), 1% SL, 5x leverage, no carry discount
# risk_usd     = $100,000 * 0.325 * 0.25 = $8,125
# notional_usd = $8,125 / 0.01 = $812,500   <- notional exposure
# margin_req   = $812,500 / 5 = $162,500    <- but this exceeds NAV!
# -> Portfolio cap enforcement (below) will reduce this
```

---

## Portfolio Cap Enforcement

Kelly output must pass through **three hard caps** in sequence. The
final notional is the minimum of Kelly output and all three caps:

```python
# Hard caps (configure per firm risk policy):
MAX_SINGLE_POSITION_PCT_NAV  = 0.20   # 20% of NAV as margin on any single position
MAX_SINGLE_NOTIONAL_PCT_NAV  = 2.00   # 200% of NAV as notional (2x gross leverage cap)
MAX_CORRELATED_EXPOSURE_PCT  = 0.35   # 35% of NAV in correlated assets (e.g. BTC+ETH)
MAX_TOTAL_MARGIN_UTILIZATION = 0.60   # 60% of NAV deployed as margin across all positions

def apply_portfolio_caps(
    kelly_result: dict,
    portfolio_nav_usd: float,
    current_margin_used_usd: float,
    correlated_exposure_usd: float,   # existing notional in correlated assets
    asset_correlation: float = 0.0,   # 0.0-1.0; BTC/ETH ~0.85, BTC/SOL ~0.70
) -> dict:
    notional  = kelly_result["notional_usd"]
    margin    = kelly_result["margin_required_usd"]
    leverage  = kelly_result["effective_leverage"]

    # Cap 1: single position margin
    max_margin = portfolio_nav_usd * MAX_SINGLE_POSITION_PCT_NAV
    if margin > max_margin:
        notional = max_margin * leverage
        margin   = max_margin

    # Cap 2: single position notional
    max_notional = portfolio_nav_usd * MAX_SINGLE_NOTIONAL_PCT_NAV
    if notional > max_notional:
        notional = max_notional
        margin   = notional / leverage

    # Cap 3: total margin utilization
    available_margin = portfolio_nav_usd * MAX_TOTAL_MARGIN_UTILIZATION - current_margin_used_usd
    if margin > available_margin:
        margin   = max(0.0, available_margin)
        notional = margin * leverage

    # Cap 4: correlated exposure
    # New notional adds to correlated bucket scaled by correlation coefficient
    correlated_addition = notional * asset_correlation
    if correlated_exposure_usd + correlated_addition > portfolio_nav_usd * MAX_CORRELATED_EXPOSURE_PCT:
        allowed_addition = max(0.0, portfolio_nav_usd * MAX_CORRELATED_EXPOSURE_PCT - correlated_exposure_usd)
        notional = allowed_addition / asset_correlation if asset_correlation > 0 else notional
        margin   = notional / leverage

    return {
        "final_notional_usd": max(0.0, notional),
        "final_margin_usd":   max(0.0, margin),
        "binding_cap": _identify_binding_cap(kelly_result["notional_usd"], notional),
    }

def _identify_binding_cap(original: float, final: float) -> str:
    if final >= original * 0.99: return "none"        # Kelly was binding
    if final < original * 0.30:  return "correlated"  # correlation cap cut deeply
    return "portfolio_margin"                          # margin/notional cap binding
```

---

## Kelly Multiplier Selection Guide

The Kelly multiplier (fractional Kelly) is the most important practical
decision in the sizing framework. Select based on strategy confidence:

| Kelly Multiplier | Risk Profile | When to Use |
|---|---|---|
| 0.10–0.15 | Ultra-conservative | New strategy, unvalidated; nascent trend regime; first 20 live trades |
| 0.25 | Conservative | Validated strategy, < 50 live trades, or elevated market risk (cascade score ≥ 3) |
| 0.33 | Moderate | Validated strategy, 50–200 live trades, normal regime, cascade score ≤ 2 |
| 0.50 | Moderate-aggressive | Well-validated strategy, 200+ live trades, established trend, all regime checks green |
| > 0.50 | **Not recommended** | Full Kelly and above: theoretically optimal but practically catastrophic drawdowns |

> Default to **0.25** when uncertain. Increase multiplier only after
> live performance confirms the win rate and RR ratio assumptions.
> The Kelly formula is only as good as the edge estimate — overestimated
> win rates produce oversized positions that ruin accounts.

---

## Edge Estimation Best Practices

The Kelly formula amplifies errors in edge estimation. A 5% overestimate
of win rate can double the recommended position size. Apply these
checks before trusting any edge estimate:

```python
def validate_edge_estimate(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    sample_size: int,
    confidence: str = "low",   # "low", "medium", "high"
) -> dict:
    # Minimum sample sizes for reliable Kelly estimation:
    MIN_SAMPLES = {"high": 200, "medium": 100, "low": 30}

    expectancy = win_rate * avg_win_pct - (1 - win_rate) * avg_loss_pct
    profit_factor = (win_rate * avg_win_pct) / ((1 - win_rate) * avg_loss_pct)

    # Wilson score interval 95% CI on win rate:
    import math
    z = 1.96
    n = sample_size
    p = win_rate
    centre = (p + z*z/(2*n)) / (1 + z*z/n)
    margin = (z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))) / (1 + z*z/n)
    win_rate_lower_ci = max(0.0, centre - margin)

    # Conservative Kelly uses lower CI on win rate:
    kelly_conservative = kelly_fraction(win_rate_lower_ci, avg_win_pct, avg_loss_pct)

    return {
        "expectancy_pct": expectancy * 100,
        "profit_factor": profit_factor,
        "win_rate_lower_95ci": win_rate_lower_ci,
        "kelly_conservative": kelly_conservative,
        "sufficient_sample": sample_size >= MIN_SAMPLES[confidence],
        "recommendation": "use kelly_conservative" if sample_size < 200 else "use kelly_fraction",
    }
```

**Always use `kelly_conservative` (lower CI on win rate) when sample
size < 200 trades.** This is the single most important practical
adjustment to standard Kelly theory.

---

## Regime Adjustments

Apply these multipliers to the Kelly output **after** the base
calculation and **before** portfolio cap enforcement:

| Condition | Source Skill | Multiplier | Rationale |
|---|---|---|---|
| Cascade score ≥ 5 (HIGH) | `liquidation-cascade-risk` | × 0.50 | Book fragility increases true loss probability |
| Cascade score ≥ 8 (CRITICAL) | `liquidation-cascade-risk` | × 0.00 | No new positions during active cascade |
| Funding regime ELEVATED | `high-funding-carry-avoidance` | carry_discount from that skill | Carry cost reduces net edge |
| Nascent trend (< 3 HH/HL) | `trending-bull-entry-timing` | × 0.40 | Trend not confirmed; higher false-signal rate |
| Post-cascade re-entry (leg 1) | `liquidation-cascade-risk` | × 0.50 | Uncertainty about cascade exhaustion |
| Mature trend (8+ HH/HL) | `trending-bull-entry-timing` | × 0.50 | Proximity to exhaustion; asymmetric downside |
| New strategy (< 20 live trades) | — | × 0.15 | Edge unvalidated; protect bankroll during learning |

---

## Worked Example — Full Sizing Pipeline

```
Inputs:
  Portfolio NAV:         $200,000
  Current margin used:   $20,000
  Asset:                 ETH perp
  Strategy:              Trending bull pullback (established, 120 live trades)
  Win rate (observed):   0.58  (58%)
  Sample size:           120 trades
  Avg TP distance:       1.8% of notional
  Avg SL distance:       0.9% of notional  (2:1 RR)
  Target leverage:       4x
  Funding 1h:            0.018% (carry_discount from carry-avoidance skill: 0.82)
  Cascade score:         2  (NORMAL, no multiplier)
  Correlated exposure
  (BTC position open):   $80,000 notional (ETH correlation to BTC: 0.85)
  Kelly multiplier:      0.33 (moderate; 120 validated trades)

Step 1 — Validate edge:
  win_rate_lower_95ci  = 0.494  (lower CI on 0.58 @ n=120)
  kelly_conservative   = kelly_fraction(0.494, 1.8%, 0.9%)
                       = (0.494 * 2.0 - 0.506) / 2.0 = 0.241

Step 2 — Base Kelly notional:
  risk_usd             = $200,000 * 0.241 * 0.33 * 0.82  (carry discount)
                       = $200,000 * 0.065 = $13,034
  notional_usd         = $13,034 / 0.009 = $1,448,222   <- very large; caps will bind
  margin_required      = $1,448,222 / 4 = $362,056

Step 3 — Apply portfolio caps:
  Cap 1 (20% NAV margin): max_margin = $40,000
    notional = $40,000 * 4 = $160,000  margin = $40,000
  Cap 3 (60% total margin): available = $200,000*0.60 - $20,000 = $100,000
    margin $40,000 < $100,000 ✔ passes
  Cap 4 (correlated 35% NAV = $70,000):
    new correlated addition = $160,000 * 0.85 = $136,000
    existing correlated     = $80,000 * 0.85 = $68,000
    total projected         = $68,000 + $136,000 = $204,000 > $70,000
    allowed addition        = $70,000 - $68,000 = $2,000
    max notional from corr  = $2,000 / 0.85 = $2,353

Final result:
  final_notional_usd  = $2,353  (correlated exposure cap is binding)
  final_margin_usd    = $2,353 / 4 = $588
  binding_cap         = "correlated"

Implication: the ETH position should not be sized until BTC is partially
closed, OR the Kelly multiplier is correct but the correlated cap policy
needs review if ETH is genuinely a separate signal.
```

---

## Failure Modes to Avoid

- **Using full Kelly (multiplier = 1.0)**: Full Kelly maximises long-run
  median wealth but the path includes drawdowns of 50%+ that are
  psychologically and operationally catastrophic. Quarter Kelly captures
  ~75% of the growth rate with ~25% of the drawdown. Never use full Kelly
  on live capital.
- **Estimating win rate from too few trades**: 20 trades can produce an
  apparent 70% win rate by chance alone. Always use the lower confidence
  interval on win rate for Kelly inputs. With < 30 trades, use 0.10 Kelly
  multiplier regardless of observed win rate.
- **Using Kelly on correlated simultaneous positions as if independent**:
  Two correlated positions (BTC + ETH) are not two independent Kelly bets.
  They share the same underlying risk factor. The correlated exposure cap
  and correlation multiplier in `apply_portfolio_caps()` handle this—
  but only if the correlation coefficient is set correctly.
- **Ignoring leverage in Kelly notional conversion**: Kelly sizes the
  *amount at risk* (SL distance × notional), not the notional directly.
  At 10× leverage, a 1% SL is 10% of margin. Confusing risk-on-notional
  with risk-on-margin produces positions 10× too large or too small.
- **Not adjusting Kelly multiplier after drawdown**: A 15% portfolio
  drawdown is a signal that edge estimates are wrong, market regime has
  changed, or both. After any 10%+ drawdown, reduce Kelly multiplier
  by 50% until live performance restores confidence in the edge estimate.
- **Treating Kelly as a static calculation**: Win rate and RR ratio drift
  as market regimes change. Recompute Kelly inputs from the most recent
  50-trade rolling window, not from the all-time backtest average.

---

## Integration with Other Skills

- **`high-funding-carry-avoidance`** (regime-detection/): Provides
  `carry_discount` multiplier applied to `risk_usd` before notional
  conversion. Always run funding check first; pass carry_discount into
  `kelly_notional()`.
- **`liquidation-cascade-risk`** (regime-detection/): Provides
  `cascade_score` and `book_fragility`. Apply cascade regime multiplier
  to Kelly output before portfolio caps.
- **`trending-bull-entry-timing`** (regime-detection/): Provides regime
  classification (nascent/established/mature). Apply corresponding
  regime multiplier (0.40× / 1.0× / 0.50×) to Kelly output.
- **`slippage-budget-enforcement`** (execution/): Kelly output is the
  `initial_size_usd` input to `max_size_within_budget()`. If slippage
  enforcement reduces the size, the risk engine must be updated with
  the actual executed notional, not the Kelly target.
- **`drawdown-kill-switch-trigger`** (risk/): After any kill-switch
  fire, reset Kelly multiplier to 0.10 for the next session. Kelly
  assumes a stationary edge; a kill-switch fire signals the edge
  assumption has broken down.

---

## Audit JSONL Schema

```json
{
  "event": "kelly_position_sizing",
  "asset": "ETH",
  "timestamp_utc": "2026-04-07T22:00:00Z",
  "portfolio_nav_usd": 200000,
  "win_rate_observed": 0.58,
  "win_rate_lower_ci": 0.494,
  "sample_size": 120,
  "avg_win_pct": 0.018,
  "avg_loss_pct": 0.009,
  "kelly_full_f": 0.241,
  "kelly_multiplier": 0.33,
  "carry_discount": 0.82,
  "cascade_regime_multiplier": 1.0,
  "trend_regime_multiplier": 1.0,
  "risk_usd_adjusted": 13034,
  "kelly_notional_usd": 1448222,
  "binding_cap": "correlated",
  "final_notional_usd": 2353,
  "final_margin_usd": 588,
  "target_leverage": 4,
  "current_margin_used_usd": 20000,
  "correlated_exposure_usd": 68000
}
```

---

## Quick Decision Tree

```
New position entry — compute Kelly size:
│
├── 1. Get regime inputs:
│     carry_discount      ← high-funding-carry-avoidance
│     cascade_multiplier  ← liquidation-cascade-risk (score ≥ 8? → 0.0x: no trade)
│     trend_multiplier    ← trending-bull-entry-timing (regime classification)
│
├── 2. Validate edge:
│     validate_edge_estimate(win_rate, avg_win, avg_loss, n_trades)
│     Use win_rate_lower_ci if n_trades < 200
│     kelly_f = kelly_fraction(win_rate, avg_win, avg_loss)
│     kelly_f == 0? → ABORT. No edge. Do not trade.
│
├── 3. Select Kelly multiplier from guide (default: 0.25)
│
├── 4. Compute notional:
│     result = kelly_notional(nav, kelly_f, multiplier, avg_loss,
│                             leverage, carry_discount)
│     Apply cascade_multiplier and trend_multiplier to result["notional_usd"]
│
├── 5. Apply portfolio caps:
│     final = apply_portfolio_caps(result, nav, margin_used,
│                                  correlated_exposure, correlation)
│     final["final_notional_usd"] == 0? → ABORT. Caps fully consumed.
│
├── 6. Pass final_notional_usd to slippage-budget-enforcement
│     as initial_size_usd → book walk may reduce further
│
└── 7. Log full kelly_position_sizing audit event.
         Execute at actual filled size.
         Update margin tracking with actual margin used.
```
