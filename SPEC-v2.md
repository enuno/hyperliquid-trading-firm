# SPEC.md — HyperLiquid Autonomous Trading Agent v2
# Evolving Strategy Loop + Dual-Bot Architecture + Profit Vault

**Version:** 0.2.0  
**Supersedes:** SPEC.md v0.1.0  
**New in v2:** autoresearch refinement loop, paper↔live co-evolution,
               profit vault, drawdown recovery mode

---

## 1. System Architecture Overview

```

┌─────────────────────────────────────────────────────────────────┐
│                     OVERNIGHT AGENT LOOP                        │
│  autoresearch-style: ~100 experiments × 5min backtest budget    │
│                                                                 │
│  ┌──────────────┐    propose     ┌──────────────────────────┐   │
│  │  LLM Agent   │ ─────────────► │  strategy.py (sandbox)   │   │
│  │  (iteration  │ ◄───────────── │  backtest score          │   │
│  │   loop)      │    score       └──────────────────────────┘   │
│  └──────┬───────┘                                               │
│         │ accepted (Sharpe ≥ threshold)                         │
└─────────┼───────────────────────────────────────────────────────┘
          │ git commit + ArgoCD deploy
          ▼
┌─────────────────────────────────────┐
│         PAPER BOT (always on)       │  ← real-time reinforcement data
│  strategy_paper.py                  │    every trade logged to RL buffer
│  HyperLiquid paper wallet           │
└──────────────┬──────────────────────┘
               │ reinforcement signal (win/loss/edge deltas)
               │ fed back into next autoresearch iteration
               ▼
┌─────────────────────────────────────┐
│         LIVE BOT (guarded)          │
│  strategy_live.py ← promoted from   │
│  paper only when paper Sharpe≥1.5   │
│  AND paper win_rate≥45% over 48h    │
│                                     │
│  ┌─────────────────────────────┐    │
│  │  PROFIT VAULT               │    │
│  │  10–20% of each trade PnL   │    │
│  │  sent to vault wallet addr  │    │
│  └─────────────────────────────┘    │
│                                     │
│  DRAWDOWN GUARD: if equity drops    │
│  to 50% of start → CEASE TRADING    │
│  → trigger Recovery Mode            │
└─────────────────────────────────────┘

```

---

## 2. Three-Tier Strategy Lifecycle

Strategies flow through three tiers. Promotion is one-way unless recovery mode triggers a demotion.

```

BACKTEST (offline, historical OHLCV)
↓  Sharpe ≥ 1.5 AND max_dd < 8% AND n_trades ≥ 10
PAPER TRADE (live market, simulated fills, 48h minimum window)
↓  paper Sharpe ≥ 1.5 AND win_rate ≥ 45% over 48h real-time
LIVE TRADE (real funds, vault active, drawdown guards armed)
↓  if equity ≤ 50% of session_start_equity
RECOVERY MODE (live halted → accelerated autoresearch + paper revalidation)

```

---

## 3. `strategy.py` — Dual-File Architecture

The agent manages **two** strategy files. `strategy_paper.py` is the active experiment target. `strategy_live.py` is only written when paper promotion criteria are met.

```

strategy/
├── strategy_paper.py     ← agent-editable; promoted to live on criteria
├── strategy_live.py      ← written by promotion logic only (not agent-direct)
├── strategy_base.py      ← abstract interface (locked)
└── strategy_vault.py     ← vault transfer logic (locked)

```

### 3.1 Shared Interface (`strategy_base.py`, locked)

```python
# strategy/strategy_base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal
import pandas as pd

@dataclass
class StrategyConfig:
    # Indicator params — agent editable
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    atr_period: int = 14
    atr_stop_multiplier: float = 2.0
    bb_period: int = 20
    bb_std: float = 2.0
    vwap_enabled: bool = False

    # Signal logic — agent editable
    entry_signal: Literal[
        "ema_cross", "rsi_reversal", "breakout",
        "bb_squeeze", "vwap_reversion", "hybrid"
    ] = "ema_cross"
    exit_signal: Literal[
        "atr_trail", "fixed_tp_sl", "time_exit", "signal_flip"
    ] = "atr_trail"
    take_profit_pct: float = 0.03
    stop_loss_pct: float = 0.015

    # Sizing — agent editable (capped by safety layer)
    position_size_pct: float = 0.10
    max_concurrent_positions: int = 1

    # Order type — agent editable
    entry_order_type: Literal["limit", "market"] = "limit"
    limit_offset_bps: int = 5
    min_edge_bps: int = 10

    # Vault config — agent MAY adjust rate, vault address is LOCKED
    vault_take_pct: float = 0.10        # 10–20%; clamped by safety layer


class BaseStrategy(ABC):
    def __init__(self, config: StrategyConfig):
        self.cfg = config

    @abstractmethod
    def generate_signal(self, candles: pd.DataFrame) -> Literal["long", "short", "flat"]: ...

    @abstractmethod
    def compute_entry_price(self, signal: str, mid: float) -> float: ...

    @abstractmethod
    def compute_position_size(self, equity: float, price: float) -> float: ...

    @abstractmethod
    def should_exit(self, position: dict, candles: pd.DataFrame) -> bool: ...
```


