# SPEC.md — HyperLiquid Autonomous Trading Firm

**Version:** 0.3.0  
**Supersedes:** SPEC-v1.md (v0.1.0), SPEC-v2.md (v0.2.0)  
**Deployment:** Kubernetes (ServerDomes edge cluster) via ArgoCD GitOps  
**Languages:** Python 3.11+ (agents, strategies, executors) · TypeScript 5.x (orchestrator API, SAE engine) · React/Next.js (dashboard)  
**Status:** Experimental research software — not audited for large-capital use  
**Analogy:** autoresearch `train.py` → `strategy_paper.py` | `program.md` → `trading_program.md`

---

## 1. System Architecture Overview

### 1.1 Service Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                  OpenClaw Controller  (optional external)           │
│     Triggers decision cycles · Adjusts SAE policies · Reads traces  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  REST / WebSocket
┌──────────────────────────────▼──────────────────────────────────────┐
│              apps/orchestrator-api  (Node/TypeScript)               │
│  Decision cycle:                                                     │
│    Analysts → Research Debate → Trader → Risk Council →             │
│    Fund Manager → SAE Engine → Executor                             │
└───────┬────────────────────────────────────────────┬────────────────┘
        │ internal RPC                               │ validated plan
┌───────▼──────────────────────────┐   ┌────────────▼────────────────┐
│   apps/agents  (Python)          │   │  apps/sae-engine  (TS)      │
│  ┌──────────────────────────┐    │   │  Leverage / size / dd caps  │
│  │  IntelliClaw client      │    │   │  Staged execution plans     │
│  │  get_intel_snapshot()    │    │   │  TWAP / VWAP / POV / Ice    │
│  │  search_events()         │    │   │  Non-bypassable guardrail   │
│  │  iter_alert_stream()     │    │   └────────────┬────────────────┘
│  └──────────────────────────┘    │                │ execution plan
│  Analysts · Researchers          │   ┌────────────▼────────────────┐
│  Trader · Risk Council           │   │  apps/executors  (Python)   │
│  Fund Manager                    │   │  HyperLiquid perps          │
└──────────────────────────────────┘   │  Hummingbot MM/arb          │
                                       │  DEX gateway                │
┌──────────────────────────────────────┴─────────────────────────────┐
│        Autoresearch Loop  (apps/jobs)                               │
│  Paper Bot (24/7) → RL Buffer → Overnight Loop (~100 iter) →       │
│  Backtest Score → Git Commit → ArgoCD → Paper Bot → Live Promotion  │
└────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────┐
│  multiclaw/mlflow  — experiment tracking for all ML/RL/OPRO jobs    │
│  MLflow + Postgres + MinIO  (MLFLOW_TRACKING_URI env var)           │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 Multi-Agent Firm Structure

Each decision cycle runs in strict sequence:

1. **Analyst Agents** — Market, News, Fundamental, On-chain, Sentiment  
   Each analyst calls the IntelliClaw client, builds a typed `AnalystReport`,  
   and returns it to the orchestrator.
2. **Research Debate** — Bullish Researcher vs. Bearish Researcher; Facilitator  
   synthesises the bull/bear case into a structured `ResearchSummary`.
3. **Trader Agent** — Consumes all reports, selects a `BaseStrategy` plugin  
   and proposes a `TradeDecision` (asset, direction, size, entry type).
4. **Risk Council** — Three profiles (aggressive / neutral / conservative) vote  
   independently. Majority or unanimous veto required depending on config.
5. **Fund Manager** — Applies portfolio-level constraints (concentration, corr,  
   daily loss limit) and produces an approved `TradeOrder`.
6. **SAE Engine** — Non-bypassable guardrail. Validates leverage, size, drawdown  
   policies; builds a staged execution plan with algo hints.
7. **Executor** — Venue adapter places real orders via the HL SDK, Hummingbot,  
   or DEX gateway.

> **Rule:** Agents must never call executors directly. All trades MUST pass
> through the SAE engine.

### 1.3 HyperLiquid API Integration

