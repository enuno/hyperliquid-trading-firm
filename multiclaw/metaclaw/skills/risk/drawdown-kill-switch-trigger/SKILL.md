---
name: drawdown-kill-switch-trigger
description: Use when monitoring portfolio drawdown and session P&L to determine whether any circuit-breaker threshold has been breached, which positions must be closed, what trading suspension duration applies, and how to restore trading with a reduced Kelly multiplier after cooldown. This skill governs all kill-switch logic — never bypass it.
category: agentic
---

# Drawdown Kill-Switch Trigger

## When This Skill Activates

This skill is **consulted on every trade cycle** — not only when things
go wrong. Apply it:

- At session open: compute session baseline NAV and check intraday
  drawdown carried over from previous session
- Before every new position entry: confirm kill-switch is not active
- After every position close: update running drawdown metrics
- After any loss > 1.5% NAV in a single trade: immediate re-check
- On any cascade event or liquidation: emergency evaluation regardless
  of trade cycle timing
- On agent restart or reconnect: restore kill-switch state from
  persistent state store before resuming any trading activity

---

## Kill-Switch Tier Definitions

The kill-switch system has **four tiers**. Each tier is a strict
superset of the previous — higher tiers inherit all restrictions of
lower tiers and add new ones. Once a tier is triggered, downgrading
requires explicit cooldown + human approval (tiers 3 and 4) or
automatic cooldown expiry (tiers 1 and 2).

### Tier 1 — Session Soft Stop

**Trigger**: Intraday drawdown from session-open NAV ≥ 3%, OR
three consecutive losing trades in the same session.

**Actions**:
- Halt all new position entries immediately
- Do **not** close existing positions (let them run to their TP/SL)
- Log `kill_switch_tier_1_triggered` audit event
- Set `kelly_multiplier_override = 0.15` for next session
- Suspension duration: remainder of current session only
- Automatic reset: next session open (after sleep window)

**Rationale**: A 3% intraday drawdown is a signal that the strategy
edge is not materialising in the current micro-regime. Stopping new
entries while letting existing positions complete avoids panic-closing
at worst prices while preventing compounding losses.

### Tier 2 — Extended Pause

**Trigger**: Two consecutive sessions where Tier 1 fires, OR total
drawdown from rolling 7-day high-water mark (HWM) ≥ 6%.

**Actions**:
- Halt all new position entries
- Close any open positions at market if unrealised PnL is negative;
  let positive unrealised positions run to TP/SL
- Log `kill_switch_tier_2_triggered` audit event
- Set `kelly_multiplier_override = 0.10` for next two sessions
- Suspension duration: 24 hours from trigger timestamp
- Automatic reset: after 24-hour cooldown + positive equity check

**Rationale**: Back-to-back session stops or a 6% rolling drawdown
indicate a potential regime shift or systematic strategy failure, not
random variance. Closing negative positions prevents drawdown
compounding while the longer cooldown allows market conditions to
evolve.

### Tier 3 — Strategy Suspension

**Trigger**: Total drawdown from all-time or month-start HWM ≥ 10%,
OR a single trade loss ≥ 4% NAV (anomalous loss — slippage failure,
API error, unexpected gap).

**Actions**:
- Immediately close **all** open positions at market (defensive exit)
- Cancel all open orders
- Halt ALL trading activity — no new positions, no re-entries
- Log `kill_switch_tier_3_triggered` with full position snapshot
- Notify: write `KILL_SWITCH_TIER_3.alert` to `logs/alerts/`
- Set `kelly_multiplier_override = 0.10`
- Suspension duration: 72 hours minimum + **human approval required**
  to resume
- Resume only after: root cause analysis filed in
  `logs/postmortem/YYYYMMDD_tier3.md`

**Rationale**: A 10% drawdown from HWM signals a fundamental
breakdown in strategy or risk assumptions. A 4% single-trade loss
implies execution failure or extreme unexpected market behaviour.
Neither resolves without human investigation.

### Tier 4 — Emergency Shutdown