---

## 4. Autoresearch Feedback Loop

The key addition over v0.1: paper-trade outcomes feed directly back into each new autoresearch proposal as **reinforcement context**. The LLM agent sees recent paper trade results, not just backtest scores.

### 4.1 Reinforcement Buffer

```python
# agent/rl_buffer.py (locked)
import sqlite3
from dataclasses import dataclass

@dataclass
class PaperTradeOutcome:
    strategy_run_id: str
    symbol: str
    signal: str            # long / short
    entry_price: float
    exit_price: float
    pnl_usd: float
    pnl_pct: float
    hold_bars: int
    entry_signal_features: dict   # snapshot of indicators at entry
    exit_reason: str       # atr_trail | tp | sl | signal_flip | time_exit
    funding_paid: float
    fee_paid: float
    timestamp: int

# Schema addition to experiments.db:
# CREATE TABLE paper_outcomes (... as above ...);
# CREATE TABLE rl_aggregates (
#     run_id TEXT,
#     window_hours REAL,
#     sharpe REAL,
#     win_rate REAL,
#     avg_edge_bps REAL,
#     worst_trade_pct REAL,
#     funding_drag REAL,
#     meets_promotion_criteria INTEGER
# );
```


### 4.2 Agent Proposal Context Injection

```python
# agent/iteration_loop.py — proposal call with reinforcement context
async def build_proposal_context(db) -> dict:
    return {
        "program": load_trading_program("trading_program.md"),
        "backtest_history": db.last_n_experiments(20),
        "paper_rl_window": db.get_rl_aggregates(hours=48),
        "paper_recent_trades": db.get_paper_outcomes(limit=50),
        "current_live_config": load_live_config(),
        "market_conditions": await get_market_snapshot(),  # funding, vol regime
        "recovery_mode": get_recovery_state(),
    }
```

The LLM agent receives the last 50 paper trade outcomes annotated with indicator snapshots, letting it identify which signal configurations are producing alpha in current market conditions — equivalent to autoresearch reading `val_bpb` history to guide the next hypothesis.

---

## 5. Paper Bot — Continuous Real-Time Reinforcement

The paper bot runs **continuously** (not just during evaluation windows). It shadows live market prices 24/7, logging every simulated trade to the RL buffer.

```python
# agent/paper_bot.py (locked orchestration, strategy_paper.py is editable)
class PaperBot:
    """
    Runs the current strategy_paper.py against live HyperLiquid ticks.
    No real orders placed. All fills simulated at mid ± half-spread.
    Outcomes written to rl_buffer every closed trade.
    """
    async def run(self):
        async for tick in hl_ws.subscribe_trades(symbol):
            signal = self.strategy.generate_signal(self.candle_buffer)
            if signal != "flat" and self.position is None:
                self._open_simulated_position(signal, tick.price)
            elif self.position and self.strategy.should_exit(
                    self.position, self.candle_buffer):
                outcome = self._close_simulated_position(tick.price)
                await rl_buffer.write(outcome)
                await self._check_promotion_criteria()

    async def _check_promotion_criteria(self):
        agg = await rl_buffer.get_aggregates(hours=48)
        if (agg.sharpe >= 1.5
                and agg.win_rate >= 0.45
                and agg.meets_minimum_trades(n=30)
                and not recovery_state.active):
            await promote_to_live(self.strategy)
```


---

## 6. Live Bot — Guarded Real-Fund Execution

### 6.1 Session State

```python
# agent/live_bot.py (locked)
@dataclass
class LiveSession:
    session_id: str
    session_start_equity: float     # set at bot start, never updated
    current_equity: float
    peak_equity: float
    vault_balance: float            # accumulated in separate HL sub-account
    total_profit_realized: float
    halt_reason: str | None = None

    @property
    def recovery_threshold(self) -> float:
        return self.session_start_equity * 0.50   # 50% floor

    @property
    def in_recovery(self) -> bool:
        return self.current_equity <= self.recovery_threshold
```