Uses [`hyperliquid-python-sdk`](https://github.com/hyperliquid-dex/hyperliquid-python-sdk) exclusively.

| Interface | Use | Rationale |
|:--|:--|:--|
| WS `subscribe` | Trades, L2 book, candles (real-time) | Sub-100 ms latency for entry triggers |
| REST `info.candles_snapshot` | Historical OHLCV for backtest | Rate-limited; startup only |
| REST `exchange.order` | Order placement / cancel | Stateless, auditable |
| REST `info.user_state` | Position / margin poll (1 Hz) | Reconciles WS state drift |
| WS `candleSnapshot` stream | 1-minute live candle feed for dashboard | Incremental updates |

### 1.4 Key Management

```
K8s Secret → env var → agent/exchange.py (read-once at init)
```

- `HL_PRIVATE_KEY` — injected by K8s Secret; read once into a non-exportable `LocalAccount`
- `VAULT_SUBACCOUNT_ADDRESS` — injected by K8s Secret; **no code path may write to this value**
- `TRADE_MODE=paper|live` — per-pod flag; default `paper`; live requires `TRADE_MODE_CONFIRM=yes`
- No key material ever reaches `strategy_paper.py` or any agent-writable file

---

## 2. IntelliClaw — Market Intelligence Layer

IntelliClaw is the external multi-source market intelligence service. All analyst
agents consume data exclusively through `apps/agents/src/tools/intelliclaw_client.py`.

### 2.1 Client Functions

| Function | Signature | Purpose |
|:--|:--|:--|
| `get_intel_snapshot` | `(asset, window_hours=24, bypass_cache=False)` | Normalised `IntelSnapshot`; TTL-cached (default 60 s) |
| `search_events` | `(asset, window, limit, importance)` | Historical events (news, exploits, protocol changes) |
| `iter_alert_stream` | `(asset, poll_interval=5.0, max_alerts=None)` | Polling generator yielding live `IntelAlert` objects |
| `get_multi_snapshot` | `(assets, window_hours=24)` | Batch wrapper; errors per-asset are logged and skipped |

Configuration via environment:
```bash
INTELLICLAW_URL=http://intelliclaw:8080   # required
INTELLICLAW_API_KEY=<bearer-token>         # optional
INTELLICLAW_CACHE_TTL=60                  # seconds
```

The client uses a `requests.Session` with `Retry(total=3, backoff_factor=0.5,
status_forcelist=[429,500,502,503,504])`. `IntelliClawError` (a `RuntimeError`
subclass) is raised on non-retryable failures and must be surfaced to the
orchestrator — never swallowed silently.

**Note:** The in-process `_snapshot_cache` dict is not shared across OS processes.
Replace with a Redis-backed cache for multi-worker deployments.

### 2.2 IntelSnapshot Schema

```
IntelSnapshot
  ├── asset: str                        # e.g. "BTC"
  ├── as_of: str                        # ISO-8601 UTC
  ├── window_hours: int                 # default 24
  ├── overall_sentiment: SentimentLabel # bullish|bearish|mixed|neutral
  ├── confidence: float                 # 0.0–1.0
  ├── sentiment_score: float            # –1.0 to +1.0
  ├── key_points: List[str]
  ├── narrative_summary: Optional[str]
  ├── headlines: List[IntelHeadline]
  │     └── source, title, url, published_at, sentiment,
  │         importance, summary, tags
  ├── onchain: Optional[IntelOnChain]
  │     └── net_flows_usd, whale_tx_count, exchange_reserves_change_pct,
  │         active_addresses_change_pct, miner_outflow_usd,
  │         funding_rate, open_interest_change_pct
  ├── fundamental: Optional[IntelFundamental]
  │     └── regime, fear_greed_index, dominance_btc_pct, macro_notes
  ├── alerts: List[IntelAlert]
  │     └── alert_id, severity, message, source, fired_at, tags
  ├── source_count: int
  └── intel_version: str               # "1.0"
```

**Helpers:**
- `.has_critical_alerts` → `bool`
- `.high_importance_headlines` → `List[IntelHeadline]`
- `.to_analyst_context()` → compact LLM-ready string (use for prompt injection)

### 2.3 Analyst Agent Pattern

Every analyst in `apps/agents/src/agents/` must follow this pattern:

```python
from ..tools.intelliclaw_client import get_intel_snapshot
from ..types.intel import IntelSnapshot

class <Role>AnalystAgent:
    def generate_report(self, asset: str) -> <Role>AnalystReport:
        intel = get_intel_snapshot(asset)
        # Build typed AnalystReport from intel.*
        # Use intel.to_analyst_context() for LLM prompt injection
        ...
```

`SentimentAnalystAgent` (`sentiment_analyst.py`) is the reference implementation.
All other stubs are empty and must be implemented following this pattern.

---

## 3. Strategy Architecture

### 3.1 Three-Tier Promotion Lifecycle

Strategies flow through three tiers. Promotion is one-way except when recovery
mode triggers a demotion.

```
BACKTEST  ────────────────────────────────────────────────────────────
  Sharpe ≥ 1.5  AND  max_dd < 8%  AND  n_trades ≥ 10
    │
    ▼
PAPER TRADE  ────────────────────────────────────────────────────────
  (runs continuously 24/7 on BTC-PERP)
  Sharpe ≥ 1.5  AND  win_rate ≥ 45%  AND  n_trades ≥ 30  over 48 h
    │
    ▼
LIVE TRADE  ─────────────────────────────────────────────────────────
  Real funds; vault active; drawdown guards armed
    │  if equity ≤ 50% of session_start_equity
    ▼
RECOVERY MODE  ──────────────────────────────────────────────────────
  Live halted → accelerated research (200 iter/night)
  Raised bar: Sharpe ≥ 2.0  AND  win_rate ≥ 50%  AND  72 h paper
```

### 3.2 Dual-File Architecture

```
apps/agents/src/strategies/
  base_strategy.py        ← OpenTrader-style interface (locked)
strategy/
  strategy_base.py        ← Abstract ABC interface (locked)
  strategy_paper.py       ← AGENT-EDITABLE; paper bot target
  strategy_live.py        ← Written by promotion logic ONLY
  strategy_vault.py       ← Vault rate config (rate editable; address locked)
```

### 3.3 BaseStrategy Interface (`apps/agents/src/strategies/base_strategy.py`)

OpenTrader-style interface consumed by the Trader Agent and strategy plugins:

```python
class BaseStrategy:
    name: str = "BaseStrategy"
    description: str = ""
    parameters_schema: dict = {}   # JSON-schema for UI / autogen

    def __init__(self, symbol: str, parameters: dict): ...
    def on_start(self, ctx) -> None: ...
    def on_stop(self, ctx) -> None: ...
    def on_bar(self, bar, ctx) -> None: ...
    def generate_signals(self, ctx) -> list[dict]:
        # Returns [{"action": "buy", "size": 0.1, "type": "market"}, ...]
        # SAE / execution layer validates and transforms to orders.
        return []
```

Strategy plugins: `grid_bot.py`, `dca_bot.py`, `rsi_reversion.py`,
`hyperliquid_perps_meta.py` — all extend `BaseStrategy`.

### 3.4 StrategyConfig (`strategy/strategy_base.py`, locked ABC)

The ABC-layer config used by the autoresearch loop:

```python
@dataclass
class StrategyConfig:
    # Indicators — agent editable
    ema_fast: int = 9;  ema_slow: int = 21
    rsi_period: int = 14;  rsi_oversold: float = 30.0;  rsi_overbought: float = 70.0
    atr_period: int = 14;  atr_stop_multiplier: float = 2.0
    bb_period: int = 20;  bb_std: float = 2.0
    vwap_enabled: bool = False

    # Signal logic — agent editable
    entry_signal: Literal["ema_cross","rsi_reversal","breakout",
                          "bb_squeeze","vwap_reversion","hybrid"] = "ema_cross"
    exit_signal: Literal["atr_trail","fixed_tp_sl","time_exit","signal_flip"] = "atr_trail"
    take_profit_pct: float = 0.03;  stop_loss_pct: float = 0.015

    # Sizing — agent editable; capped by SAE
    position_size_pct: float = 0.10   # max 0.20 in practice
    max_concurrent_positions: int = 1

    # Orders — agent editable
    entry_order_type: Literal["limit","market"] = "limit"
    limit_offset_bps: int = 5;  min_edge_bps: int = 10

    # Vault — agent may set rate; address is LOCKED
    vault_take_pct: float = 0.10   # clamped to [0.10, 0.20] by safety layer
```

**Iteration constraint:** At most **3 `StrategyConfig` parameter changes** per
proposal. Each change must be justified by referencing recent paper trade outcomes
from the RL buffer.

---

## 4. Autoresearch Feedback Loop

### 4.1 Paper Bot — Continuous Real-Time Reinforcement

The paper bot runs **24/7**, never paused between evaluation windows.

```python
class PaperBot:
    """Runs strategy_paper.py against live HL ticks. No real orders.
    Fills simulated at mid ± half-spread. Outcomes → rl_buffer."""
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
        if (agg.sharpe >= 1.5 and agg.win_rate >= 0.45
                and agg.meets_minimum_trades(n=30)
                and not recovery_state.active):
            await promote_to_live(self.strategy)
```

### 4.2 RL Buffer Schema

```python
@dataclass
class PaperTradeOutcome:
    strategy_run_id: str
    symbol: str
    signal: str              # long / short
    entry_price: float
    exit_price: float
    pnl_usd: float;  pnl_pct: float
    hold_bars: int
    entry_signal_features: dict   # indicator snapshot at entry
    exit_reason: str         # atr_trail | tp | sl | signal_flip | time_exit
    funding_paid: float;  fee_paid: float
    timestamp: int

# SQLite tables in logs/experiments.db:
# paper_outcomes   — one row per closed paper trade
# rl_aggregates    — rolling window stats (sharpe, win_rate, avg_edge_bps,
#                    worst_trade_pct, funding_drag, meets_promotion_criteria)
# experiments      — one row per autoresearch iteration
```

### 4.3 Agent Proposal Context

Every iteration receives this context before proposing a new `strategy_paper.py`:

```python
async def build_proposal_context(db) -> dict:
    return {
        "program":              load_trading_program("trading_program.md"),
        "backtest_history":     db.last_n_experiments(20),
        "paper_rl_window":      db.get_rl_aggregates(hours=48),
        "paper_recent_trades":  db.get_paper_outcomes(limit=50),
        "current_live_config":  load_live_config(),
        "market_conditions":    await get_market_snapshot(),  # funding, vol regime
        "recovery_mode":        get_recovery_state(),
    }
```

### 4.4 Overnight Iteration Loop

```python
async def overnight_loop(
    max_iterations: int = 100,    # 200 in recovery mode
    backtest_budget_minutes: float = 5.0,
    score_threshold: float = 1.5, # 2.0 in recovery mode
):
    for i in range(max_iterations):
        ctx      = await build_proposal_context(db)
        proposal = await agent.propose_strategy(
            context=ctx,
            constraints=[
                "max 3 StrategyConfig param changes from current paper config",
                "prefer limit orders",
                "account for current funding rate regime",
                "justify each change referencing recent paper trade outcomes",
            ]
        )
        if not validate_strategy_module(proposal.code):
            db.log(proposal, kept=False, rationale="validation_fail"); continue
        try:
            score = await asyncio.wait_for(
                run_backtest(proposal.strategy, candles),
                timeout=backtest_budget_minutes * 60
            )
        except asyncio.TimeoutError:
            db.log(proposal, kept=False, rationale="timeout"); continue
        if not should_keep(score, db.get_best_score()):
            db.log(proposal, score=score, kept=False); continue
        # ACCEPT — deploy to paper bot
        db.log(proposal, score=score, kept=True)
        git_commit_strategy(
            proposal.code,
            path="strategy/strategy_paper.py",
            tag=f"paper/v{i}",
            message=proposal.rationale,
        )
        # ArgoCD picks up → paper bot ConfigMap update
        # Promotion to live: async, via paper_bot._check_promotion_criteria()
        await asyncio.sleep(2)
```

### 4.5 Keep / Discard Logic

```python
def should_keep(new_score: dict, best_score: dict | None) -> bool:
    if new_score["max_drawdown"] > 0.08: return False   # hard constraint
    if new_score["n_trades"] < 10:       return False   # insufficient sample
    if best_score is None:
        return new_score["sharpe"] >= score_threshold
    return (new_score["sharpe"] > best_score["sharpe"] and
            new_score["max_drawdown"] <= best_score["max_drawdown"] * 1.1)
```

---

## 5. Live Bot — Guarded Real-Fund Execution

### 5.1 Session State

```python
@dataclass
class LiveSession:
    session_id: str
    session_start_equity: float  # set at start; reset on recovery exit
    current_equity: float
    peak_equity: float
    vault_balance: float         # accumulated in HL sub-account
    total_profit_realized: float
    halt_reason: str | None = None

    @property
    def recovery_threshold(self) -> float:
        return self.session_start_equity * 0.50   # 50% floor

    @property
    def in_recovery(self) -> bool:
        return self.current_equity <= self.recovery_threshold
```

### 5.2 Vault Deduction on Trade Close

```python
async def close_position_and_vault(position, exit_price, session):
    raw_pnl = compute_pnl(position, exit_price)
    net_pnl = raw_pnl - compute_fees(position, exit_price)
    if net_pnl > 0:
        vault_amt = net_pnl * clamp(session.vault_take_pct, 0.10, 0.20)
        await exchange.transfer_to_vault(vault_amt, VAULT_SUBACCOUNT_ADDRESS)
        session.vault_balance  += vault_amt
        session.current_equity += (net_pnl - vault_amt)
    else:
        session.current_equity += net_pnl   # losses never touch vault
    session.peak_equity = max(session.peak_equity, session.current_equity)
    safety.check_recovery_threshold(session)
```

### 5.3 Vault Rules

| Rule | Value | Notes |
|:--|:--|:--|
| Take rate | 10–20% | Agent may set within range; default 10% |
| Condition | Profitable trades only | Losses never reduce vault |
| Address | `VAULT_SUBACCOUNT_ADDRESS` env var | Locked — never agent-writable |
| Withdrawal | Manual only | No automated withdrawal logic |
| Re-deployment | Prohibited | Vault balance is one-way |
| Target | 1× `session_start_equity` | Suggested trigger for human-reviewed withdrawal |

---

## 6. Safety Layer

### 6.1 Kill Switches (`agent/safety.py`, locked)

```python
class SafetyGuard:
    HARD_MAX_POSITION_USD = 500        # paper; override via env for live
    DAILY_LOSS_LIMIT_PCT  = 0.02
    MAX_DRAWDOWN_PCT       = 0.08
    API_RATE_LIMIT_RPS     = 3         # self-limit; HL public limit is 5 rps

    def check(self, current_equity: float) -> None:
        """Raises TradingHalt if any limit breached."""

    def validate_order(self, size_usd: float) -> None:
        """Raises OrderRejected if size > HARD_MAX_POSITION_USD."""
```

### 6.2 Recovery Mode Trigger

```python
def check_recovery_threshold(session: LiveSession):
    if session.in_recovery and not recovery_state.active:
        await exchange.cancel_all_orders()
        await exchange.close_all_positions()
        recovery_state.activate(reason="equity_floor",
                                floor_equity=session.current_equity)
        await alert.send("🔴 LIVE TRADING HALTED — recovery mode engaged.")
```

### 6.3 Recovery Mode Parameters

```python
@dataclass
class RecoveryState:
    active: bool = False
    recovery_target_sharpe: float = 2.0   # raised from normal 1.5
    min_paper_hours: float = 72.0         # raised from normal 48 h
    min_win_rate: float = 0.50            # raised from normal 0.45
    min_trades: int = 50                  # raised from normal 30
```

While in recovery:
1. Live bot: completely halted
2. Autoresearch loop: 200 iterations/night (vs. normal 100)
3. Paper bot: continues 24/7
4. Promotion bar raised to all recovery thresholds above
5. On exit: `session_start_equity` resets to current equity

### 6.4 Rate Limiting

```python
# Token bucket in exchange.py — 3 req/s, burst 5
_rate_sem = asyncio.Semaphore(5)
async def throttled_request(coro):
    async with _rate_sem:
        result = await coro
        await asyncio.sleep(0.33)   # enforce 3 rps avg
        return result
```

---

## 7. SAE Engine — Survivability-Aware Execution

The SAE (Survivability-Aware Execution) engine runs as a separate TypeScript
service (`apps/sae-engine/`). It is the **only path** from approved trade
decisions to the executor layer.

Functions:
- Validates trade requests against per-asset leverage and size caps
- Enforces drawdown-aware regime selection
- Builds staged execution plans with algo hints: TWAP, VWAP, POV, Iceberg
- Integrates with RL-based execution timing agents (future)
- Acts as a non-bypassable firewall — no executor may be called directly

Configuration via `config/strategies/` YAML files and the
`PUT /sae/policies` Orchestrator API endpoint.

---

## 8. Evaluation Harness (`agent/harness.py`, locked)

```python
BACKTEST_DAYS      = 30       # rolling window
CANDLE_INTERVAL    = "15m"
SCORE_THRESHOLD    = 1.5      # Sharpe; raised to 2.0 in recovery

def score(equity: list, trades: list) -> dict:
    """Returns sharpe, max_drawdown, win_rate, profit_factor, n_trades."""
    returns      = np.diff(equity) / equity[:-1]
    sharpe       = (returns.mean() / (returns.std() + 1e-9)) * np.sqrt(365 * 96)
    # 96 = 15-minute bars per day
    drawdown     = max_drawdown(equity)
    win_rate     = sum(1 for t in trades if t["pnl"] > 0) / max(len(trades), 1)
    profit_factor = (sum positive pnl) / (sum abs negative pnl)
    return {"sharpe": sharpe, "max_drawdown": drawdown, "win_rate": win_rate,
            "profit_factor": profit_factor, "n_trades": len(trades)}
```

**SQLite experiment log schema (`logs/experiments.db`):**

```sql
CREATE TABLE experiments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL,   -- git short SHA of strategy_paper.py
    timestamp     INTEGER NOT NULL,
    config_json   TEXT NOT NULL,   -- StrategyConfig as JSON
    score_json    TEXT NOT NULL,   -- score() output
    sharpe        REAL,
    max_dd        REAL,
    kept          INTEGER DEFAULT 0,
    rationale     TEXT
);
CREATE TABLE paper_outcomes ( ... as PaperTradeOutcome dataclass ... );
CREATE TABLE rl_aggregates (
    run_id TEXT, window_hours REAL, sharpe REAL, win_rate REAL,
    avg_edge_bps REAL, worst_trade_pct REAL, funding_drag REAL,
    meets_promotion_criteria INTEGER
);
```

JSONL sidecar: `logs/experiments.jsonl` (streaming dashboards).

---

## 9. MLflow Experiment Tracking (MultiClaw-MLFlow)

All ML/RL/OPRO jobs in `apps/jobs/` must log to the MultiClaw-MLFlow stack
(`multiclaw/mlflow/`): MLflow + Postgres + MinIO.

```bash
# Start stack
cd multiclaw/mlflow/infra && docker compose up -d
# Tracking UI: http://localhost:5000
```

**Required fields per run** (from `EXPERIMENT_STANDARD.md`):

| Field | Description |
|:--|:--|
| `model family + version` | LLM or RL model identifier |
| `dataset identifier/version` | Candle source + date range |
| `hyperparameters` | All `StrategyConfig` params |
| `training/eval metrics` | Sharpe, max_dd, win_rate, profit_factor |
| `artifact URI` | Path to `strategy_paper.py` snapshot |
| `operator/agent role` | `autoresearch` / `rl-training` / `opro` |

```python
import mlflow
with mlflow.start_run(run_name="backtest_ema_cross_v42"):
    mlflow.log_params({"strategy": "ema_cross", "ema_fast": 9, "ema_slow": 21})
    mlflow.log_metrics({"sharpe": 1.72, "max_dd": 0.063, "win_rate": 0.51})
    mlflow.log_artifact("strategy/strategy_paper.py")
```

`MLFLOW_TRACKING_URI=http://multiclaw-mlflow:5000` (set in `.env.example`).

---

## 10. Dashboard and Observability

### 10.1 Service Components

| Service | Role |
|:--|:--|
| `dashboard-ui` | React/Next.js UI (charts, tables, regime toggles) |
| `dashboard-api` | FastAPI backend — aggregates trading and research data |
| `market-ingestor` | Stores 1-minute candles locally (365-day rolling window) |
| `status-reporter` | Sends 12-hour operational summary messages |

### 10.2 UI Sections

- **Market Research** — last 365 days of 1-minute candles; strategy entry/exit
  markers; regime annotations
- **Paper Trading Performance** — cumulative P/L, rolling Sharpe, max DD, win rate,
  fees, funding, vault transfers
- **Live Trading Performance** — same as paper + live equity curve
- **Vault / Reserved Profit Balance** — accumulated vault balance
- **Strategy Experiments** — experiment history, accepted/rejected, rationale
- **Risk and Halt Status** — current mode (backtest / paper / live / recovery)

### 10.3 Data Sources

| Data | Source |
|:--|:--|
| Historical candles | HL `candleSnapshot` API → local time-series store |
| Live candles | HL WebSocket `candle` stream (1-minute incremental) |
| Account state | HL clearinghouse state + user fills |
| Experiment data | SQLite `experiments.db` + `experiments.jsonl` |

**Persistent data model:**

```sql
-- Candle store
CREATE TABLE candles (
    symbol TEXT, interval TEXT, ts INTEGER,
    open REAL, high REAL, low REAL, close REAL, volume REAL, source TEXT
);
-- Performance store
CREATE TABLE bot_performance (
    bot_type TEXT,   -- paper | live
    session_id TEXT, realized_pnl REAL, unrealized_pnl REAL,
    fees_paid REAL, funding_paid REAL, balance REAL,
    reserved_profit REAL, max_drawdown REAL, updated_at INTEGER
);
```

### 10.4 12-Hour Status Notification

The `status-reporter` sends a compact summary every 12 hours via Slack,
Telegram, or email fallback. Contents:

- Paper bot cumulative P/L
- Live bot cumulative P/L
- Current account balance
- Reserved profit (vault) balance
- Current drawdown
- Current state: `normal | paper-only | live | recovery`

Reporter failures are logged and retried on the next cycle. Repeated failures
trigger an ops alert but **do not halt trading**. Notifications must never
include secrets, private keys, or raw wallet material.

### 10.5 Dashboard Auth

Dashboard must be deployed behind SSO or reverse-proxy auth. It must never
expose secrets, raw API keys, or HL private key material in any API response.

---

## 11. Deployment

### 11.1 Environment Variables

```bash
# HyperLiquid (K8s Secrets only — never in repo)
HL_PRIVATE_KEY=<private-key>
VAULT_SUBACCOUNT_ADDRESS=<hl-sub-account-addr>
TRADE_MODE=paper                    # paper | live
TRADE_MODE_CONFIRM=yes              # required to enable TRADE_MODE=live

# LLM
LLM_PROVIDER=<openai|anthropic|…>
LLM_API_KEY=<provider-key>

# IntelliClaw
INTELLICLAW_URL=http://intelliclaw:8080
INTELLICLAW_API_KEY=<bearer-token>  # optional
INTELLICLAW_CACHE_TTL=60

# MLflow
MLFLOW_TRACKING_URI=http://multiclaw-mlflow:5000
```

### 11.2 Kubernetes Pods

| Pod | Manifest | TRADE_MODE |
|:--|:--|:--|
| `orchestrator-api` | `infra/k8s/base/orchestrator-api-deploy.yaml` | N/A |
| `sae-engine` | `infra/k8s/base/sae-engine-deploy.yaml` | N/A |
| `agents` | `infra/k8s/base/agents-deploy.yaml` | N/A |
| `executors` | `infra/k8s/base/executors-deploy.yaml` | `paper` (default) |
| `dashboard` | `infra/k8s/base/dashboard-deploy.yaml` | N/A |
| `aiml-namespace` | `infra/k8s/aiml/namespace.yaml` | N/A |

Live trading requires a manual K8s Secret patch to set `TRADE_MODE=live` and
`TRADE_MODE_CONFIRM=yes`.

### 11.3 ArgoCD GitOps Flow

```
Agent accepts strategy
  → git commit strategy/strategy_paper.py  (tag: paper/v{N})
  → push to main branch
  → ArgoCD detects diff
  → applies updated ConfigMap
  → rolling restart of paper-eval pod
  → paper bot resumes with new strategy
  → RL buffer accumulates real-time outcomes
  → promotion to live: async, via paper_bot._check_promotion_criteria()
```

ArgoCD ApplicationSets default to `TRADE_MODE=paper`. Live requires manual
patch. Dashboard manifests are also GitOps-managed; strategy commits do not
directly modify dashboard code.

### 11.4 Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent/   ./agent/
COPY strategy/ ./strategy/
COPY trading_program.md .
# strategy_paper.py mounted via ConfigMap or git-sync sidecar
CMD ["python", "-m", "agent.main"]
```

---

## 12. Repository Layout

```
hyperliquid-trading-firm/
├── SPEC.md                       ← this file (canonical)
├── SPEC-v1.md                    ← archived
├── SPEC-v2.md                    ← archived
├── AGENTS.md                     ← agent editing rules
├── CLAUDE.md                     ← Claude Code guidance
├── trading_program.md            ← human-authored goals + addenda
├── .env.example                  ← env var template
│
├── apps/
│   ├── orchestrator-api/         # Node/TS REST+WS API
│   ├── sae-engine/               # TypeScript SAE policy engine
│   ├── agents/
│   │   └── src/
│   │       ├── agents/           # 12 analyst/trader/risk agent stubs
│   │       ├── atlas/            # meta_prompts.py, prompt_optimizer.py
│   │       ├── config/           # model_routing.yaml
│   │       ├── memory/           # global_state_store.py, vector_store.py
│   │       ├── strategies/       # base_strategy.py + 4 plugin stubs
│   │       ├── tools/            # intelliclaw_client.py (implemented)
│   │       ├── types/            # intel.py (IntelSnapshot schema, implemented)
│   │       └── main.py
│   ├── executors/                # HL, Hummingbot, DEX adapters
│   ├── dashboard/                # React/Next.js UI
│   └── jobs/                     # Backtests, RL training, OPRO, DCA/vault
│
├── strategy/
│   ├── strategy_base.py          ← locked ABC
│   ├── strategy_paper.py         ← AGENT-EDITABLE
│   ├── strategy_live.py          ← promotion logic only
│   └── strategy_vault.py         ← vault rate config
│
├── agent/
│   ├── main.py                   ← orchestrator (locked)
│   ├── exchange.py               ← HL SDK, auth, rate limit (locked)
│   ├── safety.py                 ← kill switches (locked)
│   ├── harness.py                ← backtest + scoring (locked)
│   ├── iteration_loop.py         ← autoresearch engine (locked)
│   ├── paper_bot.py              ← 24/7 paper trader (locked)
│   ├── live_bot.py               ← real-fund execution (locked)
│   ├── rl_buffer.py              ← reinforcement data store (locked)
│   └── recovery.py               ← recovery state machine (locked)
│
├── logs/
│   ├── experiments.db            ← SQLite (gitignored)
│   └── experiments.jsonl         ← JSONL sidecar (gitignored)
│
├── config/
│   ├── db.yaml, logging.yaml, queues.yaml
│   ├── env.example
│   └── strategies/               ← per-asset SAE policy YAML
│
├── infra/
│   ├── k8s/
│   │   ├── base/                 ← service deployments
│   │   └── aiml/                 ← AI/ML namespace
│   └── terraform/
│
├── multiclaw/
│   ├── mlflow/                   ← MLflow + Postgres + MinIO stack
│   │   ├── infra/docker-compose.yml
│   │   └── docs/  (architecture, runbook, EXPERIMENT_STANDARD, ROADMAP)
│   └── tools/                    ← agentic reasoning docs, PDF utilities
│
├── prompts/                      ← LLM system + user prompt templates
├── tests/                        ← unit + integration tests
├── docker-compose.yml
└── Makefile
```

---

## 13. Success Metrics and Risk Parameters

| Metric | Target | Hard Limit |
|:--|:--|:--|
| Annualised Sharpe ratio | ≥ 1.5 (normal) · ≥ 2.0 (recovery) | — |
| Max drawdown | < 8% over backtest window | 8% → strategy rejected |
| Win rate | ≥ 45% (normal) · ≥ 50% (recovery) | — |
| Profit factor | ≥ 1.3 | — |
| Min trade edge | > 10 bps after fees | < 10 bps → skip trade |
| Paper gate window | 48 h (normal) · 72 h (recovery) | — |
| Overnight iterations | 100 (normal) · 200 (recovery) | 5 min budget/iter |
| Live halt trigger | Equity ≤ 50% of session start | Immediate halt + close all |
| Daily loss limit | 2% of account equity | Trading halt |
| Max position (paper) | $500 notional | Hard cap in safety.py |
| Max position (live) | $2,000 notional (phase 1) | Hard cap via env override |
| Vault take rate | 10% default · max 20% | Agent-configurable within range |
| Funding rate threshold | > 0.05%/8 h adverse | Skip entry |

---

## 14. Markets

- **Primary:** BTC-PERP (highest liquidity, tightest spreads)
- **Secondary:** ETH-PERP (permitted after 50 successful BTC iterations)
- **Prohibited:** Any market with < $5M 24 h volume or funding rate > 0.1%/8 h

---

## 15. OpenClaw Integration Surface

| Endpoint | Description |
|:--|:--|
| `POST /cycles/trigger` | Kick off a full analyst → debate → trader → risk → SAE cycle |
| `PUT /sae/policies` | Adjust SAE leverage, size, drawdown policy parameters |
| `PUT /config/strategy` | Update strategy config for paper bot |
| `GET /traces/:id` | Full decision trace for audit / auto-research loops |
| `GET /metrics` | Live performance metrics |

Do not add endpoints that expose private keys, vault addresses, or allow
direct order placement bypassing the SAE engine.

---

## 16. Design Decision Log

| Decision | Rationale |
|:--|:--|
| Multi-service firm (v2+) vs. single process (v1) | Separation of concerns; orchestrator, agents, SAE, and executors scale and fail independently |
| IntelliClaw as external intel layer (v3) | Analysts get live, multi-source sentiment/on-chain data without managing data pipelines in-repo |
| Paper bot runs 24/7, not just eval windows | Real-time market regime data is more valuable than offline backtest; fills autoresearch context with live signal |
| 48 h paper gate before live promotion | Prevents backtest-overfit strategies from touching real funds; spans multiple sessions and funding cycles |
| Dual-file strategy (paper + live) | Agent cannot bypass the paper gate; only promotion logic writes `strategy_live.py` |
| Vault deducted from profits only | Losses are never taxed; vault grows monotonically as a permanent safety reserve |
| 50% equity floor for live halt | At 50% loss the strategy is demonstrably failing; continuing risks total loss |
| Raised recovery bar (Sharpe 2.0, 72 h) | Recovery must produce a better strategy, not just a marginally passing one |
| `session_start_equity` resets on recovery exit | Prevents perpetual "almost 50% down" trap after recovery |
| Vault address in K8s Secret only | Eliminates any code path where a compromised agent could reroute vault funds |
| MLflow via MultiClaw-MLFlow (v3) | Reproducible experiment governance; Postgres + MinIO for durability across pods |
| Max 3 StrategyConfig param changes/iter | Prevents overfitting by isolating the effect of each change |
| Sharpe over raw PnL as primary metric | Sharpe penalises volatility; more stable signal for unattended overnight runs |
| SQLite for experiment log | Zero infra overhead; queryable; portable across pods |
| ConfigMap / git-sync for strategy_paper.py | ArgoCD can diff/rollback any strategy version without rebuilding the image |