**Trigger**: Any of the following:
- Total portfolio drawdown ≥ 15% from HWM
- Exchange API returning consecutive errors for > 5 minutes with open
  positions
- Margin utilisation > 90% of available margin (liquidation imminent)
- Detecting own orders as the dominant order flow (self-trading signal)
- `EMERGENCY_STOP` signal received from orchestration layer

**Actions**:
- Immediately attempt market close of **all** positions; retry up to
  5 times with exponential backoff (1s, 2s, 4s, 8s, 16s)
- If exchange API unresponsive after all retries: log
  `emergency_close_failed` and write `MANUAL_INTERVENTION_REQUIRED`
  to `logs/alerts/`
- Cancel all open orders
- Revoke trading API key if key rotation is available
- Halt agent process; do not restart automatically
- Log `kill_switch_tier_4_triggered` with complete state dump
- Suspension duration: **indefinite — manual restart only**
- Resume only after: human review, postmortem, exchange confirmation
  of position closure

**Rationale**: Tier 4 covers catastrophic failure modes where
automated recovery could make things worse. Human intervention is
always required.

---

## Core State Machine

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
import time

class KillSwitchTier(Enum):
    NONE   = 0   # all clear — trading permitted
    TIER_1 = 1   # session soft stop
    TIER_2 = 2   # extended pause (24h)
    TIER_3 = 3   # strategy suspension (72h + human)
    TIER_4 = 4   # emergency shutdown (manual only)

@dataclass
class KillSwitchState:
    tier: KillSwitchTier = KillSwitchTier.NONE
    trigger_timestamp_utc: Optional[float] = None
    trigger_reason: str = ""
    session_start_nav: float = 0.0
    hwm_nav: float = 0.0           # all-time or month-start high-water mark
    rolling_7d_hwm: float = 0.0    # 7-day rolling high-water mark
    session_loss_count: int = 0    # consecutive losing trades this session
    consecutive_session_stops: int = 0
    kelly_multiplier_override: float = 0.33  # default; reduced on trigger
    human_approval_required: bool = False
    human_approved: bool = False
    postmortem_filed: bool = False
    cooldown_hours: float = 0.0

    def trading_permitted(self) -> bool:
        """Single authoritative check: is new position entry allowed?"""
        if self.tier == KillSwitchTier.NONE:
            return True
        if self.tier == KillSwitchTier.TIER_1:
            # Auto-resets at next session open; check timestamp
            return False   # session-level check handled by session_open()
        if self.tier in (KillSwitchTier.TIER_2,):
            elapsed_h = (time.time() - self.trigger_timestamp_utc) / 3600
            return elapsed_h >= self.cooldown_hours
        # Tier 3 and 4 require explicit human approval
        return False

    def effective_kelly_multiplier(self, base_multiplier: float) -> float:
        """Returns the lower of base multiplier and any kill-switch override."""
        return min(base_multiplier, self.kelly_multiplier_override)
```

---

## Drawdown Computation

```python
def compute_drawdown_metrics(
    current_nav: float,
    session_start_nav: float,
    hwm_nav: float,
    rolling_7d_hwm: float,
) -> dict:
    """
    Compute all drawdown metrics used for tier evaluation.
    All drawdown values are positive percentages (0.0 = no drawdown).
    """
    intraday_dd   = max(0.0, (session_start_nav - current_nav) / session_start_nav)
    rolling_7d_dd = max(0.0, (rolling_7d_hwm - current_nav) / rolling_7d_hwm)
    alltime_dd    = max(0.0, (hwm_nav - current_nav) / hwm_nav)

    return {
        "current_nav":      current_nav,
        "intraday_dd_pct":  intraday_dd  * 100,
        "rolling_7d_dd_pct": rolling_7d_dd * 100,
        "alltime_dd_pct":   alltime_dd   * 100,
        "nav_vs_hwm_usd":   current_nav - hwm_nav,
    }

