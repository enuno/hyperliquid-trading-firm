# HyperLiquid Autonomous Trading Firm

This repository contains a modular, multi-agent trading system designed to run production-grade strategies on HyperLiquid perpetual futures (with extensions for DEX arbitrage and treasury flows).

The application runs as a stand-alone trading “firm” with its own agents, risk engine, and dashboard, but can also be orchestrated remotely by OpenClaw or other controllers via a clean API surface.

> Warning: This codebase is **experimental research software**. It is not audited and is not suitable for trading large capital without additional review, hardening, and monitoring.

---

## High-Level Architecture

The system is split into several independently deployable services:

- **Orchestrator API (`apps/orchestrator-api`)**  
  Central HTTP/WS API and coordinator. Runs TradingAgents-style decision cycles:
  1. Trigger analyst agents.
  2. Run bull/bear research debate.
  3. Ask the Trader agent for a decision.
  4. Ask the Risk Council and Fund Manager to approve/adjust.
  5. Call the SAE engine and execution adapters.

- **SAE Engine (`apps/sae-engine`)**  
  Survivability-Aware Execution middleware implementing per-strategy and per-asset policies:
  - Validates trade requests against leverage, size, and drawdown rules.
  - Builds staged execution plans (slices, pacing, algo choice).
  - Acts as a non-bypassable guardrail in front of all executors.

- **Agent Services (`apps/agents`)**  
  Python services implementing LLM-based agents and tools:
  - ATLAS-style Market/News/Fundamental/On-chain analysts.
  - Sentiment analyst with pluggable providers.
  - Bullish/Bearish researchers and debate facilitator.
  - Trader agent, three-profile Risk Council, Fund Manager.
  - Strategy plugins (Open-Trader/Freqtrade-style) used by the Trader as building blocks.
  - ATLAS Adaptive-OPRO prompt optimizer and RAG utilities.

- **Executors (`apps/executors`)**  
  Venue adapters responsible for turning validated execution plans into real orders:
  - HyperLiquid perps executor.
  - Hummingbot controller for MM / arbitrage.
  - DEX gateway adapter for on-chain routes.

- **Dashboard (`apps/dashboard`)**  
  Web UI for:
  - Live positions, PnL, and equity curves.
  - Strategy configuration and regime toggles.
  - Decision traces for each trade (analyst reports → debate → trader → risk → SAE → orders).

- **Jobs (`apps/jobs`)**  
  Offline/batch processes:
  - Backtesting and evaluation harness.
  - RL training for execution timing and strategy parameters.
  - Adaptive-OPRO prompt updates.
  - Treasury DCA/staking/profit-vault flows.

- **Infra (`infra/`)**  
  Kubernetes manifests, Terraform modules, and Helm charts for production deployment.

---

## Key Concepts

- **Multi-Agent Firm Structure**  
  The system models a trading “firm” rather than a single bot:
  - Analysts prepare structured market intelligence.
  - Researchers debate the bull and bear cases.
  - Trader agent proposes trades.
  - Risk Council (aggressive/neutral/conservative) votes per trade.
  - Fund Manager applies portfolio-level constraints.
  - SAE engine validates and stages execution.

- **ATLAS Market Intelligence + Adaptive-OPRO**  
  Analyst microservices implement ATLAS-style Market, News, and Fundamental pipelines, feeding structured context into decision agents. Adaptive-OPRO runs offline to continually refine the Trader’s prompt and hyperparameters based on realized performance.

- **SAE (Survivability-Aware Execution)**  
  All trades pass through a dedicated engine that enforces:
  - Position and leverage caps.
  - Drawdown-aware regime selection.
  - Staged execution with algo hints (TWAP/VWAP/POV/Iceberg).
  - Integration with RL-based execution agents for timing.

- **Strategy Plugins**  
  Classical strategies (grid, DCA, RSI reversion, etc.) are implemented as small Python classes with a common interface. The LLM Trader agent can select and configure these strategies dynamically, combining human-readable logic with agentic decision-making.

---

## Getting Started (Dev)

### Prerequisites

- Docker / Docker Compose
- Node.js (LTS) + pnpm or npm
- Python 3.11+
- A HyperLiquid testnet API key
- Access tokens for your LLM provider(s)

### Quick Start

Clone and enter the repo:

```bash
git clone https://github.com/your-org/hyperliquid-trading-firm.git
cd hyperliquid-trading-firm
```

Copy environment template and edit:

```bash
cp config/env.example .env
# edit .env with API keys, DB connection strings, etc.
```

Start core services in development mode:

```bash
docker-compose up -d
```

This should bring up:

- Orchestrator API
- SAE engine
- Agent workers
- HyperLiquid executor (paper mode)
- Postgres / Redis
- Dashboard (on http://localhost:3000 by default)

---

## Repository Layout

```text
apps/
  orchestrator-api/   # Node/TS REST+WS API and agent coordination
  sae-engine/         # TypeScript SAE policy evaluation and staging
  agents/             # Python LLM agents, analysts, and strategy plugins
  executors/          # Python venue adapters
  dashboard/          # Web UI (React/NextJS)
  jobs/               # Offline backtests, RL training, prompt updates

infra/
  k8s/                # Kubernetes manifests and overlays
  terraform/          # Optional infra provisioning
  helm/               # Optional Helm charts

config/               # Environment, logging, DB, queues, strategy configs
tests/                # Unit/integration tests per service
```

---

## OpenClaw Integration

This application is designed to be controlled by OpenClaw or similar orchestrators:

- OpenClaw can:
  - Trigger decision cycles via the Orchestrator API.
  - Adjust SAE policies and strategy configs via config endpoints.
  - Inspect decision traces and metrics for auto-research loops.

- The trading firm can also run completely standalone, with its own job schedulers and dashboards.

---

## Status

This repo currently provides **scaffolding and high-level structure** only. Many components are stubs and must be implemented:

- Agent prompts and model routing.
- SAE policy rules for your target assets.
- Strategy plugin implementations.
- Dashboard views and metrics.

Use this as a starting point for iterative development and experimentation.