### 6.2 Trade Execution with Vault Deduction

```python
async def close_position_and_vault(position: dict, exit_price: float,
                                    session: LiveSession):
    raw_pnl = compute_pnl(position, exit_price)
    fee = compute_fees(position, exit_price)
    net_pnl = raw_pnl - fee

    if net_pnl > 0:
        vault_amt = net_pnl * clamp(session.vault_take_pct, 0.10, 0.20)
        trading_amt = net_pnl - vault_amt

        # Transfer vault_amt to vault sub-account via HL transfer API
        await exchange.transfer_to_vault(vault_amt, VAULT_SUBACCOUNT_ADDRESS)
        session.vault_balance += vault_amt
        session.current_equity += trading_amt
    else:
        # Losses come entirely from trading capital; vault never clawed back
        session.current_equity += net_pnl

    session.peak_equity = max(session.peak_equity, session.current_equity)
    db.log_live_trade(position, exit_price, net_pnl, vault_amt)

    # Drawdown check after every closed trade
    safety.check_recovery_threshold(session)
```


### 6.3 Vault Rules (locked, human-configurable)

| Rule | Value | Notes |
| :-- | :-- | :-- |
| Vault take rate | 10–20% | Agent may set within range; default 10% |
| Vault take condition | Profitable trades only | Losses never touch vault |
| Vault address | `VAULT_SUBACCOUNT_ADDRESS` env var | Locked; never agent-writable |
| Vault withdrawal | Manual only | No automated withdrawal logic |
| Vault floor protection | Vault balance never re-deployed to trading | One-way transfer |


---

## 7. Recovery Mode

Recovery mode activates when `session.current_equity ≤ session_start_equity × 0.50`.

### 7.1 Trigger Sequence

```python
# agent/safety.py
def check_recovery_threshold(session: LiveSession):
    if session.in_recovery and not recovery_state.active:
        # 1. Cancel all open live orders
        await exchange.cancel_all_orders()
        # 2. Close all open positions at market
        await exchange.close_all_positions()
        # 3. Engage recovery mode
        recovery_state.activate(reason="equity_floor",
                                floor_equity=session.current_equity)
        # 4. Emit alert
        await alert.send(
            f"🔴 LIVE TRADING HALTED — equity at "
            f"{session.current_equity:.2f} "
            f"({session.current_equity/session.session_start_equity:.0%} of start). "
            f"Recovery mode engaged."
        )
```


### 7.2 Recovery Mode Behavior

```python
@dataclass
class RecoveryState:
    active: bool = False
    activated_at: int = 0
    floor_equity: float = 0.0
    recovery_target_sharpe: float = 2.0   # higher bar than normal 1.5
    min_paper_hours: float = 72.0         # 3 days minimum paper revalidation
    iterations_completed: int = 0
    deactivation_criteria_met: bool = False
```

While in recovery:

1. **Live bot**: completely halted, no orders
2. **Autoresearch loop**: runs at double iteration rate (overnight: 200 experiments)
3. **Paper bot**: continues 24/7, feeds RL buffer
4. **Promotion bar raised**: Sharpe ≥ 2.0 (vs normal 1.5), 72h paper window (vs 48h), win_rate ≥ 50% (vs 45%)
5. **Recovery exit**: all three raised criteria met → live bot resumes with new strategy, `session_start_equity` reset to current equity level

### 7.3 Recovery Loop Pseudocode

```python
async def recovery_loop(session: LiveSession, recovery: RecoveryState):
    """Runs instead of normal overnight loop while recovery is active."""
    log.warning(f"RECOVERY MODE — floor: ${recovery.floor_equity:.2f}")

    while recovery.active:
        # Run accelerated autoresearch (200 iterations / night)
        await overnight_loop(
            max_iterations=200,
            backtest_budget_minutes=5.0,
            score_threshold=recovery.recovery_target_sharpe,
        )

        # Check if paper bot has accumulated enough real-time evidence
        agg = await rl_buffer.get_aggregates(
            hours=recovery.min_paper_hours,
            since=recovery.activated_at
        )

        if (agg.sharpe >= recovery.recovery_target_sharpe
                and agg.win_rate >= 0.50
                and agg.n_trades >= 50
                and hours_elapsed(recovery.activated_at) >= recovery.min_paper_hours):

            recovery.deactivation_criteria_met = True
            await promote_to_live(paper_bot.strategy)

            # Reset session baseline to current equity
            session.session_start_equity = session.current_equity
            session.peak_equity = session.current_equity
            recovery.active = False

            await alert.send(
                "🟢 RECOVERY COMPLETE — live trading resuming. "
                f"New session baseline: ${session.current_equity:.2f}"
            )
        else:
            log.info(f"Recovery criteria not met yet: {agg}. Continuing...")
            await asyncio.sleep(3600)   # check hourly
```