def evaluate_kill_switch(
    metrics: dict,
    state: KillSwitchState,
    consecutive_losses: int,
    single_trade_loss_pct: float = 0.0,   # 0.0 if not evaluating a single trade
    margin_utilisation_pct: float = 0.0,  # 0-100
    api_error_minutes: float = 0.0,
    emergency_signal: bool = False,
) -> KillSwitchState:
    """
    Evaluate all trigger conditions and return updated KillSwitchState.
    Tiers are evaluated highest-to-lowest; first match wins.
    Does NOT modify state in place — returns new state object.
    """
    # Tier 4 — emergency conditions first (highest priority)
    if (
        emergency_signal
        or metrics["alltime_dd_pct"] >= 15.0
        or margin_utilisation_pct >= 90.0
        or api_error_minutes >= 5.0
    ):
        return KillSwitchState(
            tier=KillSwitchTier.TIER_4,
            trigger_timestamp_utc=time.time(),
            trigger_reason=_tier4_reason(
                emergency_signal, metrics, margin_utilisation_pct, api_error_minutes
            ),
            session_start_nav=state.session_start_nav,
            hwm_nav=state.hwm_nav,
            rolling_7d_hwm=state.rolling_7d_hwm,
            kelly_multiplier_override=0.10,
            human_approval_required=True,
            cooldown_hours=float("inf"),
        )

    # Tier 3 — strategy suspension
    if (
        metrics["alltime_dd_pct"] >= 10.0
        or single_trade_loss_pct >= 4.0
    ):
        return KillSwitchState(
            tier=KillSwitchTier.TIER_3,
            trigger_timestamp_utc=time.time(),
            trigger_reason=_tier3_reason(metrics, single_trade_loss_pct),
            session_start_nav=state.session_start_nav,
            hwm_nav=state.hwm_nav,
            rolling_7d_hwm=state.rolling_7d_hwm,
            kelly_multiplier_override=0.10,
            human_approval_required=True,
            cooldown_hours=72.0,
        )

    # Tier 2 — extended pause
    if (
        state.consecutive_session_stops >= 2
        or metrics["rolling_7d_dd_pct"] >= 6.0
    ):
        return KillSwitchState(
            tier=KillSwitchTier.TIER_2,
            trigger_timestamp_utc=time.time(),
            trigger_reason=_tier2_reason(state, metrics),
            session_start_nav=state.session_start_nav,
            hwm_nav=state.hwm_nav,
            rolling_7d_hwm=state.rolling_7d_hwm,
            kelly_multiplier_override=0.10,
            human_approval_required=False,
            cooldown_hours=24.0,
        )

    # Tier 1 — session soft stop
    if (
        metrics["intraday_dd_pct"] >= 3.0
        or consecutive_losses >= 3
    ):
        return KillSwitchState(
            tier=KillSwitchTier.TIER_1,
            trigger_timestamp_utc=time.time(),
            trigger_reason=_tier1_reason(metrics, consecutive_losses),
            session_start_nav=state.session_start_nav,
            hwm_nav=state.hwm_nav,
            rolling_7d_hwm=state.rolling_7d_hwm,
            consecutive_session_stops=state.consecutive_session_stops + 1,
            kelly_multiplier_override=0.15,
            human_approval_required=False,
            cooldown_hours=0.0,  # resets at next session open
        )

    # No trigger — return existing state unchanged
    return state
