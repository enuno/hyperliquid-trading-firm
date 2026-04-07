<!-- ANALYTICS.md — HyperLiquid Autonomous Trading Firm -->

# ANALYTICS.md

> **Scope:** Blockchain analytics, on-chain data, token metrics, DeFi/DEX analytics, and market data platform integration for the HyperLiquid Autonomous Trading Firm.  
> This document covers: platform selection rationale, integration patterns for each service layer, full-node operations, and how analytics feeds flow into the agent architecture.

---

## Table of Contents

1. [Design Principles](#1-design-principles)
2. [Analytics Platform Tiers](#2-analytics-platform-tiers)
   - [Tier 1 — Core Free/Open Backbone](#tier-1--core-freeopen-backbone)
   - [Tier 2 — Targeted Paid Services](#tier-2--targeted-paid-services)
   - [Tier 3 — Deferred or Skip](#tier-3--deferred-or-skip)
3. [Full Node Operations](#3-full-node-operations)
4. [Data Flow Architecture](#4-data-flow-architecture)
5. [Agent Integration Map](#5-agent-integration-map)
6. [Service Configuration](#6-service-configuration)
7. [Schema Reference](#7-schema-reference)
8. [Operational Guidance](#8-operational-guidance)
9. [Platform Comparison Table](#9-platform-comparison-table)

---

## 1. Design Principles

Analytics sourcing follows these principles, in priority order:

1. **Open-source and self-hosted first.** If a platform's core functionality can be replicated by running your own indexer or consuming a free public API, the commercial platform is deferred.
2. **Programmatic access over dashboards.** All analytics must expose REST or WebSocket APIs suitable for automated ingestion; human-only dashboards are classified as research tools, not data sources.
3. **Normalization at ingestion.** All external data is normalized to internal canonical schemas (`OnChainMetric`, `MarketSnapshot`, `DeFiProtocolState`, `TokenFundamentals`) before any agent consumes it. Agents never call external APIs directly.
4. **Redundancy on critical price feeds.** Reference prices are cross-validated across at minimum two independent sources before entering the execution path.
5. **Least-cost acquisition.** A paid platform is only provisioned when a concrete, validated signal hypothesis exists that specifically requires data not available from free sources.
6. **Auditability.** Every external data fetch is logged with source, timestamp, and schema version for replay and post-trade attribution.

---

## 2. Analytics Platform Tiers

### Tier 1 — Core Free/Open Backbone

These services are active from Day 1. All are free to use at the required scale or open-source self-hosted.

---

#### 2.1 DeFiLlama

- **Role:** Primary DeFi/DEX analytics backbone.
- **Data provided:** Protocol TVL, fees, revenue, DEX volumes, stablecoin supply by chain, protocol health metrics, yield rates, bridge flows.
- **API:** Public REST, no API key required for standard endpoints. Optional Pro API for higher rate limits.
- **Relevance to HL Trading Firm:** Feeds `DeFiProtocolState` snapshots used by the **Market Research Agent** and **OnChainFlowAnalyst**. Provides cross-protocol liquidity context for regime detection and token selection.
- **Integration point:** `apps/agents/src/tools/defillama_client.py`
- **Key endpoints:**
  ```
  GET https://api.llama.fi/protocols
  GET https://api.llama.fi/protocol/{protocol}
  GET https://api.llama.fi/charts
  GET https://yields.llama.fi/pools
  GET https://stablecoins.llama.fi/stablecoins
  GET https://api.llama.fi/overview/dexs
  GET https://api.llama.fi/overview/fees
  ```
- **Update cadence:** Hourly snapshots into TimescaleDB; daily archival to Delta Lake.
- **Cost:** Free (public API). Pro API available for higher rate limits if needed.

---

#### 2.2 Dune Analytics (Free Tier)

- **Role:** Ad-hoc on-chain SQL research and hypothesis prototyping.
- **Data provided:** Decoded EVM event logs, token transfers, DEX trades, lending events, liquidations, cross-chain bridges.
- **API:** REST (query execution + results download). Free tier has limited monthly credits.
- **Relevance to HL Trading Firm:** Used by the **Quant Validation Agent** for rapid hypothesis testing against decoded on-chain data before building dedicated indexers. Query results can be exported as Parquet for offline backtesting.
- **Integration point:** `apps/jobs/src/research/dune_query.py` (research/offline jobs only — not in live execution path)
- **Key usage pattern:**
  ```python
  # Example: fetch funding-rate anomaly dataset from a Dune query
  from dune_client.client import DuneClient
  client = DuneClient(api_key=os.getenv("DUNE_API_KEY"))
  result = client.get_latest_result(query_id=QUERY_ID)
  ```
- **Cost:** Free tier (~2,500 credits/month). Paid tiers from ~$399/month.
- **Constraint:** Free-tier queries are public. Use private queries only on paid plans for any proprietary signal logic.

---

#### 2.3 The Graph (Community Subgraphs + Decentralized Network)

- **Role:** Structured EVM protocol indexing.
- **Data provided:** Protocol-specific decoded event data (DEX swaps, LP positions, lending health factors, liquidations) via GraphQL.
- **Relevance to HL Trading Firm:** Used to index specific DeFi protocols relevant to cross-chain collateral management and hedge execution. Custom subgraphs are deployed for protocols not covered by community indexes.
- **Integration point:** `apps/agents/src/tools/subgraph_client.py`
- **Deployment:** Community subgraphs via hosted service for research; self-hosted Graph Node for production critical paths.
- **Key protocols to index:**
  - Uniswap V3 (all active L2 deployments)
  - Aave V3 (Arbitrum, Optimism, Base)
  - GMX (Arbitrum)
  - Hyperliquid bridge contracts (Arbitrum)
- **Cost:** Free for community subgraphs. Decentralized network incurs GRT query fees (~minimal at normal volume). Self-hosted Graph Node: infrastructure cost only.

---

#### 2.4 Subsquid

- **Role:** Custom EVM and non-EVM chain indexing with full archival capability.
- **Data provided:** Any on-chain event, transaction, storage slot — custom-schema, high-throughput.
- **Relevance to HL Trading Firm:** Preferred over The Graph when custom schemas are needed, when querying raw transaction traces (MEV-style orderflow analytics), or when non-EVM chains are involved.
- **Integration point:** `infra/subsquid/` (processor definitions), `apps/agents/src/tools/subsquid_client.py`
- **Key use cases:**
  - Raw block-level liquidation event indexing
  - Custom orderflow analytics (large swaps, whale accumulation)
  - Cross-chain bridge event indexing
- **Cost:** Open-source SDK (free self-hosted). Subsquid Cloud available if self-hosting is not feasible.

---

#### 2.5 CoinGecko

- **Role:** Market metadata, token reference data, pricing.
- **Data provided:** OHLCV, market cap, FDV, circulating supply, volume, token metadata, exchange listings, categories/narratives, derivative markets.
- **API:** Public REST (no key, rate-limited); Pro API for higher limits and extended history.
- **Relevance to HL Trading Firm:** Primary source for `TokenFundamentals` schema. Feeds the **FundamentalAnalyst** agent with supply/market structure data. Used for reference price cross-validation.
- **Integration point:** `apps/agents/src/tools/coingecko_client.py`
- **Key endpoints:**
  ```
  GET /coins/markets
  GET /coins/{id}/ohlc
  GET /coins/{id}/market_chart
  GET /derivatives/exchanges
  ```
- **Cost:** Free (demo API key, 30 calls/min). Pro from $129/month for higher limits.

---

#### 2.6 CoinMarketCap (CMC)

- **Role:** Secondary market data feed (redundancy and cross-check).
- **Data provided:** Prices, volume, market cap, supply, exchange data.
- **Relevance to HL Trading Firm:** Cross-validation source for reference prices. CMC and CoinGecko are both queried; divergence above a threshold triggers a data-quality alert before prices enter the execution path.
- **Integration point:** `apps/agents/src/tools/cmc_client.py`
- **Key usage:** Reference price reconciliation only. Not a primary data source.
- **Cost:** Free (Basic plan, 10,000 calls/month). Standard from $79/month.

---

#### 2.7 Coin Metrics (Community Data)

- **Role:** High-quality BTC/ETH on-chain reference metrics and market microstructure data.
- **Data provided:** Realized cap, MVRV, NVT, active addresses, transaction count, hash rate, exchange flows, reference rates.
- **Relevance to HL Trading Firm:** Feeds the `RegimeMapper` component with BTC/ETH macro on-chain context. Community data covers most required metrics for regime classification.
- **API:** Public REST (`https://community-api.coinmetrics.io/v4/`), no API key for community tier.
- **Integration point:** `apps/agents/src/tools/coinmetrics_client.py`
- **Key metrics used:**
  - `ReferenceRateUSD` — benchmark price
  - `CapMrktCurUSD` — market cap
  - `CapRealUSD` — realized cap
  - `NVTAdj` — network value to transactions
  - `FlowInExNtv` / `FlowOutExNtv` — exchange flows
- **Cost:** Community tier: free. Pro: enterprise pricing (defer unless specific institutional SLA is needed).

---

#### 2.8 Artemis Analytics (Lite/Free Tier)

- **Role:** Macro chain fundamentals, stablecoin flows, cross-chain sector metrics.
- **Data provided:** Daily active addresses, transaction count, fees, stablecoin supply and velocity by chain, protocol revenue, cross-chain asset flows.
- **Relevance to HL Trading Firm:** Supplements DeFiLlama with stablecoin and chain-level activity metrics. Useful for the **Market Research Agent** to assess macro liquidity conditions.
- **API:** Available on Pro plans. Free Terminal for human research.
- **Integration point:** Human research tool (free tier). API integration deferred to Phase 2 if Pro plan justified.
- **Cost:** Lite: free (terminal only). Pro: ~$300/user/month.

---

### Tier 2 — Targeted Paid Services

These services are provisioned only when a concrete, backtested signal hypothesis specifically requires their data. Each requires an explicit go/no-go decision based on measured incremental Sharpe improvement over Tier 1 sources.

---

#### 2.9 Nansen

- **Role:** Wallet labeling, smart-money flow tracking, entity-level on-chain intelligence.
- **Data provided:** Labeled wallet activity (CEX, fund, protocol, whale classifications), smart money token flow, DEX volume by wallet tier, NFT/token holder concentration.
- **Relevance to HL Trading Firm:** Enables "smart money flow" signals for the **OnChainFlowAnalyst** agent. Only justified if backtests show statistically significant incremental lift in Sharpe or drawdown reduction vs. baseline.
- **API:** REST with credit-based pricing.
- **Integration point:** `apps/agents/src/tools/nansen_client.py` (deferred until Phase 2 signal validation)
- **Activation condition:** Walk-forward backtest demonstrating >0.15 Sharpe improvement on held-out data using Nansen wallet flow signals, across ≥2 distinct market regimes.
- **Cost:** API Pro from ~$49/month (credits). Higher tiers for volume.

---

#### 2.10 Glassnode

- **Role:** Deep BTC/ETH on-chain market intelligence.
- **Data provided:** HODL waves, realized price cohorts, miner flows, funding/perpetual metrics, ETF flows, put/call ratios, options gamma exposure.
- **Relevance to HL Trading Firm:** Advanced BTC/ETH regime inputs for `RegimeMapper`. Particularly useful for HODL cohort data and miner selling pressure metrics not available in community sources.
- **API:** REST, tiered by plan.
- **Integration point:** `apps/agents/src/tools/glassnode_client.py` (deferred until Phase 2 macro regime work)
- **Activation condition:** Demonstrated improvement in regime classification accuracy (precision/recall on regime transitions) vs. Coin Metrics community data alone.
- **Cost:** Advanced: ~$39/month. Studio: varies. Research: varies. Enterprise: custom.

---

### Tier 3 — Deferred or Skip

The following platforms are explicitly excluded from the active stack for the reasons stated. They may be reconsidered in future phases with explicit justification.

| Platform | Reason Excluded |
|---|---|
| **Chainalysis** | Compliance/AML tooling. Not relevant to trading signal generation. Required only if fiat on/off-ramp integration or institutional KYC/AML compliance mandated. |
| **Lukka** | Fund accounting, NAV calculation, tax reporting. Relevant only for fund admin, not trading strategy. |
| **Santiment** | On-chain + social sentiment overlaps with FlowHunt MCP integration and open NLP pipelines. Not cost-justified given existing stack. |
| **CryptoQuant** | Substantially overlaps with Glassnode and Coin Metrics for BTC/ETH on-chain flow analytics. Evaluate only if Glassnode proves insufficient. |
| **Coinglass** | Derivatives/liquidation heatmaps can be reconstructed from HyperLiquid WebSocket feeds and exchange APIs. Not required as a paid service. |
| **Space and Time** | Generalized decentralized data warehouse. Functionality covered by Subsquid + self-hosted indexers + TimescaleDB/ClickHouse. |
| **Moralis** | Web3 BaaS. Self-hosting The Graph + Subsquid covers all required EVM indexing without vendor lock-in. |
| **OptiBlack** | Niche. No demonstrated edge over existing open stack for this use case. |
| **DappRadar** | Usage rankings and app metrics useful for research context but not required as a programmatic agent feed. Use manually as a research enrichment tool. |
| **Delphi Digital / The Block / Formo** | Institutional research/editorial. High-quality narrative research for human macro context, not programmatic signal feeds. |
| **Investopedia** | Educational content. Not a data source. |
| **Nansen.ai (website)** | Refer to Nansen API integration above (§2.9). Website access is for human research; API integration is the programmatic path. |

---

## 3. Full Node Operations

Direct chain access eliminates dependency on third-party RPC providers for latency-sensitive paths and enables custom analytics (MEV traces, raw log scraping, mempool monitoring).

### 3.1 Required Nodes

#### Bitcoin Full Node (`bitcoind`)

- **Purpose:** UTXO-level analytics, mempool monitoring, miner behavior, on-chain macro metrics.
- **Client:** Bitcoin Core (`bitcoind`)
- **Mode:** Full node with `txindex=1` for transaction indexing
- **Hardware:** 600 GB SSD minimum (pruned: 20 GB); 8 GB RAM; 4 vCPU
- **Configuration:**
  ```ini
  # bitcoin.conf
  txindex=1
  rpcbind=0.0.0.0
  rpcallowip=10.0.0.0/8
  zmqpubrawblock=tcp://0.0.0.0:28332
  zmqpubrawtx=tcp://0.0.0.0:28333
  ```
- **Analytics derived:** Exchange reserve flows, miner capitulation signals, UTXO age band shifts (feeds `RegimeMapper` BTC macro inputs)
- **Deployment:** `infra/k8s/nodes/bitcoin/`

---

#### Ethereum Archival Node

- **Purpose:** Full EVM trace access for DeFi analytics, MEV-style orderflow, liquidation monitoring, smart contract state queries at arbitrary blocks.
- **Client:** Geth (`go-ethereum`) or Erigon (preferred for archive mode — significantly smaller disk footprint)
- **Mode:** Full archival with `--gcmode=archive` (Erigon: archival by default)
- **Hardware (Erigon):** 2.5 TB NVMe SSD; 16 GB RAM; 8 vCPU
- **Configuration (Erigon example):**
  ```bash
  erigon \
    --chain=mainnet \
    --datadir=/data/erigon \
    --http \
    --http.addr=0.0.0.0 \
    --http.api=eth,net,web3,debug,trace \
    --ws \
    --torrent.download.rate=128mb
  ```
- **Analytics derived:** Raw liquidation events, LP flow events, whale transaction traces, custom DEX price impact modeling
- **Deployment:** `infra/k8s/nodes/ethereum/`

---

#### Arbitrum Full Node

- **Purpose:** L2-specific orderflow analytics, bridge events, Hyperliquid bridge contract monitoring.
- **Client:** Nitro (`arbitrum-nitro`)
- **Mode:** Full node (Arbitrum does not have a standard archival mode; historical data accessed via Sequencer feeds)
- **Hardware:** 1 TB NVMe SSD; 8 GB RAM; 4 vCPU
- **Key analytics:** HyperLiquid bridge deposit/withdrawal flows, Arbitrum DEX (GMX, Camelot) volume and liquidation events
- **Deployment:** `infra/k8s/nodes/arbitrum/`

---

#### Optimism Full Node

- **Purpose:** L2 DeFi protocol analytics (Velodrome, Synthetix, Aave V3 OP).
- **Client:** `op-node` + `op-geth`
- **Hardware:** 500 GB NVMe SSD; 8 GB RAM; 4 vCPU
- **Deployment:** `infra/k8s/nodes/optimism/`

---

#### Base Full Node

- **Purpose:** Base L2 DeFi analytics (Aerodrome, Morpho, Base-native DEX volumes).
- **Client:** `op-node` + `op-geth` (Base is an OP Stack chain)
- **Hardware:** 500 GB NVMe SSD; 8 GB RAM; 4 vCPU
- **Deployment:** `infra/k8s/nodes/base/`

---

### 3.2 Optional / Phase 2 Nodes

| Chain | Client | Justification | Trigger Condition |
|---|---|---|---|
| **Solana** | Jito-Solana or standard validator | Solana ecosystem perp/spot strategies or DeFi hedge execution | Solana assets added to strategy universe |
| **BNB Chain** | BSC client | BNB DeFi strategies (PancakeSwap, Venus) | BNB ecosystem strategies validated |
| **Avalanche C-Chain** | AvalancheGo | Avalanche DeFi (Trader Joe, AAVE) | Avalanche strategies validated |

---

### 3.3 RPC Infrastructure Pattern

```
                    ┌─────────────────────────┐
                    │     Load Balancer RPC   │
                    │   (HAProxy / Nginx)      │
                    └─────────┬───────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │  Primary     │  │  Secondary   │  │  Archival    │
    │  Full Node   │  │  Full Node   │  │  Node        │
    │  (low-lat)   │  │  (failover)  │  │  (analytics) │
    └──────────────┘  └──────────────┘  └──────────────┘
```

- Primary nodes: Serve live RPC requests from the execution path (low-latency read operations).
- Archival node: Serves analytics jobs and Subsquid indexers; never in the execution hot path.
- Failover: HAProxy health checks route around node failures automatically.

---

## 4. Data Flow Architecture

```
External Data Sources
┌─────────────────────────────────────────────────────────────────────┐
│  DeFiLlama  │  CoinGecko  │  CMC  │  CoinMetrics  │  Nansen (P2)  │
│  Dune       │  The Graph  │  Subsquid  │  Glassnode (P2)          │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                    ┌──────────▼───────────┐
                    │   ETL / Normalizer   │  apps/jobs/src/ingest/
                    │   - Schema mapping   │  Normalize to canonical
                    │   - Validation       │  schemas, enrich, dedupe
                    │   - Quality checks   │
                    └──────────┬───────────┘
                               │
          ┌────────────────────┼───────────────────┐
          ▼                    ▼                   ▼
  ┌──────────────┐   ┌──────────────────┐  ┌────────────────┐
  │ TimescaleDB  │   │  Redis Hot Cache │  │  Delta Lake    │
  │ (time-series)│   │  (< 24h window)  │  │  (Parquet S3)  │
  │ OHLCV, OI,  │   │  Latest snapshots│  │  Historical    │
  │ funding,     │   │  for agents      │  │  backtesting   │
  │ on-chain     │   └────────┬─────────┘  │  & RL training │
  └──────────────┘            │            └────────────────┘
                              │
                    ┌─────────▼───────────┐
                    │   Kafka Topics      │
                    │  market.ohlcv       │
                    │  onchain.metrics    │
                    │  defi.protocol      │
                    │  token.fundamentals │
                    │  sentiment.snapshot │
                    └─────────┬───────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    ┌──────────────┐  ┌──────────────┐  ┌────────────┐
    │  Analyst     │  │  RegimeMapper│  │  Quant Val │
    │  Agents      │  │  Component   │  │  Agent     │
    └──────────────┘  └──────────────┘  └────────────┘
```

---

## 5. Agent Integration Map

How analytics feeds map to each agent/component in the trading firm architecture:

| Agent / Component | Primary Data Sources | Update Cadence | Schema |
|---|---|---|---|
| **MarketResearchAgent** | DeFiLlama (TVL, DEX vol), CoinGecko (market caps, categories), Coin Metrics (macro BTC/ETH), Artemis (stablecoin flows) | 1h (protocol), 15m (market) | `MarketContextMemo` |
| **FundamentalAnalyst** | CoinGecko (supply, FDV, volume), CoinMetrics (active addresses, fees), DeFiLlama (protocol revenue) | 4h | `AnalystReport.fundamentals` |
| **TechnicalAnalyst** | HyperLiquid WebSocket (OHLCV, OI, funding), CoinGecko (spot reference) | 1m | `AnalystReport.technicals` |
| **OnChainFlowAnalyst** | Subsquid (custom liquidation/flow indexer), The Graph (DEX swaps, lending), Coin Metrics (exchange flows), Nansen (P2, wallet labeling) | 15m | `AnalystReport.onchain` |
| **SentimentAnalyst** | FlowHunt MCP (social sentiment), CoinGecko (market sentiment gauge) | 15m | `AnalystReport.sentiment` |
| **RegimeMapper** | Coin Metrics (MVRV, realized cap, NVT), Glassnode (P2, HODL waves), DeFiLlama (TVL trend), HyperLiquid (funding/OI) | 1h | `RegimeTag` enum |
| **RiskCouncil** | TimescaleDB (portfolio metrics), Redis (live positions), on-chain node (liquidation price tracking) | real-time | `RiskVote` |
| **SAE Middleware** | Redis (position state), internal risk DB | per-order | `ExecutionDecision` |
| **TreasuryAgent** | CoinGecko/CMC (BTC price), DeFi protocol APY (DeFiLlama yields) | 1h | `TreasuryState` |
| **StrategyTunerAgent** | Delta Lake (historical outcomes), Dune (offline queries), TimescaleDB | overnight | `StrategySpec` |

---

## 6. Service Configuration

### 6.1 Environment Variables

Add to `.env` (see `.env.example`):

```bash
# --- Tier 1: Free/Open APIs ---
DEFILLAMA_API_BASE=https://api.llama.fi
DEFILLAMA_YIELDS_BASE=https://yields.llama.fi
DEFILLAMA_STABLECOINS_BASE=https://stablecoins.llama.fi
COINGECKO_API_BASE=https://api.coingecko.com/api/v3
COINGECKO_API_KEY=                       # Optional; leave blank for free demo key
CMC_API_KEY=                             # CoinMarketCap API key
CMC_API_BASE=https://pro-api.coinmarketcap.com/v1
COINMETRICS_COMMUNITY_BASE=https://community-api.coinmetrics.io/v4
DUNE_API_KEY=                            # Dune Analytics API key

# --- The Graph ---
THEGRAPH_HOSTED_BASE=https://api.thegraph.com/subgraphs/name
THEGRAPH_DECENTRALIZED_GATEWAY=https://gateway.thegraph.com/api
THEGRAPH_API_KEY=                        # Required for decentralized network

# --- Full Node RPCs ---
ETH_RPC_URL=http://ethereum-node:8545
ETH_WS_URL=ws://ethereum-node:8546
ARB_RPC_URL=http://arbitrum-node:8547
ARB_WS_URL=ws://arbitrum-node:8548
OP_RPC_URL=http://optimism-node:8549
BASE_RPC_URL=http://base-node:8550
BTC_RPC_URL=http://bitcoin-node:8332
BTC_RPC_USER=
BTC_RPC_PASS=
BTC_ZMQ_BLOCK=tcp://bitcoin-node:28332
BTC_ZMQ_TX=tcp://bitcoin-node:28333

# --- Tier 2: Activated When Validated ---
NANSEN_API_KEY=                          # Set when Phase 2 signal validated
NANSEN_API_BASE=https://api.nansen.ai/v2
GLASSNODE_API_KEY=                       # Set when Phase 2 regime work starts
GLASSNODE_API_BASE=https://api.glassnode.com/v1
```

---

### 6.2 Docker Compose Services (Analytics Stack)

Add to `docker-compose.yml`:

```yaml
services:
  # --- Node Services ---
  bitcoin-node:
    image: lncm/bitcoind:v27.0
    volumes:
      - bitcoin-data:/data/.bitcoin
      - ./infra/nodes/bitcoin/bitcoin.conf:/data/.bitcoin/bitcoin.conf:ro
    ports:
      - "8332:8332"
      - "28332:28332"
      - "28333:28333"

  ethereum-node:
    image: thorax/erigon:latest
    volumes:
      - erigon-data:/home/erigon/.local/share/erigon
    command: >
      --chain=mainnet
      --http --http.addr=0.0.0.0
      --http.api=eth,net,web3,debug,trace
      --ws

  # --- Indexers ---
  subsquid-processor:
    build: ./infra/subsquid
    environment:
      - DB_URL=postgresql://postgres:${POSTGRES_PASSWORD}@postgres:5432/subsquid
      - RPC_ENDPOINT=${ETH_RPC_URL}

  graph-node:
    image: graphprotocol/graph-node:latest
    environment:
      postgres_host: postgres
      ipfs: https://api.thegraph.com/ipfs/
      ethereum: mainnet:${ETH_RPC_URL}

  # --- Analytics Ingestion Jobs ---
  analytics-ingestor:
    build: ./apps/jobs
    command: python -m src.ingest.scheduler
    environment:
      - DEFILLAMA_API_BASE=${DEFILLAMA_API_BASE}
      - COINGECKO_API_KEY=${COINGECKO_API_KEY}
      - COINMETRICS_COMMUNITY_BASE=${COINMETRICS_COMMUNITY_BASE}
    depends_on:
      - timescaledb
      - redis
      - kafka
```

---

## 7. Schema Reference

Canonical internal schemas that all analytics data is normalized into before agent consumption:

```python
# apps/agents/src/types/analytics.py

from dataclasses import dataclass, field
from typing import List, Optional, Literal
from datetime import datetime

# --- On-Chain Metrics ---
@dataclass
class OnChainMetric:
    asset: str                    # e.g., "BTC", "ETH"
    timestamp: datetime
    source: str                   # e.g., "coinmetrics", "glassnode", "subsquid"
    metric_id: str                # e.g., "realized_cap_usd", "exchange_flow_in"
    value: float
    unit: str
    schema_version: str = "1.0"

# --- DeFi Protocol State ---
@dataclass
class DeFiProtocolState:
    protocol: str                 # e.g., "aave-v3", "uniswap-v3"
    chain: str                    # e.g., "arbitrum", "ethereum"
    timestamp: datetime
    tvl_usd: float
    volume_24h_usd: Optional[float] = None
    fees_24h_usd: Optional[float] = None
    revenue_24h_usd: Optional[float] = None
    source: str = "defillama"
    schema_version: str = "1.0"

# --- Token Fundamentals ---
@dataclass
class TokenFundamentals:
    asset: str
    timestamp: datetime
    price_usd: float
    market_cap_usd: float
    fdv_usd: Optional[float]
    circulating_supply: float
    total_supply: Optional[float]
    volume_24h_usd: float
    price_change_24h_pct: float
    source: str                   # e.g., "coingecko", "coinmarketcap"
    schema_version: str = "1.0"

# --- Market Snapshot ---
@dataclass
class MarketSnapshot:
    timestamp: datetime
    btc_dominance_pct: float
    stablecoin_supply_usd: float  # from DeFiLlama stablecoins
    total_defi_tvl_usd: float     # from DeFiLlama
    total_dex_volume_24h_usd: float
    eth_gas_price_gwei: float
    funding_rate_btc: float       # from HyperLiquid or aggregated
    open_interest_btc_usd: float
    source: str = "aggregated"
    schema_version: str = "1.0"

# --- Regime Tag (output of RegimeMapper) ---
RegimeType = Literal[
    "BULL_TREND",
    "BEAR_TREND",
    "HIGH_VOL_CHOP",
    "LOW_VOL_CHOP",
    "PANIC",
    "EUPHORIA",
    "ACCUMULATION",
    "DISTRIBUTION"
]

@dataclass
class RegimeSnapshot:
    timestamp: datetime
    regime: RegimeType
    confidence: float             # 0.0 - 1.0
    supporting_metrics: List[str]  # list of metric IDs that support this regime
    schema_version: str = "1.0"
```

---

## 8. Operational Guidance

### 8.1 Data Quality Checks

Every analytics ingest job must validate:

```python
# apps/jobs/src/ingest/validators.py

def validate_price_feed(token: str, price_usd: float) -> bool:
    """Cross-validate price across CoinGecko and CMC. Reject if divergence > 0.5%."""
    cg_price = coingecko_client.get_price(token)
    cmc_price = cmc_client.get_price(token)
    divergence = abs(cg_price - cmc_price) / cg_price
    if divergence > 0.005:
        alert("PRICE_DIVERGENCE", token=token, cg=cg_price, cmc=cmc_price)
        return False
    return True

def validate_onchain_metric(metric: OnChainMetric) -> bool:
    """Reject metrics with timestamp older than max_staleness_seconds."""
    max_staleness = {
        "exchange_flow": 3600,   # 1 hour
        "realized_cap": 86400,   # 24 hours
        "hodl_waves": 86400,
    }
    staleness = (datetime.utcnow() - metric.timestamp).seconds
    return staleness < max_staleness.get(metric.metric_id, 3600)
```

### 8.2 Rate Limit Management

Each API client implements token-bucket rate limiting:

```python
# apps/agents/src/tools/rate_limiter.py
import asyncio
import time

class RateLimiter:
    def __init__(self, calls_per_minute: int):
        self.calls_per_minute = calls_per_minute
        self.interval = 60.0 / calls_per_minute
        self._last_call = 0.0

    async def acquire(self):
        now = time.monotonic()
        sleep_time = self.interval - (now - self._last_call)
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)
        self._last_call = time.monotonic()

# Per-service limiters
DEFILLAMA_LIMITER = RateLimiter(calls_per_minute=60)  # conservative
COINGECKO_LIMITER = RateLimiter(calls_per_minute=30)  # free tier
CMC_LIMITER = RateLimiter(calls_per_minute=20)         # Basic plan
COINMETRICS_LIMITER = RateLimiter(calls_per_minute=10) # Community tier
```

### 8.3 Activation / Deactivation of Tier 2 Sources

Tier 2 sources (Nansen, Glassnode) are controlled by the data source policy table in Postgres, which the SAE reads at startup:

```sql
-- Schema for data source policy governance
CREATE TABLE data_source_policies (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(100) NOT NULL,   -- e.g., 'nansen_wallet_flows'
    provider      VARCHAR(50)  NOT NULL,   -- e.g., 'nansen'
    status        VARCHAR(20)  NOT NULL DEFAULT 'inactive',  -- inactive|experimental|active|disabled
    sae_regimes_enabled JSONB,             -- e.g., ["BULL_TREND", "ACCUMULATION"]
    last_evaluated_run_id VARCHAR(100),    -- MLflow run ID
    activation_sharpe_threshold FLOAT,     -- required incremental Sharpe to activate
    current_sharpe_delta FLOAT,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);
```

### 8.4 Prometheus Metrics (Observability)

Each analytics client exposes metrics:

```python
# Prometheus counters/gauges for analytics health
analytics_fetch_total          = Counter('analytics_fetch_total', ['source', 'endpoint', 'status'])
analytics_fetch_latency_seconds = Histogram('analytics_fetch_latency_seconds', ['source'])
analytics_data_staleness_seconds = Gauge('analytics_data_staleness_seconds', ['source', 'metric'])
analytics_price_divergence_pct  = Gauge('analytics_price_divergence_pct', ['asset'])
```

Alerts:
- `analytics_data_staleness_seconds{source="coinmetrics"} > 7200` → WARNING
- `analytics_price_divergence_pct{asset="BTC"} > 0.5` → CRITICAL (halt execution)
- `analytics_fetch_total{status="error"}` rate > 10/min → WARNING

---

## 9. Platform Comparison Table

| Platform | Category | Open Source | Cost | Usefulness (1–5) | Programmatic API | Recommended Action |
|---|---|---|---|---|---|---|
| **DeFiLlama** | DeFi/DEX | ✅ Yes (GitHub) | Free / Pro | 5 | ✅ REST | **Core — integrate now** |
| **The Graph** | Chain Indexing | ✅ Yes | Free / GRT fees | 4 | ✅ GraphQL | **Core — deploy subgraphs** |
| **Subsquid** | Chain Indexing | ✅ Yes | Free (self-hosted) | 4 | ✅ REST | **Core — custom indexers** |
| **CoinGecko** | Market Data | ❌ Proprietary | Free / $129+/mo | 4 | ✅ REST | **Core — token reference data** |
| **CoinMarketCap** | Market Data | ❌ Proprietary | Free / $79+/mo | 3 | ✅ REST | **Core — cross-validation only** |
| **Coin Metrics (Community)** | On-Chain | ❌ Proprietary | Free (community) | 4 | ✅ REST | **Core — BTC/ETH macro inputs** |
| **Dune Analytics** | On-Chain SQL | ❌ Proprietary | Free / $399+/mo | 4 | ✅ REST | **Core — research/prototyping only** |
| **Artemis (Lite)** | Macro/Fundamentals | ❌ Proprietary | Free (terminal) | 3 | ❌ (Pro only) | **Use free terminal for research** |
| **Nansen** | Wallet Analytics | ❌ Proprietary | ~$49+/mo API | 5 | ✅ REST | **Phase 2 — after signal validation** |
| **Glassnode** | BTC/ETH On-Chain | ❌ Proprietary | $39–$999+/mo | 4 | ✅ REST | **Phase 2 — after regime model work** |
| **Artemis Pro** | Macro/Fundamentals | ❌ Proprietary | ~$300/user/mo | 4 | ✅ REST | **Defer — overlaps with Tier 1** |
| **Coin Metrics Pro** | Reference Rates | ❌ Proprietary | Enterprise | 4 | ✅ REST | **Defer — unless SLA required** |
| **CryptoQuant** | BTC/ETH On-Chain | ❌ Proprietary | Paid | 3 | ✅ REST | **Skip — covered by Glassnode** |
| **Santiment** | On-Chain + Social | ❌ Proprietary | Paid | 3 | ✅ REST | **Skip — covered by FlowHunt + NLP** |
| **DappRadar** | Dapp Rankings | ❌ Proprietary | Free/Paid | 2 | ✅ REST | **Skip (use manually as needed)** |
| **Coinglass** | Derivatives | ❌ Proprietary | Free/Paid | 2 | ✅ REST | **Skip — reconstructed from HL feeds** |
| **Chainalysis** | Compliance/AML | ❌ Proprietary | Enterprise | 1 | ✅ REST | **Skip — not relevant to trading** |
| **Lukka** | Fund Accounting | ❌ Proprietary | Enterprise | 1 | ✅ REST | **Skip — fund admin only** |
| **Moralis** | Web3 BaaS | ❌ Proprietary | Free/$49+/mo | 2 | ✅ REST | **Skip — replaced by Subsquid** |
| **Space and Time** | Data Warehouse | Partial | Varies | 2 | ✅ SQL | **Skip — replaced by ClickHouse+Subsquid** |
| **OptiBlack** | Analytics | ❌ Proprietary | Unknown | 1 | Unknown | **Skip — insufficient documentation** |
| **Delphi Digital** | Research | ❌ Proprietary | Institutional | 2 | ❌ | **Skip — human research only** |
| **The Block** | Research/Data | ❌ Proprietary | Institutional | 2 | Partial | **Skip — human research only** |
| **Formo** | Analytics | ❌ Proprietary | Unknown | 1 | Unknown | **Skip** |
| **Investopedia** | Education | ❌ Proprietary | Free | 0 | ❌ | **Skip — not a data source** |

---

*Document version: 1.0.0 — April 2026*  
*Maintainer: Platform & Infrastructure*  
*Review cycle: Quarterly, or when a new Tier 2 platform activation decision is made.*
