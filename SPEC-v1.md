# SPEC.md — HyperLiquid Autonomous Trading Agent

**Version:** 0.1.0  
**Target Repo:** openclaw/openclaw  
**Deployment:** Kubernetes (ServerDomes edge cluster) via ArgoCD GitOps  
**Language:** Python 3.12 (trading core) + openclaw agent loop (TypeScript wrapper optional)  
**Analogy:** autoresearch `train.py` → `strategy.py` | `program.md` → `trading_program.md`

---

## 1. Architecture Overview

### 1.1 Agent Loop Structure

The agent runs as a single-process event loop with three concurrent async tasks:

```python
# agent/main.py (orchestrator — NOT agent-editable)
async def main():
    async with asyncio.TaskGroup() as tg:
        tg.create_task(market_data_loop())   # WebSocket feed
        tg.create_task(strategy_loop())      # signal generation + order mgmt
        tg.create_task(safety_watchdog())    # kill switch monitor
```

**Rationale:** Separating market data ingestion from strategy execution prevents slow LLM/indicator calls from missing ticks. The safety watchdog runs independently so it cannot be blocked by strategy errors.

### 1.2 HyperLiquid API Integration

Uses [`hyperliquid-python-sdk`](https://github.com/hyperliquid-dex/hyperliquid-python-sdk) exclusively for all exchange interactions.

```python
# agent/exchange.py (locked — no agent modification)
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

info = Info(constants.MAINNET_API_URL, skip_ws=False)
exchange = Exchange(wallet, constants.MAINNET_API_URL)
```

| Interface | Use Case | Rationale |
|---|---|---|
| WebSocket `subscribe` | Real-time trades, L2 book, candles | Sub-100ms latency for entry triggers |
| REST `info.candles_snapshot` | Historical OHLCV for backtest | Rate-limited; used only at startup |
| REST `exchange.order` | Order placement/cancel | Stateless, auditable |
| REST `info.user_state` | Position/margin polling (1 Hz) | Reconciles WS state drift |

### 1.3 WebSocket vs REST

- **WS** for: tick data, order book imbalance signals, fill confirmations  
- **REST** for: order placement, historical candle fetch, position reconciliation  
- WS reconnect logic lives in `exchange.py` (locked); exponential backoff with max 30s cap.

### 1.4 Wallet / Key Management

Secrets flow: Vault/K8s Secret → env var → exchange.py (read-once at init)


- Private key injected as `HL_PRIVATE_KEY` env var via K8s `Secret` (never in repo)
- `exchange.py` reads key **once** at startup into a non-exportable `LocalAccount` object
- No key material ever reaches `strategy.py` or any agent-writable file
- Paper-trade mode uses a separate `HL_PAPER_WALLET` with zero real funds (flag: `TRADE_MODE=paper`)

---

## 2. `strategy.py` — Agent-Editable Module

### 2.1 Contract: What the Agent CAN Modify

```python
# strategy/strategy.py
# ============================================================
# AGENT SANDBOX — agent may freely rewrite this file.
# Interface contract: must export `Strategy` class below.
# ============================================================

from dataclasses import dataclass, field
from typing import Literal
import pandas as pd

@dataclass
class StrategyConfig:
    # --- AGENT-EDITABLE PARAMETERS ---
    # Indicator parameters
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    atr_period: int = 14
    atr_stop_multiplier: float = 2.0

    # Entry/exit logic toggles
    entry_signal: Literal["ema_cross", "rsi_reversal", "breakout", "hybrid"] = "ema_cross"
    exit_signal: Literal["atr_trail", "fixed_tp_sl", "time_exit"] = "atr_trail"
    take_profit_pct: float = 0.03       # 3%
    stop_loss_pct: float = 0.015        # 1.5%

    # Position sizing (fraction of available margin)
    position_size_pct: float = 0.10     # 10% of margin per trade
    max_concurrent_positions: int = 1

    # Order types
    entry_order_type: Literal["limit", "market"] = "limit"
    limit_offset_bps: int = 5           # bps inside spread for limit orders

    # Fee awareness
    fee_tier: float = 0.00035           # taker; agent should prefer maker (0.0001)
    min_edge_bps: int = 10              # skip trade if expected edge < this

class Strategy:
    def __init__(self, config: StrategyConfig):
        self.cfg = config

    def generate_signal(self, candles: pd.DataFrame) -> Literal["long", "short", "flat"]:
        """Core signal logic. Agent rewrites this body."""
        raise NotImplementedError

    def compute_entry_price(self, signal: str, mid: float) -> float:
        """Returns limit price or mid for market orders."""
        raise NotImplementedError

    def compute_position_size(self, equity: float, price: float) -> float:
        """Returns size in base asset. MUST respect HARD_MAX_POSITION_USD."""
        raise NotImplementedError

    def should_exit(self, position: dict, candles: pd.DataFrame) -> bool:
        """Returns True if current position should be closed."""
        raise NotImplementedError
```

### 2.2 What is LOCKED (agent cannot modify)

| File | Why Locked |
|---|---|
| `agent/main.py` | Orchestrator / event loop |
| `agent/exchange.py` | API auth, order execution, rate limiting |
| `agent/safety.py` | Kill switches, drawdown guard |
| `agent/harness.py` | Backtest loop and scoring |
| `trading_program.md` | Human-authored goals (read-only to agent at runtime) |

The agent loop diffs `strategy.py` against the previous version, runs the harness, and only if the score improves does it commit the new file. It **never touches** anything outside `strategy/`.

---

## 3. `trading_program.md` — Human-Authored Goal Document

```markdown
# trading_program.md
<!-- Human-editable. Loaded by agent at start of each iteration. -->

## Mission
Generate consistent risk-adjusted returns on HyperLiquid perpetuals.
Prioritize capital preservation over absolute PnL. Never exceed defined
risk limits regardless of perceived opportunity.

## Markets
- Primary: BTC-PERP (highest liquidity, tightest spreads)
- Secondary: ETH-PERP (permitted after 50 successful BTC iterations)
- Prohibited: any market with <$5M 24h volume or funding rate >0.1%/8h

## Success Metrics
- **Primary:** Annualized Sharpe ratio ≥ 1.5 over backtest window
- **Secondary:** Max drawdown < 8% over backtest window
- **Tertiary:** Win rate ≥ 45%, profit factor ≥ 1.3
- Fee efficiency: avg trade edge > 10 bps after fees

## Risk Parameters (READ-ONLY to agent)
- Max position size: $500 notional (paper) / $2,000 notional (live, phase 1)
- Max concurrent positions: 1
- Daily loss limit: 2% of account equity → triggers trading halt
- Max drawdown kill switch: 8% peak-to-trough → stops all activity

## Iteration Constraints
- Do not change more than 3 `StrategyConfig` parameters per iteration
- Prefer maker orders (limit) to reduce fee drag
- Each experiment must complete backtest in < 5 minutes wall-clock
- Log rationale for each parameter change in experiment record

## Fee Awareness
HyperLiquid fees: maker ~0.01%, taker ~0.035%.
Referral discount applied. Always compute expected edge after fees
before placing an order. Minimum viable edge: 10 bps.

## Funding Rate Awareness
Check 8h funding rate before entering. Avoid holding positions when
funding rate disadvantages your direction by > 0.05%/8h.
```

---

## 4. Evaluation Harness

### 4.1 Backtest Loop

```python
# agent/harness.py (locked)
import sqlite3, json, time
from pathlib import Path
from strategy.strategy import Strategy, StrategyConfig

BACKTEST_DAYS = 30        # rolling window
CANDLE_INTERVAL = "15m"
SCORE_THRESHOLD = 1.5     # min Sharpe to keep strategy

def run_backtest(strategy: Strategy, candles: pd.DataFrame) -> dict:
    equity = [10_000.0]
    trades = []
    position = None

    for i in range(100, len(candles)):
        window = candles.iloc[i-100:i]
        mid = candles.iloc[i]["close"]

        if position is None:
            signal = strategy.generate_signal(window)
            if signal in ("long", "short"):
                size = strategy.compute_position_size(equity[-1], mid)
                price = strategy.compute_entry_price(signal, mid)
                fee = price * size * strategy.cfg.fee_tier
                position = {"signal": signal, "entry": price, "size": size,
                            "fee_in": fee, "open_bar": i}
        else:
            if strategy.should_exit(position, window):
                exit_price = mid
                fee_out = exit_price * position["size"] * strategy.cfg.fee_tier
                pnl = (exit_price - position["entry"]) * position["size"]
                if position["signal"] == "short":
                    pnl *= -1
                pnl -= (position["fee_in"] + fee_out)
                equity.append(equity[-1] + pnl)
                trades.append({"pnl": pnl, "bars": i - position["open_bar"]})
                position = None

    return score(equity, trades)

def score(equity: list, trades: list) -> dict:
    import numpy as np
    returns = np.diff(equity) / equity[:-1]
    sharpe = (returns.mean() / (returns.std() + 1e-9)) * np.sqrt(365 * 96)  # 15m bars/year
    drawdown = max_drawdown(equity)
    win_rate = sum(1 for t in trades if t["pnl"] > 0) / max(len(trades), 1)
    profit_factor = (sum(t["pnl"] for t in trades if t["pnl"] > 0) /
                     max(abs(sum(t["pnl"] for t in trades if t["pnl"] < 0)), 1e-9))
    return {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(drawdown, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "n_trades": len(trades),
        "final_equity": round(equity[-1], 2),
    }
```

### 4.2 Experiment Logging

```python
# SQLite schema (created by harness.py on first run)
CREATE TABLE experiments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,          -- git short SHA of strategy.py
    timestamp   INTEGER NOT NULL,
    config_json TEXT NOT NULL,          -- StrategyConfig as JSON
    score_json  TEXT NOT NULL,          -- score() output as JSON
    sharpe      REAL,
    max_dd      REAL,
    kept        INTEGER DEFAULT 0,      -- 1 = accepted, promoted to paper trade
    rationale   TEXT                    -- agent's reasoning for this iteration
);
```

Also emits a JSONL sidecar at `logs/experiments.jsonl` for streaming dashboards.

### 4.3 Keep / Discard Decision

```python
def should_keep(new_score: dict, best_score: dict | None) -> bool:
    if new_score["max_drawdown"] > 0.08:
        return False   # hard constraint
    if new_score["n_trades"] < 10:
        return False   # insufficient sample
    if best_score is None:
        return new_score["sharpe"] > SCORE_THRESHOLD
    return (new_score["sharpe"] > best_score["sharpe"] and
            new_score["max_drawdown"] <= best_score["max_drawdown"] * 1.1)
```

---

## 5. Safety Layer

### 5.1 Kill Switches

```python
# agent/safety.py (locked)
class SafetyGuard:
    HARD_MAX_POSITION_USD = 500       # paper | overridden by env for live
    DAILY_LOSS_LIMIT_PCT  = 0.02
    MAX_DRAWDOWN_PCT       = 0.08
    API_RATE_LIMIT_RPS     = 5        # HL public limit; we self-limit to 3

    def __init__(self):
        self._halted = False
        self._peak_equity = None
        self._day_start_equity = None

    def check(self, current_equity: float) -> None:
        """Raises TradingHalt if any limit breached."""
        if self._peak_equity is None:
            self._peak_equity = current_equity
        self._peak_equity = max(self._peak_equity, current_equity)
        drawdown = (self._peak_equity - current_equity) / self._peak_equity
        daily_loss = (self._day_start_equity - current_equity) / self._day_start_equity

        if drawdown >= self.MAX_DRAWDOWN_PCT:
            self._halt(f"Max drawdown {drawdown:.1%} breached")
        if daily_loss >= self.DAILY_LOSS_LIMIT_PCT:
            self._halt(f"Daily loss {daily_loss:.1%} breached")

    def validate_order(self, size_usd: float) -> None:
        if size_usd > self.HARD_MAX_POSITION_USD:
            raise OrderRejected(f"Size ${size_usd} > hard max ${self.HARD_MAX_POSITION_USD}")

    def _halt(self, reason: str):
        self._halted = True
        # Cancel all open orders via exchange.py
        # Emit alert to K8s event log
        raise TradingHalt(reason)
```

### 5.2 Rate Limiting

```python
# Token bucket in exchange.py — 3 req/s, burst 5
from asyncio import Semaphore
_rate_sem = Semaphore(5)

async def throttled_request(coro):
    async with _rate_sem:
        result = await coro
        await asyncio.sleep(0.33)  # enforce 3 rps avg
        return result
```

### 5.3 Paper vs Live Toggle

TRADE_MODE=paper → all orders logged to DB, no real exchange.order() calls
TRADE_MODE=live → real orders; requires TRADE_MODE_CONFIRM=yes env validate_order

ArgoCD ApplicationSets default to `paper`. Live requires manual patch to K8s Secret.

---

## 6. Deployment — Docker + Kubernetes + ArgoCD

### 6.1 Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent/ ./agent/
COPY strategy/ ./strategy/
COPY trading_program.md .
# strategy.py is mounted via ConfigMap or git-sync sidecar
CMD ["python", "-m", "agent.main"]
```

### 6.2 Kubernetes Manifests (`k8s/`)

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hl-trader
  namespace: trading
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: trader
        image: ghcr.io/openclaw/hl-trader:latest
        env:
        - name: TRADE_MODE
          value: "paper"
        - name: HL_PRIVATE_KEY
          valueFrom:
            secretKeyRef:
              name: hl-wallet
              key: private_key
        volumeMounts:
        - name: strategy-vol
          mountPath: /app/strategy
      volumes:
      - name: strategy-vol
        configMap:
          name: current-strategy    # updated by ArgoCD on each accepted commit
```

### 6.3 ArgoCD GitOps Flow

Agent accepts strategy → git commit strategy/strategy.py → push to branch
→ ArgoCD detects diff → applies new ConfigMap → rolling restart of paper-eval Pod
→ paper-eval Pod runs N-hour live paper trade → metrics logged → human reviews


Each accepted strategy gets a git tag: `strategy/v{experiment_id}` for full rollback capability.

---

## 7. Iteration Loop Pseudocode

```python
# agent/iteration_loop.py  — the overnight ~100-experiment engine

async def overnight_loop(
    max_iterations: int = 100,
    paper_eval_hours: float = 4.0,
    backtest_budget_minutes: float = 5.0,
):
    program = load_trading_program("trading_program.md")
    candles  = await fetch_historical_candles(days=30, interval="15m")
    best     = db.get_best_experiment()

    for i in range(max_iterations):
        # 1. PROPOSE — LLM generates a new StrategyConfig + strategy.py body
        proposal = await agent.propose_strategy(
            program=program,
            current_best=best,
            experiment_history=db.last_n(20),
            constraints="max 3 param changes, prefer maker orders"
        )

        # 2. VALIDATE — syntax + interface check (no exec of untrusted code paths)
        if not validate_strategy_module(proposal.code):
            db.log(proposal, kept=False, rationale="syntax/interface error")
            continue

        # 3. BACKTEST — timed, killed if over budget
        try:
            score = await asyncio.wait_for(
                run_backtest(proposal.strategy, candles),
                timeout=backtest_budget_minutes * 60
            )
        except asyncio.TimeoutError:
            db.log(proposal, kept=False, rationale="backtest timeout")
            continue

        # 4. SCORE — keep/discard
        kept = should_keep(score, best["score"] if best else None)
        db.log(proposal, score=score, kept=kept, rationale=proposal.rationale)

        if kept:
            best = {"config": proposal.config, "score": score}
            git_commit_strategy(proposal.code, tag=f"strategy/v{i}")
            # ArgoCD picks up commit → deploys paper-eval pod automatically
            await notify_slack(f"✅ New strategy accepted | Sharpe={score['sharpe']}")

        # 5. SLEEP — brief pause between iterations (respect API limits)
        await asyncio.sleep(2)

    # End of loop — emit final report
    generate_experiment_report(db.all_experiments())
```

---

## 8. Repository Layout

openclaw/
├── SPEC.md ← this file
├── trading_program.md ← human-authored goals (locked at runtime)
├── strategy/
│ └── strategy.py ← AGENT-EDITABLE; interface-locked
├── agent/
│ ├── main.py ← orchestrator (locked)
│ ├── exchange.py ← HL SDK wrapper, auth, rate limit (locked)
│ ├── safety.py ← kill switches, position guards (locked)
│ ├── harness.py ← backtest loop + scoring (locked)
│ └── iteration_loop.py ← overnight agent driver (locked)
├── logs/
│ ├── experiments.db ← SQLite (gitignored)
│ └── experiments.jsonl ← JSONL sidecar (gitignored)
├── k8s/
│ ├── deployment.yaml
│ ├── configmap-strategy.yaml ← updated by ArgoCD on each accepted commit
│ └── secret-template.yaml ← sealed secret template (no real keys)
├── Dockerfile
└── requirements.txt
# hyperliquid-sdk, pandas, numpy, python-dotenv, aiohttp, sqlalchemy


---

## 9. Design Decisions — Rationale

| Decision | Rationale |
|---|---|
| Python core, not TypeScript | `hyperliquid-python-sdk` is the canonical SDK; pandas/numpy for backtest |
| Single `strategy.py` file | Mirrors autoresearch's `train.py` — minimal diff surface, easy git audit |
| SQLite for experiment log | Zero infra overhead, queryable, portable across pods |
| WS for ticks, REST for orders | HL WS delivers fills <100ms; REST order placement is idempotent/auditable |
| `asyncio.wait_for` budget | Prevents runaway backtests from blocking overnight iteration count |
| ConfigMap for strategy | ArgoCD can diff/rollback any strategy version without rebuilding image |
| `TRADE_MODE=paper` default | Operator must explicitly opt into live; avoids accidental real trades |
| Max 3 param changes/iter | Prevents the agent from over-fitting by changing everything at once |
| Sharpe over raw PnL | Sharpe penalizes volatility; more stable signal for overnight unattended runs |