```

---

## Session Lifecycle Hooks

Kill-switch state must integrate with the session lifecycle — not just
evaluated reactively after losses:

```python
def on_session_open(state: KillSwitchState, current_nav: float) -> KillSwitchState:
    """
    Called at the start of every trading session.
    Resets Tier 1 if cooldown has expired; updates session baseline.
    """
    new_state = KillSwitchState(
        tier=KillSwitchTier.NONE if state.tier == KillSwitchTier.TIER_1 else state.tier,
        session_start_nav=current_nav,
        hwm_nav=max(state.hwm_nav, current_nav),   # update HWM if equity recovered
        rolling_7d_hwm=_compute_rolling_7d_hwm(state, current_nav),
        session_loss_count=0,                        # reset consecutive loss counter
        consecutive_session_stops=state.consecutive_session_stops,
        kelly_multiplier_override=state.kelly_multiplier_override,
        human_approval_required=state.human_approval_required,
        human_approved=state.human_approved,
        postmortem_filed=state.postmortem_filed,
    )
    # If Tier 2 cooldown has expired, reset to NONE
    if state.tier == KillSwitchTier.TIER_2:
        elapsed_h = (time.time() - state.trigger_timestamp_utc) / 3600
        if elapsed_h >= state.cooldown_hours and current_nav >= state.session_start_nav:
            new_state.tier = KillSwitchTier.NONE
            new_state.kelly_multiplier_override = 0.25  # conservative, not default 0.33
            new_state.consecutive_session_stops = 0
    return new_state

def on_trade_closed(
    state: KillSwitchState,
    pnl_pct_nav: float,   # negative = loss; positive = win
    current_nav: float,
) -> KillSwitchState:
    """
    Called after every position close.
    Updates consecutive loss counter and triggers re-evaluation.
    """
    loss_count = (state.session_loss_count + 1) if pnl_pct_nav < 0 else 0
    updated = KillSwitchState(**{**state.__dict__, "session_loss_count": loss_count})
    metrics = compute_drawdown_metrics(
        current_nav, state.session_start_nav, state.hwm_nav, state.rolling_7d_hwm
    )
    return evaluate_kill_switch(
        metrics, updated, loss_count,
        single_trade_loss_pct=abs(pnl_pct_nav) if pnl_pct_nav < 0 else 0.0,
    )
```

---

## Tier 3 / 4 Recovery Protocol

Tier 3 and 4 are not automatic. The following steps are **mandatory**
before any trading resumes:

```
TIER 3 RECOVERY CHECKLIST
────────────────────────────────────────────────────────────────────
□ 72-hour cooling-off period has elapsed
□ Root cause analysis written to logs/postmortem/YYYYMMDD_tier3.md
  Required sections:
    - Trigger conditions (exact metrics at trigger)
    - Market context at trigger (regime, cascade score, funding)
    - Trade-by-trade loss attribution for the session(s) involved
    - Strategy edge re-validation (is win rate/RR still valid?)
    - Parameter changes (if any) before resumption
□ Human operator has set state.human_approved = True in state store
□ Kelly multiplier set to 0.10 for minimum 10 live trades post-resume
□ Maximum concurrent positions reduced to 1 for first 5 sessions
□ Drawdown alert thresholds tightened by 50% for first 20 sessions

TIER 4 RECOVERY CHECKLIST
────────────────────────────────────────────────────────────────────
□ All positions confirmed closed on exchange (manual check)
□ Exchange API errors resolved (if applicable)
□ Full state audit: compare exchange position state vs agent state
□ If API key revoked: new key provisioned with least-privilege scope
□ Postmortem filed (same format as Tier 3 + infrastructure section)
□ Staging environment smoke test passed (paper trading, 5 sessions)
□ Human operator restart: agent process restarted with
  --kill-switch-reset-tier-4 flag; state store updated manually
□ Kelly multiplier: 0.10 for minimum 20 live trades post-resume
```

---

## Threshold Configuration

All thresholds are configurable. Defaults below represent conservative
institutional settings for a single-strategy perps account. Adjust
based on strategy Sharpe ratio, expected volatility, and operational
risk tolerance:

```yaml
# multiclaw/metaclaw/kill_switch_config.yaml

