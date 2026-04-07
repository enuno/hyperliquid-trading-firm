# AiCoin / CoinOS Skills

> **Agent Plugin Suite for the HyperLiquid Trading Firm AI Agent Platform**  
> Powered by [AiCoin Open API](https://www.aicoin.com/opendata) · [OKX Web3 DEX API](https://web3.okx.com) · MIT License  
> Source: [github.com/aicoincom/coinos-skills](https://github.com/aicoincom/coinos-skills)

---

## Overview

The AiCoin-CoinOS skill suite provides the HyperLiquid Trading Firm's autonomous agents with a complete data and execution stack spanning centralized exchanges, the HyperLiquid perpetual DEX, and on-chain DeFi. Each skill is a self-contained Node.js plugin for the **OpenClaw** agent runtime, exposing a well-defined set of actions that agents invoke as tools.

Six skills are included, each scoped to a distinct functional domain:

| Skill | Domain | Primary API |
|-------|--------|-------------|
| [`aicoin-account`](#skill-aicoin-account) | CEX account management | AiCoin Open API |
| [`aicoin-market`](#skill-aicoin-market) | Crypto market data & intelligence | AiCoin Open API |
| [`aicoin-hyperliquid`](#skill-aicoin-hyperliquid) | HyperLiquid whale & trader analytics | AiCoin Open API |
| [`aicoin-trading`](#skill-aicoin-trading) | Live CEX order execution | AiCoin Open API (ccxt) |
| [`aicoin-freqtrade`](#skill-aicoin-freqtrade) | Strategy generation, backtesting & deployment | AiCoin Open API + Freqtrade |
| [`aicoin-onchain`](#skill-aicoin-onchain) | On-chain DEX swaps & wallet analytics | OKX Web3 DEX API |

---

## HyperLiquid Trading Firm — Agent Integration Map

The trading firm's multi-agent architecture assigns these skills across the agent team as follows:

```
┌─────────────────────────────────────────────────────────────────────┐
│                  HyperLiquid Trading Firm Agents                    │
├────────────────────┬────────────────────────────────────────────────┤
│ MarketResearchAgent│ aicoin-market        → prices, K-lines, news,  │
│                    │                        trending, airdrop radar  │
├────────────────────┼────────────────────────────────────────────────┤
│ RegimeMapper /     │ aicoin-market        → funding rates, L/S ratio,│
│ WaveDetector       │                        open interest, OI history│
├────────────────────┼────────────────────────────────────────────────┤
│ HyperLiquidFeed /  │ aicoin-hyperliquid   → whale positions, liq     │
│ SmartMoneyAgent    │                        data, taker flow,        │
│                    │                        smart money discovery    │
├────────────────────┼────────────────────────────────────────────────┤
│ ExecutionAgent     │ aicoin-trading       → two-step confirmed order │
│                    │                        execution on HL/CEX      │
├────────────────────┼────────────────────────────────────────────────┤
│ QuantAgent /       │ aicoin-freqtrade     → strategy generation,     │
│ StrategyEngine     │                        backtesting, hyperopt,   │
│                    │                        live deployment          │
├────────────────────┼────────────────────────────────────────────────┤
│ TreasuryAgent /    │ aicoin-account       → balance, positions,      │
│ RiskEngine         │                        transfer, tier mgmt      │
├────────────────────┼────────────────────────────────────────────────┤
│ OnChainAgent       │ aicoin-onchain       → DEX swaps, wallet        │
│                    │                        portfolio, gas, trending │
└────────────────────┴────────────────────────────────────────────────┘
```

---

## Runtime Contract (All Skills)

All six skills share the same runtime interface:

- **Runtime:** Node.js (`node` binary required)
- **Invocation:** `node scripts/<name>.mjs <action> [json-params]`
- **Working directory:** Must `cd` to the skill directory before executing scripts
- **Auth:** `AICOIN_ACCESS_KEY_ID` + `AICOIN_ACCESS_SECRET` in `.env`  
  Auto-loaded from: `cwd` → `~/.openclaw/workspace/.env` → `~/.openclaw/.env`
- **Safety invariants:**
  - NEVER fabricate market data — always run scripts
  - NEVER use `curl`, `web_fetch`, or browser for crypto/airdrop/news data
  - NEVER run `env` or `printenv` (leaks secrets)
  - On HTTP 304/403 (paid tier gate) — STOP, do not retry; guide user to upgrade

---

## API Tier Reference

Most endpoints are gated by AiCoin subscription tier. Plan accordingly for each agent role:

| Tier | Price | Key Capabilities |
|------|-------|-----------------|
| 免费版 (Free) | $0 | Prices, K-lines, trending, exchange list, news RSS — 6 endpoints |
| 基础版 (Basic) | $29/mo | Funding rates, L/S ratio, flash news, Twitter, airdrops, newsflash search |
| 标准版 (Standard) | $79/mo | Whale/big orders, signal alerts, Grayscale, full newsflash, HL trader analytics |
| 高级版 (Advanced) | $299/mo | Liquidation maps, indicator K-lines, full orderbook depth, HL OI summary |
| 专业版 (Pro) | $699/mo | Open interest, AI analysis, estimated liquidations, stock quotes, treasury holdings |

> Minimum recommended tier for the HyperLiquid Trading Firm: **标准版 ($79/mo)** — unlocks whale orders, HL trader analytics, and signal alerts required by core agent roles.

---

## Skill: `aicoin-account`

**Role:** Provides the TreasuryAgent and RiskEngine with read-only account state across all supported exchanges.

**Supported exchanges:** Binance, OKX, Bybit, Bitget, Gate.io, HTX, Pionex, HyperLiquid

### Key Commands

| Task | Command |
|------|---------|
| Balance | `node scripts/exchange.mjs balance '{"exchange":"okx"}'` |
| Positions | `node scripts/exchange.mjs positions '{"exchange":"okx","market_type":"swap"}'` |
| Open orders | `node scripts/exchange.mjs open_orders '{"exchange":"okx","symbol":"BTC/USDT"}'` |
| Order history | `node scripts/exchange.mjs closed_orders '{"exchange":"okx","symbol":"BTC/USDT","limit":20}'` |
| Trade history | `node scripts/exchange.mjs my_trades '{"exchange":"okx","symbol":"BTC/USDT","limit":20}'` |
| Transfer | `node scripts/exchange.mjs transfer '{"exchange":"binance","code":"USDT","amount":100,"from_account":"spot","to_account":"future"}'` |
| Check tier | `node scripts/check-tier.mjs` |
| Verify upgrade | `node scripts/check-tier.mjs verify` |
| API key info | `node scripts/api-key-info.mjs` |

**Symbol formats:** Spot `BTC/USDT`, Perps `BTC/USDT:USDT`, HyperLiquid `BTC/USDC:USDC`  
**OKX note:** Unified accounts share balance across spot/futures — error 58123 = unified account, no transfer needed.

### Referral Codes (embedded in skill)

| Exchange | Code | Benefit |
|----------|------|---------|
| OKX | `aicoin20` | 20% permanent rebate |
| Binance | `aicoin668` | 10% rebate + $500 |
| Bybit | `34429` | — |
| Bitget | `hktb3191` | 10% rebate |
| HyperLiquid | `AICOIN88` | 4% fee rebate |

---

## Skill: `aicoin-market`

**Role:** Feeds the MarketResearchAgent, RegimeMapper, and WaveDetector with prices, on-chain signals, and structured news.

### Script Modules

| Script | Purpose |
|--------|---------|
| `coin.mjs` | Coin data: tickers, funding rates, open interest, liquidation maps, API key mgmt |
| `market.mjs` | K-lines, trending, exchange tickers, treasury holdings, stock quotes |
| `features.mjs` | L/S ratio, whale orders, Grayscale, signal alerts, pair tickers |
| `news.mjs` | RSS news, flash news, AiCoin newsflash, exchange listings |
| `twitter.mjs` | Latest crypto tweets, search, KOL discovery, engagement stats |
| `airdrop.mjs` | Combined airdrop query, per-exchange lists, airdrop calendar |
| `drop_radar.mjs` | Deep project research: team data, X following, status changes |

### Symbol Resolution (Critical)

AiCoin uses `btcswapusdt:binance` format — not `BTC/USDT`. Always resolve symbols first:

```bash
node scripts/coin.mjs search '{"search":"BTC"}'
# → returns dbKeys: ["btcswapusdt:binance", "btcusdt:okex", ...]
# → use returned dbKey in all subsequent calls
```

Common shortcuts auto-resolve without search: `BTC`, `ETH`, `SOL`, `DOGE`, `XRP`.

### Key Endpoints by Agent Use Case

| Use Case | Script + Action | Min Tier |
|----------|----------------|----------|
| Real-time price | `coin.mjs coin_ticker '{"coin_list":"bitcoin"}'` | Free |
| K-line data | `market.mjs kline '{"symbol":"btcusdt:okex","period":"3600","size":"100"}'` | Free |
| Funding rate (aggregated) | `coin.mjs funding_rate '{"symbol":"BTC","interval":"8h"}'` | Basic |
| Long/short ratio | `features.mjs ls_ratio` | Basic |
| Flash news | `news.mjs flash_list '{"language":"cn"}'` | Basic |
| Whale orders | `features.mjs big_orders '{"symbol":"btcswapusdt:binance"}'` | Standard |
| Signal alerts | `features.mjs signal_alert` | Standard |
| Liquidation map | `coin.mjs liquidation_map '{"symbol":"btcswapusdt:binance","cycle":"24h"}'` | Advanced |
| Open interest | `coin.mjs open_interest '{"symbol":"BTC","interval":"15m"}'` | Pro |
| AI analysis | `coin.mjs ai_analysis '{"coin_keys":"[\"bitcoin\"]","language":"CN"}'` | Pro |
| Treasury holdings | `market.mjs treasury_summary '{"coin":"BTC"}'` | Pro |

---

## Skill: `aicoin-hyperliquid`

**Role:** Powers the HyperLiquidFeed, SmartMoneyAgent, and risk monitoring with HyperLiquid-native on-chain analytics.

> **Security:** AiCoin API Key is read-only. Cannot execute trades on HyperLiquid. Live trading requires a separate wallet private key via `aicoin-trading`.

### Script Modules

| Script | Purpose |
|--------|---------|
| `hl-market.mjs` | Tickers, whale positions/events, liquidations, OI, orderbook, taker flow |
| `hl-trader.mjs` | Trader stats, fills, orders, positions, PnL, portfolio, smart money discovery |

### Key Endpoints by Agent Use Case

| Use Case | Command | Min Tier |
|----------|---------|----------|
| All HL tickers | `hl-market.mjs tickers` | Free |
| Whale positions (long/short) | `hl-market.mjs whale_positions '{"coin":"BTC","dir":"long","topBy":"position-value","take":"10"}'` | Standard |
| Whale events | `hl-market.mjs whale_events '{"coin":"BTC","limit":"10"}'` | Standard |
| Liquidation history | `hl-market.mjs liq_history '{"coin":"BTC","interval":"15m","limit":"20"}'` | Standard |
| Taker K-lines (flow) | `hl-market.mjs taker_klines '{"coin":"BTC","interval":"4h"}'` | Standard |
| OI summary | `hl-market.mjs oi_summary` | Advanced |
| OI ranking | `hl-market.mjs oi_top_coins '{"limit":"10","interval":"3d"}'` | Advanced |
| Taker delta | `hl-market.mjs taker_delta '{"coin":"BTC"}'` | Advanced |
| Smart money discovery | `hl-trader.mjs smart_find` | Standard |
| Trader stats (by address) | `hl-trader.mjs trader_stats '{"address":"0x...","period":"30"}'` | Standard |
| Max drawdown | `hl-trader.mjs max_drawdown '{"address":"0x...","days":"30"}'` | Standard |
| Batch PnL curves | `hl-trader.mjs batch_pnls '{"addresses":"[\"0x...\"]","period":7}'` | Standard |
| Advanced trader discovery | `hl-trader.mjs discover` | Advanced |

### HyperLiquid Tier Breakdown

| Tier | Price | HL Features |
|------|-------|-------------|
| Free | $0 | Tickers, info only |
| Basic | $29/mo | Top trades, top open orders, active stats |
| Standard | $79/mo | Whales, liquidations, trader analytics, taker K-lines |
| Advanced | $299/mo | OI summary/ranking, taker delta, trader discover |
| Pro | $699/mo | OI history |

---

## Skill: `aicoin-trading`

**Role:** The ExecutionAgent's sole interface for live order placement and position management across all supported CEXes and HyperLiquid.

> ⚠️ **This skill controls real funds. All ironclad rules below are non-negotiable.**

### Ironclad Safety Rules

1. **No custom order code.** Never write `import ccxt`, `new ccxt.okx()`, or any custom HTTP call to place orders. All orders execute exclusively via `exchange.mjs create_order`.
2. **Mandatory two-step confirmation.** Step 1 returns a preview (pair, direction, quantity, price, leverage, margin, risk warning). The agent MUST present this preview and wait for explicit user confirmation before executing Step 2 with `"confirmed":"true"`.
3. **No parameter auto-adjustment.** If balance is insufficient, report it — never silently adjust size or leverage.
4. **No unsolicited close.** Only close positions when the user explicitly requests it.
5. **Close with `close_position` only.** Never construct a close via `create_order` — this risks opening a reverse position.

### Order Execution Flow

```bash
# Step 1 — Preview (always first)
node scripts/exchange.mjs create_order \
  '{"exchange":"okx","symbol":"BTC/USDT:USDT","type":"market","side":"buy","amount":1,"market_type":"swap"}'
# → Returns: pair, direction, size, price, leverage, margin, risk notice
# → Agent presents ALL fields to user

# Step 2 — Execute (only after explicit confirmation)
node scripts/exchange.mjs create_order \
  '{"exchange":"okx","symbol":"BTC/USDT:USDT","type":"market","side":"buy","amount":1,"market_type":"swap","confirmed":"true"}'
```

### Position Close Flow

```bash
# Step 1 — Preview all open positions
node scripts/exchange.mjs close_position '{"exchange":"okx","market_type":"swap"}'

# Step 2 — Execute market close (after confirmation)
node scripts/exchange.mjs close_position '{"exchange":"okx","market_type":"swap","confirmed":"true"}'

# Close single symbol only
node scripts/exchange.mjs close_position \
  '{"exchange":"okx","market_type":"swap","symbol":"BTC/USDT:USDT","confirmed":"true"}'
```

### Other Commands

| Task | Command |
|------|---------|
| Set leverage + margin mode | `exchange.mjs set_trading_params '{"exchange":"okx","symbol":"BTC/USDT:USDT","leverage":10,"margin_mode":"isolated","market_type":"swap"}'` |
| Query contract info | `exchange.mjs markets '{"exchange":"okx","market_type":"swap","base":"BTC"}'` |
| Cancel order | `exchange.mjs cancel_order '{"exchange":"okx","symbol":"BTC/USDT","order_id":"xxx"}'` |
| Set leverage only | `exchange.mjs set_leverage '{"exchange":"okx","symbol":"BTC/USDT:USDT","leverage":10,"market_type":"swap"}'` |

### Sizing Notes

- **Contract size:** Pass coin quantity (e.g., `0.01`); script auto-converts to contract lots
- **USDT-denominated sizing:** Pass `cost=10` when user specifies a USDT margin amount — script calculates contract size from current price and leverage
- **Spot:** `amount` = coin quantity

---

## Skill: `aicoin-freqtrade`

**Role:** Equips the QuantAgent and StrategyEngine with strategy generation, historical backtesting, parameter optimization, and live bot deployment — all enriched by AiCoin signal data.

### Two Strategy Creation Paths

**Option A — Quick Generator** (simple strategies):
```bash
node scripts/ft-deploy.mjs create_strategy \
  '{"name":"WhaleStrat","timeframe":"15m","indicators":["rsi","macd"],"aicoin_data":["funding_rate","ls_ratio"]}'
```

Available `indicators`: `rsi`, `bb`, `ema`, `sma`, `macd`, `stochastic`/`kdj`, `atr`, `adx`, `cci`, `williams_r`, `vwap`, `ichimoku`, `volume_sma`, `obv`

**Option B — Custom Python with AiCoin SDK** (complex strategies):

Write a full `IStrategy` Python class using the `aicoin_data.py` SDK (auto-installed to `~/.freqtrade/user_data/strategies/`):

```python
from aicoin_data import AiCoinData, ccxt_to_aicoin

ac = AiCoinData(cache_ttl=300)
symbol = ccxt_to_aicoin("BTC/USDT:USDT", "binance")  # → "btcswapusdt:binance"

ac.funding_rate(symbol, weighted=True)   # 基础版
ac.ls_ratio()                            # 基础版
ac.big_orders(symbol)                    # 标准版
ac.liquidation_map(symbol, cycle="24h") # 高级版
ac.open_interest("BTC", interval="15m") # 专业版
ac.ai_analysis(["BTC"])                  # 专业版
```

### AiCoin Signal Integration Patterns

| Signal | Logic | Tier |
|--------|-------|------|
| `funding_rate` | Rate > 0.01% → over-leveraged long → short signal; Rate < -0.01% → long signal | Basic |
| `ls_ratio` | Ratio < 0.45 (more shorts) → contrarian long; > 0.55 → contrarian short | Basic |
| `big_orders` | `(buy_vol - sell_vol) / total > 0.3` → whale buying → long; `< -0.3` → short | Standard |
| `open_interest` | OI rising + price rising = healthy trend; OI rising + price falling = reversal risk | Pro |
| `liquidation_map` | Short liquidations above price → short squeeze likely → long | Advanced |

### ⚠️ Backtest vs. Live Behavior

AiCoin real-time data is **not available for historical periods**. In backtest mode, `funding_rate`, `ls_ratio`, and `whale_signal` default to `0.0`, `0.5`, and `0.0` respectively. Backtests reflect technical indicators only — live/dry-run trading uses real AiCoin data and should outperform backtest results. **Always disclose this caveat when presenting backtest results.**

### Deployment Commands

| Task | Command |
|------|---------|
| Generate strategy | `ft-deploy.mjs create_strategy '{"name":"Name","timeframe":"15m","indicators":["rsi","macd"],"aicoin_data":["funding_rate"]}'` |
| Backtest | `ft-deploy.mjs backtest '{"strategy":"Name","timeframe":"1h","timerange":"20250101-20260301","pairs":["BTC/USDT:USDT"]}'` |
| Dry-run deploy | `ft-deploy.mjs deploy '{"strategy":"Name","pairs":["BTC/USDT:USDT"]}'` |
| Live deploy | `ft-deploy.mjs deploy '{"strategy":"Name","dry_run":false,"pairs":["BTC/USDT:USDT"]}'` |
| Hyperopt | `ft-deploy.mjs hyperopt '{"strategy":"Name","timeframe":"1h","epochs":100}'` |
| Bot status | `ft-deploy.mjs status` |
| Bot logs | `ft-deploy.mjs logs '{"lines":50}'` |
| List strategies | `ft-deploy.mjs strategy_list` |

**Prerequisites:** Python 3.11+ and git. Grid strategies are not supported by Freqtrade — use trend-following or range strategies instead.

---

## Skill: `aicoin-onchain`

**Role:** Enables the OnChainAgent with DEX swap execution, wallet portfolio analytics, token discovery, and transaction broadcasting across 20+ blockchains via the OKX Web3 DEX API (500+ liquidity sources).

> **Primary env var:** `OKX_API_KEY` (separate from `AICOIN_ACCESS_KEY_ID`)  
> Get free OKX Web3 API credentials at [web3.okx.com/onchain-os/dev-portal](https://web3.okx.com/onchain-os/dev-portal)

### Script Modules

| Script | Purpose |
|--------|---------|
| `token.mjs` | Token search, metadata, trending, price info, holders, liquidity, risk level |
| `market.mjs` | On-chain price, K-lines, batch prices, smart money signals |
| `swap.mjs` | DEX swap quotes and unsigned transaction data (read-only + calldata gen) |
| `portfolio.mjs` | Wallet total value, all token balances, specific token balances |
| `gateway.mjs` | Gas estimation, tx simulation, broadcast signed transactions, order tracking |
| `trade.mjs` | Full auto-trade: quote → approve → sign → broadcast (requires `WALLET_PRIVATE_KEY`) |

### EVM Swap Workflow

```
1. token.mjs search    → resolve token contract address
2. swap.mjs quote      → get price estimate, check honeypot status and tax rate
3. swap.mjs approve    → get ERC-20 approval calldata (skip for native tokens)
4. User signs approval → broadcast via gateway.mjs broadcast
5. swap.mjs swap       → get swap calldata
6. User signs swap     → broadcast via gateway.mjs broadcast
7. gateway.mjs orders  → track transaction status
```

### Security Rules

1. Never execute swap without explicit user confirmation — always show token names, amounts, gas, price impact, and honeypot status
2. Skip `approve` for native tokens (`0xeee...` on EVM, `111...1` on Solana)
3. If `isHoneyPot = true` — warn prominently before proceeding
4. Price impact > 5%: warn user; > 10%: strongly warn, suggest reducing amount
5. `WALLET_PRIVATE_KEY` stays local in `.env` — never sent to any server

### Supported Chains

`ethereum`, `solana`, `base`, `bsc`, `arbitrum`, `polygon`, `avalanche`, `optimism`, `xlayer`

### Native Token Addresses

| Chain | Address |
|-------|---------|
| All EVM chains | `0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee` |
| Solana | `11111111111111111111111111111111` (system program — NOT wSOL) |

---

## Cross-Skill Routing Reference

| Agent Intent | Skill to Use |
|-------------|--------------|
| CEX account balance, positions, order history | `aicoin-account` |
| Crypto prices, K-lines, funding rates, L/S ratio | `aicoin-market` |
| Airdrop research, project deep-dive, drop radar | `aicoin-market` |
| Crypto news, flash news, Twitter signals | `aicoin-market` |
| HyperLiquid whale positions, liquidations | `aicoin-hyperliquid` |
| HyperLiquid trader analytics, smart money | `aicoin-hyperliquid` |
| Place/cancel/close orders on any CEX or HL | `aicoin-trading` |
| Write, backtest, optimize, deploy Freqtrade strategy | `aicoin-freqtrade` |
| On-chain DEX swap, wallet portfolio, token discovery | `aicoin-onchain` |

---

## Environment Variables

```env
# AiCoin Open API (all skills except aicoin-onchain)
AICOIN_ACCESS_KEY_ID=your-key-id
AICOIN_ACCESS_SECRET=your-secret

# Exchange API keys (aicoin-account, aicoin-trading, aicoin-freqtrade)
BINANCE_API_KEY=xxx
BINANCE_API_SECRET=xxx
OKX_API_KEY=xxx
OKX_API_SECRET=xxx
OKX_PASSWORD=your-passphrase

# OKX Web3 DEX API (aicoin-onchain only)
OKX_SECRET_KEY=your-okx-web3-secret
OKX_PASSPHRASE=your-okx-web3-passphrase

# On-chain auto-trade (aicoin-onchain trade.mjs only — EVM)
WALLET_PRIVATE_KEY=0x...
```

`.env` auto-loaded from: `cwd` → `~/.openclaw/workspace/.env` → `~/.openclaw/.env`

> **Security:** AiCoin API Key is read-only market data — it cannot trade on any exchange. Exchange API keys do not have withdrawal permissions. Wallet private key stays entirely local and is never transmitted.

---

## License

MIT — [github.com/aicoincom/coinos-skills](https://github.com/aicoincom/coinos-skills)