---

## 8. Evolved Iteration Loop

```python
async def overnight_loop(
    max_iterations: int = 100,
    paper_eval_hours: float = 48.0,   # paper bot runs continuously; no blocking wait
    backtest_budget_minutes: float = 5.0,
    score_threshold: float = 1.5,
):
    for i in range(max_iterations):

        # 1. BUILD CONTEXT — backtest history + live paper RL signal
        ctx = await build_proposal_context(db)

        # 2. PROPOSE — LLM generates StrategyConfig + strategy body
        proposal = await agent.propose_strategy(
            context=ctx,
            constraints=[
                "max 3 StrategyConfig param changes from current paper config",
                "prefer limit orders",
                "account for current funding rate regime",
                "justify each change referencing recent paper trade outcomes",
            ]
        )

        # 3. VALIDATE
        if not validate_strategy_module(proposal.code):
            db.log(proposal, kept=False, rationale="validation_fail")
            continue

        # 4. BACKTEST (5min budget)
        try:
            score = await asyncio.wait_for(
                run_backtest(proposal.strategy, candles),
                timeout=backtest_budget_minutes * 60
            )
        except asyncio.TimeoutError:
            db.log(proposal, kept=False, rationale="timeout")
            continue

        # 5. SCORE vs THRESHOLD
        if not should_keep(score, db.get_best_score()):
            db.log(proposal, score=score, kept=False)
            continue

        # 6. ACCEPT — deploy to paper bot (ArgoCD picks up commit)
        db.log(proposal, score=score, kept=True)
        git_commit_strategy(
            proposal.code,
            path="strategy/strategy_paper.py",
            tag=f"paper/v{i}",
            message=proposal.rationale
        )
        # Paper bot picks up new strategy_paper.py via ConfigMap update
        # Paper bot RL buffer continues accumulating real-time outcomes
        # Promotion to live happens asynchronously when paper criteria met

        # 7. PAPER→LIVE PROMOTION CHECK (non-blocking)
        # Handled continuously by paper_bot._check_promotion_criteria()

        await asyncio.sleep(2)
```


---

## 9. Updated Repository Layout

```
openclaw/
├── SPEC.md
├── trading_program.md
├── strategy/
│   ├── strategy_base.py          ← locked interface
│   ├── strategy_paper.py         ← AGENT-EDITABLE (paper bot target)
│   ├── strategy_live.py          ← written by promotion logic only
│   └── strategy_vault.py         ← vault pct config (locked addr, editable rate)
├── agent/
│   ├── main.py                   ← orchestrator
│   ├── exchange.py               ← HL SDK, auth, rate limit (locked)
│   ├── safety.py                 ← kill switches, recovery trigger (locked)
│   ├── harness.py                ← backtest + scoring (locked)
│   ├── iteration_loop.py         ← autoresearch engine (locked)
│   ├── paper_bot.py              ← continuous paper trader (locked)
│   ├── live_bot.py               ← live trader with vault (locked)
│   ├── rl_buffer.py              ← reinforcement data store (locked)
│   └── recovery.py               ← recovery mode state machine (locked)
├── logs/
│   ├── experiments.db            ← SQLite: experiments + paper_outcomes + rl_aggregates
│   └── experiments.jsonl
├── k8s/
│   ├── deployment-paper.yaml
│   ├── deployment-live.yaml      ← separate pod; TRADE_MODE=live
│   ├── deployment-agent.yaml     ← overnight iteration loop pod
│   ├── configmap-strategy.yaml
│   └── secret-template.yaml      ← HL_PRIVATE_KEY + VAULT_SUBACCOUNT_ADDRESS
└── Dockerfile
```


---

## 10. Vault Architecture on HyperLiquid

HyperLiquid supports sub-accounts and vault-style smart contracts. The recommended implementation:

```
Main trading account  ──profit share──►  HL Vault sub-account (VAULT_SUBACCOUNT_ADDRESS)
                                          - Read-only from bot perspective
                                          - Withdrawals: manual only, via HL UI or separate cold-wallet script
                                          - Never re-deployed to trading without manual intervention
```