kill_switch:
  tier_1:
    intraday_dd_pct: 3.0           # % drawdown from session-open NAV
    consecutive_losses: 3          # 3 back-to-back losing trades
    kelly_multiplier_post: 0.15
    cooldown: session              # resets next session open

  tier_2:
    consecutive_session_stops: 2   # back-to-back Tier 1 sessions
    rolling_7d_dd_pct: 6.0
    kelly_multiplier_post: 0.10
    cooldown_hours: 24

  tier_3:
    alltime_dd_pct: 10.0           # from HWM (all-time or month-start)
    single_trade_loss_pct: 4.0     # anomalous single trade loss
    kelly_multiplier_post: 0.10
    cooldown_hours: 72
    requires_human_approval: true
    requires_postmortem: true

  tier_4:
    alltime_dd_pct: 15.0
    margin_utilisation_pct: 90.0
    api_error_minutes: 5.0
    cooldown: indefinite
    requires_human_approval: true
    requires_manual_restart: true

  monitoring:
    heartbeat_interval_seconds: 30
    alert_file_path: logs/alerts/
    audit_log_path: logs/audit/kill_switch_events.jsonl
    state_store_path: logs/state/kill_switch_state.json   # persisted across restarts
```

---

## Threshold Calibration Guide

Thresholds must be calibrated to the strategy's statistical properties,
not set arbitrarily. Use these guidelines:

| Tier | Threshold to Calibrate | Calibration Method |
|---|---|---|
| 1 — intraday DD | 3% default | Set to ~1.5× expected daily volatility of strategy P&L. Too tight → constant false fires. Too loose → large intraday swings absorbed before stopping. |
| 1 — consecutive losses | 3 default | Set to point where probability of the streak being random variance < 10%. For 50% WR strategy: 3 losses = p(0.5³) = 12.5%. For 60% WR: 3 losses = p(0.4³) = 6.4%. |
| 2 — rolling 7d DD | 6% default | Approximately 2× the Tier 1 threshold to catch multi-session deterioration. |
| 3 — alltime DD | 10% default | The maximum drawdown beyond which the strategy edge is statistically unlikely to be intact. Compare to backtest max DD. Should be < 2× historical max DD. |
| 4 — margin utilisation | 90% default | Always < 100%; set margin of safety based on typical liquidation price distance. For 5× leverage, 90% margin utilisation is dangerously close to forced liquidation. |

---

## Heartbeat and State Persistence

The kill-switch state must survive agent crashes, restarts, and
network interruptions:

```python
import json, os, time

STATE_PATH = "logs/state/kill_switch_state.json"

def persist_state(state: KillSwitchState) -> None:
    """Write state to disk after every mutation. Atomic write via temp file."""
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump({
            "tier": state.tier.value,
            "trigger_timestamp_utc": state.trigger_timestamp_utc,
            "trigger_reason": state.trigger_reason,
            "session_start_nav": state.session_start_nav,
            "hwm_nav": state.hwm_nav,
            "rolling_7d_hwm": state.rolling_7d_hwm,
            "consecutive_session_stops": state.consecutive_session_stops,
            "kelly_multiplier_override": state.kelly_multiplier_override,
            "human_approval_required": state.human_approval_required,
            "human_approved": state.human_approved,
            "postmortem_filed": state.postmortem_filed,
            "cooldown_hours": state.cooldown_hours,
        }, f, indent=2)
    os.replace(tmp, STATE_PATH)  # atomic on POSIX

def restore_state() -> KillSwitchState:
    """Restore kill-switch state at agent startup. If missing, start fresh."""
    if not os.path.exists(STATE_PATH):
        return KillSwitchState()
    with open(STATE_PATH) as f:
        d = json.load(f)
    state = KillSwitchState(
        tier=KillSwitchTier(d["tier"]),
        trigger_timestamp_utc=d.get("trigger_timestamp_utc"),
        trigger_reason=d.get("trigger_reason", ""),
        session_start_nav=d["session_start_nav"],
        hwm_nav=d["hwm_nav"],
        rolling_7d_hwm=d["rolling_7d_hwm"],
        consecutive_session_stops=d["consecutive_session_stops"],
        kelly_multiplier_override=d["kelly_multiplier_override"],
        human_approval_required=d["human_approval_required"],
        human_approved=d["human_approved"],
        postmortem_filed=d["postmortem_filed"],
        cooldown_hours=d["cooldown_hours"],
    )
    # CRITICAL: on restart with active Tier 3/4, never auto-resume
    if state.tier.value >= 3 and not state.human_approved:
        raise RuntimeError(
            f"Kill-switch Tier {state.tier.value} active from prior session. "
            f"Reason: {state.trigger_reason}. "
            "Human approval required before trading can resume. "
            "Set state.human_approved = True in state store after review."
        )
    return state
