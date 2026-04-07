# APP_INFRASTRUCTURE.md

> **Hyperliquid Autonomous Trading Firm — Application Infrastructure Reference**
> Version: 1.0.1 | Last Updated: 2026-04-07

---

## Table of Contents

1. [Overview](#overview)
2. [Infrastructure Philosophy](#infrastructure-philosophy)
3. [Top-Level Architecture](#top-level-architecture)
4. [Hyperliquid DEX Node Cluster](#hyperliquid-dex-node-cluster)
5. [Data & Storage Layer](#data--storage-layer)
6. [AI Agent Platform](#ai-agent-platform)
7. [Application Services](#application-services)
8. [Observability Stack](#observability-stack)
9. [Networking & Edge](#networking--edge)
10. [Public Cloud & External Services](#public-cloud--external-services)
11. [Public API Failover Map](#public-api-failover-map)
12. [Security & Secrets](#security--secrets)
13. [Kubernetes & Container Platform](#kubernetes--container-platform)
14. [Deployment Topology Summary](#deployment-topology-summary)

---

## Overview

This document describes the complete on-premises and hybrid infrastructure required to operate the Hyperliquid Autonomous Trading Firm at institutional scale. It covers all self-hosted services, their roles and interdependencies, the Hyperliquid DEX blockchain node cluster, AI agent runtimes, databases, observability tooling, and edge/cloud integrations.

**Design principles:**

- **Local-first data plane** — All market data, order book feeds, and trading decisions consume local node services. Public endpoints are fallback only for all non-execution paths.
- **Public endpoints for order submission only** — HyperCore trade submission always routes to `api.hyperliquid.xyz`; this cannot be replaced by local infra.
- **Defense in depth** — Every self-hosted critical service has a documented public fallback endpoint listed in the [Public API Failover Map](#public-api-failover-map).
- **Zero-trust networking** — All inter-service communication traverses Tailscale mesh; no service exposes raw ports to the public internet.
- **GitOps** — All K8s workloads are declared in `infra/k8s/` and reconciled by ArgoCD.

---

## Infrastructure Philosophy

| Path | Primary (Self-Hosted) | Fallback (Public / Managed) | Notes |
|---|---|---|---|
| L1 block data | `hl-node` (local) | `api.hyperliquid.xyz` gossip peers | Local preferred; ~100 GB/day log output |
| Order book feed | `order-book-server` (local WS) | `wss://api.hyperliquid.xyz/ws` | Local has L4 full-depth; public is L2 only |
| Info API (margin, positions) | `--serve-info` on `hl-node:3001` | `https://api.hyperliquid.xyz/info` | Local subset only; historical not supported |
| EVM RPC | `hl-node --serve-eth-rpc :3001/evm` | Chainstack / Dwellir managed RPC | Local first; managed RPC as hot standby |
| Historical EVM | `hyper-evm-sync` archive | AWS S3 `hl-mainnet-evm-blocks` | S3 is the upstream source regardless |
| Trade submission | `api.hyperliquid.xyz/exchange` | *(same — cannot be self-hosted)* | Always public; minimize latency via Tokyo co-location |
| LLM inference | Ollama (on-prem GPU) | Anthropic / OpenAI APIs | On-prem for FinBERT/small models; cloud for opus/o3 |
| Analytics dashboard | `hyperliquid-stats` (self-hosted) | Hyperliquid public stats site | Self-hosted for operator-private data |

---

## Top-Level Architecture

```mermaid
graph TB
    subgraph INTERNET["☁️ Public Internet / External Services"]
        HL_API["api.hyperliquid.xyz\n(Trade Submission / Info Fallback)"]
        CF["Cloudflare\n(DNS · WAF · Tunnel)"]
        TG["Tailscale\n(WireGuard Mesh VPN)"]
        AWS["AWS S3\n(hl-mainnet-evm-blocks)"]
        AKASH["Akash Network\n(Overflow Compute)"]
        FLY["Fly.io\n(Geo-Edge Agents)"]
        ANTHRO["Anthropic API\n(Claude Opus/Sonnet)"]
        OPENAI["OpenAI API\n(GPT-4o / o3)"]
        PERP["Perplexity API"]
        VENICE["Venice.ai API"]
        KIMI["Kimi Moonshot API"]
        AGENTMAIL["agentmail.to\n(Alerts / Reports)"]
        SMEM["supermemory.ai\n(Shared Agent Memory)"]
        CHAINSTACK["Chainstack\n(Managed HL RPC Fallback)"]
    end

    subgraph EDGE["🌐 Edge / CDN Layer"]
        CF_TUNNEL["Cloudflare Tunnel\n(Zero-Trust Ingress)"]
        NGINX["nginx / Traefik\n(Reverse Proxy · TLS · Rate Limit)"]
    end

    subgraph K8S["⚙️ On-Prem Kubernetes Cluster (Primary DC — Tokyo-Adjacent)"]
        subgraph HL_NODE_CLUSTER["Hyperliquid DEX Node Cluster"]
            HL_NODE_1["hl-node-1\nnon-validator\n--write-fills\n--write-order-statuses\n--write-raw-book-diffs\n--batch-by-block\n--serve-info\n--serve-eth-rpc"]
            HL_NODE_2["hl-node-2\nnon-validator\n(HA replica)"]
            OBS["order-book-server\n:8000 WebSocket\nL2 · L4 Book"]
            PRUNER["node-pruner\n(log rotation cron)"]
            MEMPOOL["mempool-stream\n(split_client_blocks)"]
            EVM_SYNC["hyper-evm-sync\n(archive node)"]
            BLOCK_IMP["block-importer\n(bootstrap batch job)"]
        end

        subgraph DATA_LAYER["Data & Storage Layer"]
            KAFKA["Apache Kafka\n(Event Bus)"]
            TIMESCALE["TimescaleDB\n(Tick · Funding · OI)"]
            POSTGRES["PostgreSQL\n(DecisionTrace · Audit · Prompt Policies)"]
            REDIS["Redis\n(24h State Cache · Rate Control)"]
            MILVUS["Milvus\n(Vector Store · RAG)"]
            DELTA["MinIO / Delta Lake\n(Columnar History · RL Training)"]
            STATS_DB["PostgreSQL\n(hyperliquid-stats)"]
        end

        subgraph AGENT_PLATFORM["AI Agent Platform"]
            ORCH["orchestrator-api\n(Node/TS — Cycle Coordinator)"]
            AGENTS["agents-svc\n(Python — TradingAgents)"]
            SAE["sae-engine\n(Node/TS — Hard Safety Gates)"]
            EXECUTORS["executors-svc\n(Python — HL Paper/Live)"]
            TREASURY["treasury-svc\n(Python — BTC→Stable)"]
            OPTIMIZER["optimizer-agent\n(Python — Off-path RL/OPRO)"]
            JOBS["jobs-svc\n(Python — Backtest · Ablation · Prompt Scoring)"]
            ELIZA["ElizaOS\n(Web3 Agent Runtime)"]
            INTELLICLAW["IntelliClaw\n(Market Intel Engine)"]
            OPENCLAW["OpenClaw / MultiClawCore\n(Control Plane · HITL)"]
        end

        subgraph OBS_STACK["Observability Stack"]
            PROM["Prometheus\n(Metrics Scrape)"]
            GRAFANA["Grafana\n(Dashboards)"]
            LOKI["Loki\n(Log Aggregation)"]
            TEMPO["Tempo\n(Distributed Traces)"]
            ALERT["Alertmanager\n(PagerDuty · Slack · agentmail)"]
            MLFLOW["MLflow\n(Experiment Tracking)"]
        end

        subgraph APP_SERVICES["Application Services"]
            DASHBOARD["dashboard\n(Next.js — Decisions · Governance · PnL)"]
            OPENWEBUI["Open WebUI\n(LLM Management UI)"]
            HL_STATS["hyperliquid-stats\n(FastAPI + PostgreSQL)"]
            HL_STATS_WEB["hyperliquid-stats-web\n(React Frontend)"]
            OLLAMA["Ollama\n(Local LLM Inference · FinBERT · Nomic-Embed)"]
            REGISTRY["Harbor / GHCR\n(Container Registry)"]
            ARGOCD["ArgoCD\n(GitOps Controller)"]
            RANCHER["Rancher / Lens\n(K8s Management Plane)"]
        end
    end

    subgraph BACKUP_DC["🔁 Secondary DC / Edge Node (Tailscale-Connected)"]
        HL_NODE_3["hl-node-3\nnon-validator\n(disaster recovery)"]
        PG_REPLICA["PostgreSQL Replica"]
        KAFKA_MIRROR["Kafka MirrorMaker"]
    end

    CF --> CF_TUNNEL --> NGINX
    NGINX --> DASHBOARD
    NGINX --> OPENWEBUI
    NGINX --> HL_STATS_WEB
    NGINX --> ARGOCD
    NGINX --> GRAFANA

    HL_NODE_1 --> OBS
    HL_NODE_1 --> KAFKA
    HL_NODE_2 --> KAFKA
    OBS --> KAFKA

    KAFKA --> AGENTS
    KAFKA --> TIMESCALE
    KAFKA --> REDIS

    AGENTS --> SAE
    SAE --> EXECUTORS
    EXECUTORS --> HL_API

    ORCH --> AGENTS
    ORCH --> SAE
    ORCH --> TREASURY
    ORCH --> OPENCLAW

    OPENCLAW --> ORCH

    INTELLICLAW --> AGENTS
    ELIZA --> ORCH

    AGENTS --> POSTGRES
    AGENTS --> MILVUS
    TREASURY --> POSTGRES
    OPTIMIZER --> POSTGRES
    OPTIMIZER --> DELTA

    PROM --> GRAFANA
    LOKI --> GRAFANA
    TEMPO --> GRAFANA
    ALERT --> AGENTMAIL

    EVM_SYNC --> AWS
    BLOCK_IMP --> HL_NODE_1

    TG --> K8S
    TG --> BACKUP_DC

    HL_NODE_1 -. "failover" .-> HL_API
    OBS -. "failover" .-> HL_API
    EXECUTORS --> HL_API

    AGENTS --> ANTHRO
    AGENTS --> OPENAI
    AGENTS --> PERP
    AGENTS --> VENICE
    AGENTS --> KIMI
    AGENTS --> SMEM

    JOBS --> MLFLOW
    JOBS --> DELTA

    ARGOCD --> K8S
    REGISTRY --> K8S
```

---

## Hyperliquid DEX Node Cluster

This cluster is the core data plane for all market data. All agent services consume from here rather than public endpoints.

```mermaid
graph LR
    subgraph PEERS["Mainnet Gossip Peers (port 4001/4002)"]
        P1["ASXN 64.31.48.111\n(Tokyo)"]
        P2["Imperator 23.81.40.69\n(Tokyo)"]
        P3["Hypurrscan 13.230.78.76\n(Tokyo)"]
    end

    subgraph NODES["Local hl-node Cluster"]
        N1["hl-node-1 (primary)\nflags: --write-fills\n--write-order-statuses\n--write-raw-book-diffs\n--batch-by-block\n--serve-info :3001/info\n--serve-eth-rpc :3001/evm"]
        N2["hl-node-2 (HA replica)\nflags: --write-fills\n--write-order-statuses\n--batch-by-block"]
    end

    subgraph DERIVED["Derived Services (reads from node output files)"]
        OBS["order-book-server\n:8000 WS\nL2 / L4 Book · Trades"]
        PRUNER["node-pruner\ncron — rotates ~/hl/data\n~100 GB/day"]
        MEMPOOL["mempool-stream\nsplit_client_blocks: true\n~/hl/data/mempool_txs"]
    end

    subgraph ARCHIVE["Historical / Archive"]
        EVM_SYNC["hyper-evm-sync\n(PoC archive node)\nreplay from genesis"]
        BLOCK_IMP["block-importer\n(batch job — bootstrap\nhistorical EVM blocks)"]
        S3["AWS S3\nhl-mainnet-evm-blocks\n(requester-pays)"]
    end

    subgraph LOCAL_API["Local API Endpoints (consumed by agents)"]
        INFO["http://hl-node-1:3001/info\n(clearinghouseState, openOrders,\nactiveAssetData, marginTable, ...)"]
        EVM_RPC["http://hl-node-1:3001/evm\n(eth_getBlockByNumber, ...)"]
        OB_WS["ws://order-book-server:8000\n(l2book, trades, l4book)"]
    end

    PEERS --> N1
    PEERS --> N2
    N1 --> OBS
    N1 --> PRUNER
    N1 --> MEMPOOL
    N1 --> INFO
    N1 --> EVM_RPC
    OBS --> OB_WS
    EVM_SYNC --> S3
    BLOCK_IMP --> N1

    style N1 fill:#1a4a2e,color:#fff
    style N2 fill:#1a4a2e,color:#fff
    style S3 fill:#3b2a10,color:#fff
```

### Node Hardware Requirements

| Role | vCPUs | RAM | Storage | Network |
|---|---|---|---|---|
| `hl-node` non-validator | 16 | 64 GB | 500 GB NVMe SSD | Ports 4001/4002 open, low-latency to Tokyo |
| `order-book-server` | 4 | 16 GB | 50 GB | Same host or same rack as `hl-node` |
| `hyper-evm-sync` | 8 | 32 GB | 2 TB NVMe SSD | High throughput (S3 sync) |

> ⚠️ **Caveat:** `order-book-server` is a community-contributed repo, not written by Hyperliquid Labs. It auto-exits on state desync; configure a K8s liveness probe or systemd `Restart=on-failure` for HA. It does not support spot order books or untriggered trigger orders.

---

## Data & Storage Layer

```mermaid
graph TD
    subgraph SOURCES["Event Sources"]
        NODE_FILES["hl-node output files\n~/hl/data/node_fills\n~/hl/data/node_order_statuses\n~/hl/data/node_raw_book_diffs"]
        OB_WS["order-book-server\nWebSocket"]
        INTEL["IntelliClaw\n(sentiment · news · onchain)"]
        EXTERNAL["External MCPs\nCoinGecko · Dune · CoinMarketCap\nGlassnode · Pyth · Bankr"]
    end

    subgraph STREAMING["Streaming Bus"]
        KAFKA["Apache Kafka\nTopics:\n  market.ticks\n  market.orderbook\n  agent.tasks\n  agent.reports\n  execution.fills\n  treasury.events\n  governance.events"]
        FLINK["Apache Flink (optional)\nor Kafka Streams\n(normalization · enrichment)"]
    end

    subgraph STORES["Persistent Stores"]
        TIMESCALE["TimescaleDB\n(tick · OHLCV · funding\nrate · OI · liquidity)"]
        POSTGRES["PostgreSQL\n(DecisionTrace · audit log\nprompt policies · strategies\ntreasury events · HITL rules)"]
        REDIS["Redis\n(24h hot state cache\nrate control · session)"]
        MILVUS["Milvus / FAISS\n(vector embeddings\nRAG context store)"]
        DELTA["MinIO + Delta Lake\n(Parquet columnar history\nRL training · strategy outcomes)"]
        STATS_DB["PostgreSQL (stats)\n(non_mm_trades\nliquidations · funding\naccount_values)"]
    end

    subgraph BATCH["Batch / S3 Sources"]
        S3["AWS S3\nhl-mainnet-evm-blocks\nhyperliquid-stats public buckets"]
    end

    NODE_FILES --> KAFKA
    OB_WS --> KAFKA
    INTEL --> KAFKA
    EXTERNAL --> KAFKA
    KAFKA --> FLINK
    FLINK --> TIMESCALE
    FLINK --> POSTGRES
    KAFKA --> REDIS
    S3 --> STATS_DB
    S3 --> DELTA

    TIMESCALE --> MILVUS
    POSTGRES --> DELTA
```

---

## AI Agent Platform

```mermaid
flowchart TB
    subgraph CONTROL["Control Plane"]
        OPENCLAW["OpenClaw / MultiClawCore\n(HITL · governance · strategy lifecycle\ncycle trigger · halt/resume · policy approval)"]
    end

    subgraph ORCH_SVC["Orchestrator API (Node/TS)"]
        CYCLE["CycleRunner\n(11-stage pipeline)"]
        STATE["Shared Typed State Store\n(GlobalAgentState)"]
        BUS["Internal Event Bus"]
        HITL_GATE["HITL Gate\n(Clawvisor ruleset eval)"]
    end

    subgraph AGENTS_SVC["agents-svc (Python — TradingAgents)"]
        MA["MarketAnalyst\n(OHLCV · OB · funding)"]
        NA["NewsAnalyst\n(IntelliClaw · agentmail)"]
        FA["FundamentalAnalyst\n(Dune · Glassnode)"]
        SA["SentimentAnalyst\n(bot-filtered)"]
        OCA["OnChainFlowAnalyst\n(vault flows · liquidation map)"]
        BULL["BullResearcher"]
        BEAR["BearResearcher"]
        FAC["DebateFacilitator"]
        TR["TraderAgent"]
        RA["RiskAgent-Aggressive"]
        RN["RiskAgent-Neutral"]
        RC_C["RiskAgent-Conservative"]
        FM["FundManagerAgent"]
        ATLAS_OPT["PromptOptimizer\n(ATLAS AdaptiveOPRO\noff-path · daily job)"]
    end

    subgraph SAE_SVC["sae-engine (Node/TS — deterministic, no LLM)"]
        CHECK["Policy Checks (in order):\n1. Stale data gate\n2. Position limits\n3. Leverage caps\n4. Daily loss limit\n5. Max drawdown\n6. Liquidity gate\n7. Correlation gate\n8. Funding rate gate\n9. Event blackout\n10. Regime check"]
        STAGE["buildStagedExecution\n(TWAP · VWAP · POV · Iceberg)"]
        RL_EXE["RLExecutionAgent\n(PPO · slice timing\nfrom OB microstructure)"]
    end

    subgraph EXECUTORS_SVC["executors-svc (Python)"]
        HL_PAPER["HyperLiquidPaper\n(paper mode)"]
        HL_LIVE["HyperLiquidLive\n(live mode)"]
        RECONCILE["FillReconciler\n(portfolio state · PnL · exposure)"]
    end

    subgraph SUPPORT_AGENTS["Support Services"]
        TREASURY["treasury-svc\n(BTC→Stable · TWAP conversion\nHITL gate for large conversions)"]
        OPTIMIZER["optimizer-agent\n(off-path · DecisionTrace analysis\nproposal → governance queue)"]
        INTELLICLAW["IntelliClaw\n(market intel engine · research snapshots)"]
        ELIZA["ElizaOS\n(Web3 agent runtime · on-chain actions)"]
        JOBS["jobs-svc\n(backtest · ablation · prompt scoring\nRL policy training · nightly OPRO)"]
    end

    subgraph LLM_ROUTING["LLM Routing (model-routing.yaml)"]
        OLLAMA["Ollama (on-prem GPU)\nFinBERT · nomic-embed\nsmall extraction tasks"]
        HAIKU["Claude Haiku / GPT-4o-mini\n(news summary · high-volume)"]
        SONNET["Claude Sonnet / GPT-4o\n(analyst synthesis)"]
        OPUS["Claude Opus / o3\n(debate · trader · fund manager)"]
    end

    OPENCLAW --> ORCH_SVC
    CYCLE --> MA
    CYCLE --> NA
    CYCLE --> FA
    CYCLE --> SA
    CYCLE --> OCA
    MA --> BULL
    NA --> BULL
    FA --> BULL
    SA --> BULL
    OCA --> BULL
    MA --> BEAR
    NA --> BEAR
    FA --> BEAR
    SA --> BEAR
    OCA --> BEAR
    BULL --> FAC
    BEAR --> FAC
    FAC --> TR
    TR --> RA
    TR --> RN
    TR --> RC_C
    RA --> FM
    RN --> FM
    RC_C --> FM
    FM --> HITL_GATE
    HITL_GATE --> SAE_SVC
    SAE_SVC --> EXECUTORS_SVC
    EXECUTORS_SVC --> RECONCILE
    RECONCILE --> STATE

    AGENTS_SVC --> OLLAMA
    AGENTS_SVC --> HAIKU
    AGENTS_SVC --> SONNET
    AGENTS_SVC --> OPUS
    INTELLICLAW --> AGENTS_SVC
    ELIZA --> ORCH_SVC
    TREASURY --> ORCH_SVC
    OPTIMIZER --> ORCH_SVC
    JOBS --> ATLAS_OPT
```

---

## Application Services

```mermaid
graph LR
    NGINX["nginx Ingress\n(Reverse Proxy · TLS)"]

    subgraph FRONTEND["Web Frontends"]
        DASH["dashboard\n(Next.js :3000)\nDecisions · Governance · PnL\nDecisionTrace · Prompt Policies"]
        HL_STATS_WEB["hyperliquid-stats-web\n(React :3001)\nPublic analytics frontend"]
        OPENWEBUI["Open WebUI\n(:8080)\nLLM model management\nOllama interface"]
    end

    subgraph BACKEND_SVC["Backend APIs"]
        HL_STATS_API["hyperliquid-stats\n(FastAPI :8000)\nAnalytics endpoints\nPostgreSQL backed"]
        ORCH_API["orchestrator-api\n(Node/TS :4000)\nCycle management\nHTTP + WebSocket"]
    end

    subgraph INFRA_MGMT["Infrastructure Management"]
        ARGOCD["ArgoCD\n(:8080/argocd)\nGitOps reconciliation"]
        RANCHER["Rancher\n(:443)\nK8s cluster management"]
        REGISTRY["Harbor / GHCR\n(Container Registry)"]
        PORTAINER["Portainer (optional)\nDocker management"]
    end

    subgraph AI_MGMT["AI / ML Management"]
        MLFLOW["MLflow\n(:5000)\nExperiment tracking\nmodel versioning"]
        OLLAMA_SVC["Ollama\n(:11434)\nLocal model serving"]
        GRAFANA_SVC["Grafana\n(:3000)\nObservability dashboards"]
    end

    NGINX --> DASH
    NGINX --> HL_STATS_WEB
    NGINX --> OPENWEBUI
    NGINX --> ARGOCD
    NGINX --> RANCHER
    NGINX --> GRAFANA_SVC
    NGINX --> MLFLOW

    DASH --> ORCH_API
    HL_STATS_WEB --> HL_STATS_API
    OPENWEBUI --> OLLAMA_SVC
```

---

## Observability Stack

```mermaid
graph TB
    subgraph SCRAPE["Metric Sources"]
        K8S_METRICS["kube-state-metrics\nnode-exporter"]
        APP_METRICS["App /metrics endpoints\n(orchestrator-api · sae-engine\nagents-svc · executors · treasury)"]
        HL_METRICS["hl-node custom exporter\n(block height · gossip peers\nfill lag · stale data age)"]
    end

    subgraph CORE_OBS["Core Observability"]
        PROM["Prometheus\n(metrics · retention 30d)"]
        LOKI["Loki\n(log aggregation\nvia Promtail / Alloy)"]
        TEMPO["Tempo\n(distributed traces\nOpenTelemetry)"]
        GRAFANA["Grafana\n(unified dashboards:\n  Trading PnL\n  SAE Rejection Rates\n  Agent Cycle Latency\n  Node Health\n  Treasury Conversions\n  HITL Approval Queue)"]
    end

    subgraph ALERT["Alerting"]
        ALERTMGR["Alertmanager"]
        SLACK["Slack\n(ops channel)"]
        AGENTMAIL["agentmail.to\n(performance reports\ntrading alerts)"]
        PAGERDUTY["PagerDuty (optional)\n(critical infra alerts)"]
    end

    subgraph EXPERIMENT["ML Experiment Tracking"]
        MLFLOW["MLflow\n(strategy experiments\nprompt-policy versions\nbacktest results)"]
    end

    K8S_METRICS --> PROM
    APP_METRICS --> PROM
    HL_METRICS --> PROM
    PROM --> GRAFANA
    LOKI --> GRAFANA
    TEMPO --> GRAFANA
    PROM --> ALERTMGR
    ALERTMGR --> SLACK
    ALERTMGR --> AGENTMAIL
    ALERTMGR --> PAGERDUTY
    JOBS_SVC["jobs-svc"] --> MLFLOW
    MLFLOW --> GRAFANA
```

### Key Alert Thresholds

| Alert | Condition | Severity |
|---|---|---|
| `trading.drawdown.critical` | Portfolio drawdown > 6% | Critical |
| `safety.staledata` | Market snapshot age > 90s in live mode | Critical |
| `safety.saerejectionspike` | SAE rejection rate > 30% over 10 cycles | High |
| `process.cyclelatency` | Cycle P95 latency > 8s | High |
| `infra.agentservicedown` | Agent service health check fails 30s | Critical |
| `treasury.conversionfailed` | Treasury conversion not filled within 30 min | High |
| `node.gossiplag` | `hl-node` block height > 100 behind peers | Critical |
| `node.diskpressure` | `~/hl/data` partition > 80% full | High |

---

## Networking & Edge

```mermaid
graph TB
    subgraph INTERNET_USERS["Operators / External Access"]
        OPS["Operator Browser\n(dashboard · Grafana · ArgoCD)"]
        OPENCLAW_CLI["OpenClaw CLI / App"]
    end

    subgraph EDGE["Edge / Access Layer"]
        CF_DNS["Cloudflare DNS\n(authoritative · proxied)"]
        CF_WAF["Cloudflare WAF\n(DDoS protection · IP rules)"]
        CF_TUNNEL["Cloudflare Tunnel\n(cloudflared — zero-trust ingress\nno open inbound ports on-prem)"]
    end

    subgraph TAILSCALE_MESH["Tailscale Zero-Trust Mesh (WireGuard)"]
        TS_EXIT["Tailscale Exit Node\n(on-prem gateway)"]
        TS_K8S["Tailscale K8s Operator\n(in-cluster sidecar injection)"]
        TS_REMOTE["Tailscale on remote\noperator devices"]
        TS_AKASH["Tailscale on Akash\noverflow nodes"]
        TS_FLY["Tailscale on Fly.io\nedge agents"]
    end

    subgraph ON_PREM_NET["On-Prem Network"]
        NGINX_INGRESS["nginx Ingress Controller\n(K8s ingress · TLS termination\nrate limiting · WebSocket proxy)"]
        API_GW["API Gateway\n(Envoy / Traefik\nmulti-agent fan-out\nWS connection multiplexing\ncircuit breaking)"]
    end

    subgraph K8S_SVCS["K8s Services"]
        ORCH_API["orchestrator-api"]
        HL_NODE_INFO["hl-node :3001/info"]
        OB_WS["order-book-server :8000"]
        K8S_PODS["K8s Pods\n(inter-pod mTLS)"]
        AKASH_NODES["Akash Worker Nodes"]
        FLY_NODES["Fly.io Machines"]
    end

    OPS --> CF_DNS
    CF_DNS --> CF_WAF
    CF_WAF --> CF_TUNNEL
    OPENCLAW_CLI --> TS_REMOTE
    TS_REMOTE --> TS_EXIT
    CF_TUNNEL --> NGINX_INGRESS
    NGINX_INGRESS --> API_GW
    API_GW --> ORCH_API
    API_GW --> HL_NODE_INFO
    API_GW --> OB_WS

    TS_K8S -.-> K8S_PODS
    TS_AKASH -.-> AKASH_NODES
    TS_FLY -.-> FLY_NODES
```

---

## Public Cloud & External Services

```mermaid
graph LR
    subgraph AWS["AWS"]
        S3_EVM["S3: hl-mainnet-evm-blocks\n(EVM historical blocks\nrequester-pays)"]
        S3_STATS["S3: hyperliquid public data\n(daily stats ingest\nfor hyperliquid-stats)"]
    end

    subgraph CLOUDFLARE["Cloudflare"]
        CF_DNS2["DNS / Proxy"]
        CF_TUNNEL2["Cloudflare Tunnel\n(zero-trust ingress)"]
        CF_PAGES["Cloudflare Pages (optional)\npublic-facing reporting site"]
    end

    subgraph AKASH["Akash Network"]
        AK_COMPUTE["Overflow GPU Compute\n(large batch inference\nRL training jobs\nbacktest parallelism)"]
    end

    subgraph FLY["Fly.io"]
        FLY_EDGE["Geo-edge agent replicas\n(low-latency Tokyo presence\nfor execution agents)"]
    end

    subgraph TAILSCALE_EXT["Tailscale"]
        TS_VPN["WireGuard Mesh VPN\n(on-prem to cloud to operator\nzero-trust access control)"]
    end

    subgraph LLM_PROVIDERS["LLM / AI APIs"]
        ANTHRO2["Anthropic\n(Claude Opus · Sonnet · Haiku)"]
        OPENAI2["OpenAI\n(GPT-4o · o3 · text-embedding)"]
        PERP2["Perplexity API\n(web research tool for agents)"]
        VENICE2["Venice.ai\n(privacy-preserving inference)"]
        KIMI2["Kimi Moonshot AI\n(supplemental reasoning)"]
    end

    subgraph AGENT_SAAS["Agent SaaS / Memory"]
        SMEM2["supermemory.ai\n(shared persistent agent memory\ninter-agent knowledge base)"]
        AGENTMAIL2["agentmail.to\n(trading alerts · PnL reports\noperator email system)"]
    end

    subgraph MKT_DATA["Market Data Providers (via MCP)"]
        COINGECKO["CoinGecko API"]
        CMC["CoinMarketCap MCP"]
        DUNE["Dune Analytics MCP"]
        GLASSNODE["Glassnode\n(on-chain flows)"]
        PYTH["Pyth Network\n(price oracle)"]
        DEFI_LLAMA["DeFiLlama API"]
        STAKING_RWD["StakingRewards API"]
    end

    subgraph MANAGED_RPC["Managed HL RPC (Fallback)"]
        CHAINSTACK2["Chainstack\n(dedicated HL RPC\nEVM fallback)"]
        DWELLIR["Dwellir\n(dedicated HL RPC)"]
        IMPERATOR["Imperator HypeRPC\n(Tokyo co-located)"]
    end

    JOBS_SVC2["jobs-svc"] --> AWS
    EVM_SYNC2["hyper-evm-sync"] --> S3_EVM
    HL_STATS2["hyperliquid-stats"] --> S3_STATS

    AGENT_SVC2["agents-svc"] --> ANTHRO2
    AGENT_SVC2 --> OPENAI2
    AGENT_SVC2 --> PERP2
    AGENT_SVC2 --> VENICE2
    AGENT_SVC2 --> KIMI2
    AGENT_SVC2 --> SMEM2
    ALERTMGR2["Alertmanager"] --> AGENTMAIL2

    AGENT_SVC2 --> COINGECKO
    AGENT_SVC2 --> CMC
    AGENT_SVC2 --> DUNE
    AGENT_SVC2 --> GLASSNODE
    AGENT_SVC2 --> PYTH
    AGENT_SVC2 --> DEFI_LLAMA
    AGENT_SVC2 --> STAKING_RWD

    HL_NODE_1_EXT["hl-node-1"] -. "fallback if local down" .-> CHAINSTACK2
    HL_NODE_1_EXT -. "fallback if local down" .-> DWELLIR
    HL_NODE_1_EXT -. "fallback if local down" .-> IMPERATOR
    EXECUTORS_SVC2["executors-svc"] --> HL_API_EXT["api.hyperliquid.xyz\n(always public)"]

    JOBS_SVC2 -. "overflow GPU" .-> AK_COMPUTE
    EXECUTORS_SVC2 -. "geo-edge exec" .-> FLY_EDGE
```

---

## Public API Failover Map

> All services should implement retry logic with exponential backoff before switching to fallback. Circuit breaker pattern required at the API gateway layer.

```mermaid
flowchart LR
    subgraph LOCAL["Primary (Self-Hosted)"]
        L1["hl-node :3001/info"]
        L2["order-book-server :8000"]
        L3["hl-node :3001/evm"]
        L4["Ollama (local GPU)"]
        L5["TimescaleDB (local)"]
        L6["hl-node gossip stream"]
    end

    subgraph FALLBACK["Fallback (Public / Managed)"]
        F1["https://api.hyperliquid.xyz/info"]
        F2["wss://api.hyperliquid.xyz/ws"]
        F3["Chainstack / Dwellir managed RPC"]
        F4["Anthropic API / OpenAI API"]
        F5["Hyperliquid public S3 stats buckets"]
        F6["Community gossip root peers\n(ASXN · Imperator · B-Harvest)"]
    end

    L1 -. "node down or stale data gt 90s" .-> F1
    L2 -. "state desync or auto-exit" .-> F2
    L3 -. "EVM RPC unavailable" .-> F3
    L4 -. "GPU OOM or node failure" .-> F4
    L5 -. "DB failure" .-> F5
    L6 -. "peer desync" .-> F6
```

| Service | Primary | Fallback | Trigger Condition | Notes |
|---|---|---|---|---|
| Info API | `hl-node:3001/info` | `api.hyperliquid.xyz/info` | Snapshot age > 90s or node crash | Subset of requests only on local |
| L2/L4 Order Book | `order-book-server:8000` | `wss://api.hyperliquid.xyz/ws` | Auto-exit / desync | Public is L2 only; L4 not available |
| EVM JSON-RPC | `hl-node:3001/evm` | Chainstack / Dwellir | RPC error / timeout | Managed RPC has broader method support |
| Block data stream | Local gossip | Community root peers | Peer count < 2 | See gossip peer list in node README |
| LLM inference | Ollama on-prem | Anthropic / OpenAI | OOM / node failure | On-prem for FinBERT; cloud for opus/o3 |
| Trade submission | `api.hyperliquid.xyz/exchange` | *(no alternative)* | N/A | Always public; cannot be self-hosted |
| Historical stats | `hyperliquid-stats` (local) | Public HL stats site | DB failure | Stats serve lagged data only (daily cron) |

---

## Security & Secrets

```mermaid
graph TB
    subgraph SECRETS["Secrets Management"]
        VAULT["HashiCorp Vault\n(or K8s Secrets + SOPS)\nAPI keys · wallet keys\nDB credentials · JWT secrets"]
        NITRO["NitroKey HSM 2\n(hardware wallet · ElizaOS signer\nTEE for critical keys)"]
    end

    subgraph NETWORK_SEC["Network Security"]
        TAILSCALE_ACL["Tailscale ACL Policies\n(least-privilege mesh access)"]
        CF_ZERO["Cloudflare Zero Trust\n(identity-aware access\nfor operator UI access)"]
        MTLS["mTLS between services\n(Tailscale + cert-manager)"]
    end

    subgraph APP_SEC["Application Security"]
        CODEOWNERS["CODEOWNERS gate\n(LLM agents cannot modify\nlocked files: SAE · agent core\nstrategy base)"]
        AUDIT_LOG["Immutable Audit Log\n(PostgreSQL · DecisionTrace\nall decisions chain-of-custody)"]
        READONLY_KEYS["Read-only API keys\nfor research/monitoring;\nseparate trading keys"]
        CLAWSEC["prompt.security/clawsec\n(prompt injection hardening)"]
    end

    subgraph CONSUMERS["Secret Consumers"]
        K8S_PODS["K8s pods\n(via Vault Agent Sidecar\nor External Secrets Operator)"]
        ELIZA_SVC["ElizaOS\n(on-chain signing)"]
        EXECUTORS_SVC["executors-svc\n(live trade signing)"]
        ALL_SERVICES["All inter-service traffic"]
        OPERATOR_ACCESS["Operator browser access\nto dashboards"]
    end

    VAULT --> K8S_PODS
    NITRO --> ELIZA_SVC
    NITRO --> EXECUTORS_SVC
    TAILSCALE_ACL --> ALL_SERVICES
    CF_ZERO --> OPERATOR_ACCESS
    MTLS --> ALL_SERVICES
```

---

## Kubernetes & Container Platform

```mermaid
graph TB
    subgraph GITOPS["GitOps Source of Truth"]
        GIT_REPO["GitHub: enuno/hyperliquid-trading-firm\ninfra/k8s/base/ — base manifests\ninfra/k8s/overlays/dev|prod/\ninfra/argocd/ — ArgoCD applications"]
    end

    subgraph ARGOCD_CTRL["ArgoCD GitOps Controller"]
        ARGOCD_APP["ArgoCD Application CRDs\n(one per service\nsync wave ordering:\n  1. databases\n  2. kafka\n  3. hl-nodes\n  4. agents\n  5. dashboards)"]
    end

    subgraph K8S_CLUSTER["Kubernetes Cluster"]
        subgraph NS_INFRA["namespace: hl-infra"]
            HL_NODE_DEPLOY["hl-node-1 StatefulSet\nhl-node-2 StatefulSet\norder-book-server Deployment\nblock-importer Job\nhyper-evm-sync StatefulSet\nnode-pruner CronJob"]
        end

        subgraph NS_DATA["namespace: hl-data"]
            KAFKA_DEPLOY["Kafka StatefulSet\n(3 brokers)"]
            PG_DEPLOY["PostgreSQL StatefulSet\n(primary + replica)"]
            TIMESCALE_DEPLOY["TimescaleDB StatefulSet"]
            REDIS_DEPLOY["Redis StatefulSet"]
            MILVUS_DEPLOY["Milvus Deployment"]
            MINIO_DEPLOY["MinIO StatefulSet"]
        end

        subgraph NS_AGENTS["namespace: hl-agents"]
            ORCH_DEPLOY["orchestrator-api Deployment"]
            AGENTS_DEPLOY["agents-svc Deployment\n(HPA: scale on Kafka consumer lag\nvia KEDA)"]
            SAE_DEPLOY["sae-engine Deployment\n(single replica — deterministic)"]
            EXEC_DEPLOY["executors-svc Deployment"]
            TREASURY_DEPLOY["treasury-svc Deployment"]
            OPTIMIZER_DEPLOY["optimizer-agent Deployment\n(low priority · batch)"]
            ELIZA_DEPLOY["ElizaOS Deployment"]
            INTELLICLAW_DEPLOY["IntelliClaw Deployment"]
            OPENCLAW_DEPLOY["OpenClaw / MultiClawCore\nDeployment"]
        end

        subgraph NS_OBS["namespace: hl-observability"]
            PROM_DEPLOY["Prometheus StatefulSet"]
            GRAFANA_DEPLOY["Grafana Deployment"]
            LOKI_DEPLOY["Loki StatefulSet"]
            TEMPO_DEPLOY["Tempo Deployment"]
            ALERTMGR_DEPLOY["Alertmanager Deployment"]
            MLFLOW_DEPLOY["MLflow Deployment"]
        end

        subgraph NS_APP["namespace: hl-apps"]
            DASH_DEPLOY["dashboard Deployment\n(Next.js)"]
            HL_STATS_DEPLOY["hyperliquid-stats Deployment\n(FastAPI)"]
            HL_STATS_WEB_DEPLOY["hyperliquid-stats-web Deployment\n(React)"]
            OLLAMA_DEPLOY["Ollama Deployment\n(GPU nodeSelector)"]
            OPENWEBUI_DEPLOY["Open WebUI Deployment"]
        end

        subgraph NS_PLATFORM["namespace: hl-platform"]
            ARGOCD_DEPLOY["ArgoCD Deployment"]
            RANCHER_DEPLOY["Rancher Deployment"]
            HARBOR_DEPLOY["Harbor Registry\n(or GHCR mirror)"]
            NGINX_CTRL["nginx Ingress Controller"]
            CERT_MGR["cert-manager\n(Let's Encrypt · internal CA)"]
            EXTSECRTS["External Secrets Operator\n(Vault integration)"]
            KEDA_CTRL["KEDA\n(event-driven autoscaling)"]
            TAILSCALE_OP["Tailscale K8s Operator"]
        end
    end

    GIT_REPO --> ARGOCD_CTRL
    ARGOCD_CTRL --> NS_INFRA
    ARGOCD_CTRL --> NS_DATA
    ARGOCD_CTRL --> NS_AGENTS
    ARGOCD_CTRL --> NS_OBS
    ARGOCD_CTRL --> NS_APP
    ARGOCD_CTRL --> NS_PLATFORM
```

---

## Deployment Topology Summary

```mermaid
graph TB
    subgraph PRIMARY_DC["Primary On-Prem DC (Tokyo-Adjacent — Co-Located or Bare Metal)"]
        PRIMARY_K8S["K8s Cluster (Primary)\n(hl-infra · hl-data · hl-agents\nhl-observability · hl-apps · hl-platform)"]
    end

    subgraph SECONDARY_DC["Secondary DC / Bare Metal (DR Site — Tailscale-Connected)"]
        SEC_NODE["hl-node-3 (DR non-validator)"]
        SEC_PG["PostgreSQL Replica"]
        SEC_KAFKA["Kafka MirrorMaker 2"]
    end

    subgraph EDGE_CLOUD["Edge / Cloud Compute"]
        FLY_EXEC["Fly.io Tokyo\n(execution agent thin replicas)"]
        AKASH_BATCH["Akash\n(overflow GPU batch\nRL training · ablations)"]
    end

    subgraph OPERATOR["Operator Devices"]
        OPS_LAPTOP["Engineer Laptop\n(Tailscale client\nOpenClaw CLI)"]
    end

    PRIMARY_K8S <-->|"Tailscale WireGuard"| SECONDARY_DC
    PRIMARY_K8S <-->|"Tailscale WireGuard"| EDGE_CLOUD
    OPS_LAPTOP <-->|"Tailscale WireGuard + Cloudflare Zero Trust"| PRIMARY_K8S
    PRIMARY_K8S -->|"trade submission (always)"| HL_API_FINAL["api.hyperliquid.xyz"]
    PRIMARY_K8S -->|"LLM APIs · market data MCPs · agentmail · supermemory"| EXTERNAL_SAAS["External SaaS APIs"]
```

---

## Component Inventory Quick Reference

| Component | Repo / Source | Namespace | Role | HA |
|---|---|---|---|---|
| `hl-node` | `hyperliquid-dex/node` | `hl-infra` | L1 data source, info API, EVM RPC | 2 replicas |
| `order-book-server` | `hyperliquid-dex/order_book_server` | `hl-infra` | Local L2/L4 WS feed | Restart policy |
| `hyper-evm-sync` | `hyperliquid-dex/hyper-evm-sync` | `hl-infra` | EVM archive node | Single |
| `block-importer` | `hyperliquid-dex/block-importer` | `hl-infra` | Bootstrap batch job | Job |
| `hyperliquid-stats` | `hyperliquid-dex/hyperliquid-stats` | `hl-apps` | Analytics API | Single |
| `hyperliquid-stats-web` | `hyperliquid-dex/hyperliquid-stats-web` | `hl-apps` | Analytics frontend | 2 replicas |
| `orchestrator-api` | `enuno/hyperliquid-trading-firm` | `hl-agents` | Cycle coordinator | 2 replicas |
| `agents-svc` | `enuno/hyperliquid-trading-firm` | `hl-agents` | TradingAgents pipeline | KEDA HPA |
| `sae-engine` | `enuno/hyperliquid-trading-firm` | `hl-agents` | Hard safety gates | Single |
| `executors-svc` | `enuno/hyperliquid-trading-firm` | `hl-agents` | HL paper/live execution | 2 replicas |
| `treasury-svc` | `enuno/hyperliquid-trading-firm` | `hl-agents` | BTC to stable conversion | Single |
| `optimizer-agent` | `enuno/hyperliquid-trading-firm` | `hl-agents` | Off-path RL/OPRO | Single |
| `intelliclaw` | internal | `hl-agents` | Market intel engine | 2 replicas |
| `eliza-os` | `elizaOS/eliza` | `hl-agents` | Web3 agent runtime | 2 replicas |
| `openclaw` | internal | `hl-agents` | HITL + governance control plane | Single |
| `kafka` | Apache Kafka | `hl-data` | Event bus | 3 brokers |
| `timescaledb` | TimescaleDB | `hl-data` | Tick/funding time-series | Primary + replica |
| `postgresql` | PostgreSQL | `hl-data` | DecisionTrace/audit/policies | Primary + replica |
| `redis` | Redis | `hl-data` | Hot state cache | Sentinel |
| `milvus` | Milvus | `hl-data` | Vector store / RAG | Single |
| `minio` | MinIO | `hl-data` | Delta Lake / RL training data | 4-node erasure |
| `prometheus` | Prometheus | `hl-observability` | Metrics | Single |
| `grafana` | Grafana | `hl-observability` | Dashboards | 2 replicas |
| `loki` | Grafana Loki | `hl-observability` | Log aggregation | Single |
| `tempo` | Grafana Tempo | `hl-observability` | Distributed tracing | Single |
| `alertmanager` | Alertmanager | `hl-observability` | Alert routing | 2 replicas |
| `mlflow` | MLflow | `hl-observability` | Experiment tracking | Single |
| `dashboard` | `enuno/hyperliquid-trading-firm` | `hl-apps` | Trading firm UI | 2 replicas |
| `ollama` | Ollama | `hl-apps` | Local LLM inference | GPU-pinned |
| `open-webui` | Open WebUI | `hl-apps` | LLM management UI | Single |
| `argocd` | ArgoCD | `hl-platform` | GitOps controller | HA mode |
| `rancher` | Rancher | `hl-platform` | K8s management plane | Single |
| `harbor` | Harbor | `hl-platform` | Container registry | 2 replicas |
| `nginx-ingress` | nginx | `hl-platform` | Reverse proxy / TLS | 2 replicas |
| `cert-manager` | cert-manager | `hl-platform` | TLS certificates | Single |
| `keda` | KEDA | `hl-platform` | Event-driven autoscaling | Single |
| `tailscale-operator` | Tailscale | `hl-platform` | Zero-trust mesh | Single |

---

*For system safety architecture, SAE policy invariants, HITL ruleset definitions, and treasury configuration, see [SPEC.md](../SPEC.md). For development phases and exit gates, see [DEVELOPMENTPLAN.md](../DEVELOPMENTPLAN.md).*