`VAULT_SUBACCOUNT_ADDRESS` is set as a K8s Secret and injected into `live_bot.py`. The agent has **no write path** to this variable. The vault transfer uses `exchange.spot_transfer()` or the HL vault deposit API depending on account type.

---

## 11. Updated `trading_program.md` Addendum

```markdown
## Dual-Bot Behavior (v2 additions)

### Paper Bot
- Runs continuously 24/7 on BTC-PERP
- Always reflects the most recently accepted strategy_paper.py
- Real-time outcomes feed autoresearch proposals as reinforcement context
- 48-hour rolling Sharpe + win_rate gate before promoting to live

### Live Bot
- Only runs a strategy proven by ≥48h paper validation
- Takes 10% of each profitable trade and transfers to vault sub-account
- If equity drops to 50% of session start: halt, enter recovery mode
- Recovery requires 72h paper revalidation at Sharpe ≥ 2.0

### Profit Vault
- Vault take rate: 10% default; agent may adjust to max 20% via StrategyConfig
- Vault address: set by human operator in K8s secret; never agent-writable
- Vault funds are never automatically re-deployed to trading
- Target: accumulate vault balance equivalent to 1× session_start_equity
  before any human-reviewed withdrawal

### Iteration Velocity Goals
- Normal operation: ~100 backtest experiments overnight
- Recovery mode: ~200 experiments overnight
- Paper bot: continuous (no iteration budget; always running)
- Live strategy update frequency: max once per 48h (paper gate enforces this)
```


---

## 12. Design Decisions — v2 Rationale

| Decision | Rationale |
| :-- | :-- |
| Paper bot runs 24/7 (not just eval windows) | Real-time market regime data is more valuable than offline backtest; fills the autoresearch context with live signal |
| 48h paper gate before live promotion | Prevents a backtest-overfit strategy from trading real funds; 48h spans multiple market sessions and funding cycles |
| Vault deducted from profits only | Losses are never "taxed"; vault grows monotonically, building a permanent safety reserve |
| 50% equity floor for live halt | Aggressive but explicit; at 50% loss the strategy is demonstrably failing; continuing would risk total loss |
| Raised recovery bar (Sharpe 2.0, 72h) | Recovery should produce a *better* strategy than what failed, not just a marginally passing one |
| `session_start_equity` resets on recovery exit | Prevents a perpetual "almost 50% down" trap after recovery; new baseline reflects real current capital |
| Agent cannot write `strategy_live.py` directly | Prevents the agent from bypassing the paper gate; only promotion logic can overwrite live strategy |
| Vault address in K8s Secret | Eliminates any code path where a compromised agent could reroute vault funds |

## 13. Research Dashboard

The system includes a web dashboard for strategy research, paper trading visibility, and live trading oversight.

### 13.1 Dashboard Goals
- Show the last year of 1-minute market data used for research and backtests.
- Show paper trading P/L, live trading P/L, current balances, and reserved profit balance.
- Show experiment history, accepted/rejected strategies, drawdown events, and promotion events.
- Show current mode: backtest, paper, live, or recovery.

### 13.2 Data Sources
- Historical candles: HyperLiquid `candleSnapshot` API for 1-minute candles, stitched into a local time-series store because upstream snapshots are limited per request.
- Live candles: HyperLiquid WebSocket `candle` stream for 1-minute incremental updates.
- Account state: HyperLiquid account/clearinghouse state and user fills for balance and P/L calculations.
- Experiment data: SQLite experiments database and JSONL log stream.

### 13.3 UI Sections
- Market Research.
- Paper Trading Performance.
- Live Trading Performance.
- Vault / Reserved Profit Balance.
- Strategy Experiments.
- Risk and Halt Status.

### 13.4 Market Research View
The dashboard plots the last 365 days of 1-minute candles for selected markets, plus overlays for strategy entry/exit markers and regime annotations.

### 13.5 P/L View
The dashboard shows:
- Cumulative P/L.
- Daily P/L.
- Rolling Sharpe ratio.
- Max drawdown.
- Win rate.
- Fees paid.
- Funding paid or received.
- Reserved profit sent to vault.

### 13.6 Implementation
- Backend: FastAPI or similar lightweight Python service.
- Frontend: React or Next.js.
- Storage: SQLite for metadata, Parquet or DuckDB for candle history and trades.
- Auth: SSO or reverse-proxy auth; dashboard must not expose secrets or raw API keys.