```

---

## Audit JSONL Schema

```json
{
  "event": "kill_switch_tier_2_triggered",
  "timestamp_utc": "2026-04-07T22:00:00Z",
  "tier": 2,
  "trigger_reason": "rolling_7d_dd_pct=6.42 >= threshold=6.0",
  "current_nav_usd": 187600,
  "session_start_nav_usd": 191000,
  "hwm_nav_usd": 200000,
  "rolling_7d_hwm_usd": 200000,
  "intraday_dd_pct": 1.78,
  "rolling_7d_dd_pct": 6.42,
  "alltime_dd_pct": 6.20,
  "consecutive_session_stops": 2,
  "open_positions_at_trigger": ["ETH-PERP-long-0.45", "BTC-PERP-short-0.02"],
  "positions_closed_by_trigger": ["ETH-PERP-long-0.45"],
  "kelly_multiplier_override": 0.10,
  "cooldown_hours": 24,
  "human_approval_required": false,
  "resume_eligible_after_utc": "2026-04-08T22:00:00Z"
}
```

---

## Integration with Other Skills

- **`kelly-position-sizing-perps`** (risk/): Call
  `state.effective_kelly_multiplier(base_multiplier)` before every
  sizing computation. Kill-switch override is always the ceiling.
  After Tier 1 fire: reset base Kelly multiplier to 0.25 for next
  session minimum 10 trades before returning to 0.33.
- **`liquidation-cascade-risk`** (regime-detection/): Cascade
  score ≥ 8 (CRITICAL) directly feeds Tier 4 emergency signal.
  Cascade score ≥ 5 should pre-emptively reduce Tier 1 threshold
  from 3% to 2% intraday DD for that session.
- **`slippage-budget-enforcement`** (execution/): Tier 3/4 emergency
  close uses `submit_defensive_exit()` — the pure market mode with
  all budget enforcement suspended. Slippage tracking is still logged
  even when budget is suspended.
- **`max-concurrent-positions`** (risk/): Post-Tier-3 recovery
  protocol reduces max concurrent positions to 1. The concurrent
  position skill must read `state.tier` as input to its own caps.
- **`high-funding-carry-avoidance`** (regime-detection/): Elevated
  funding conditions (funding regime ELEVATED or EXTREME) should
  lower the Tier 1 intraday DD threshold by 1% for that session —
  carry cost is silently eroding NAV even on winning trades.

---

## Quick Decision Tree

```
Every trade cycle — evaluate in order:
│
├── 1. Restore / check kill-switch state
│     state = restore_state()  (on startup)
│     state.trading_permitted()? → No → HALT. Log. Alert.
│
├── 2. Before new position entry:
│     metrics = compute_drawdown_metrics(nav, session_nav, hwm, rolling_7d_hwm)
│     state   = evaluate_kill_switch(metrics, state, consecutive_losses)
│     state.tier != NONE? → HALT. Do not enter position.
│
├── 3. Apply Kelly override:
│     multiplier = state.effective_kelly_multiplier(base_kelly_multiplier)
│     Pass to kelly-position-sizing-perps as kelly_multiplier
│
├── 4. After every position close:
│     state = on_trade_closed(state, pnl_pct_nav, current_nav)
│     persist_state(state)
│
├── 5. If Tier 3 or 4 triggered:
│     → Close all positions via slippage-budget-enforcement defensive exit
│     → Write alert file to logs/alerts/
│     → persist_state(state)
│     → Raise RuntimeError to halt agent process (Tier 4)
│
└── 6. Session open:
      state = on_session_open(state, current_nav)
      persist_state(state)
      Log session baseline NAV and current tier to audit log.
```
