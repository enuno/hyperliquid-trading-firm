# hyperliquid-skills — Implementation Plan

> **Version:** 1.0.0
> **Last updated:** 2026-04-07
> **Scope:** Integration of `skills/hyperliquid-skills` (Dwellir infrastructure layer) into
> `hyperliquid-trading-firm` across all development phases
> **Parent plan:** [`DEVELOPMENT_PLAN.md`](../../DEVELOPMENT_PLAN.md) — when this document
> conflicts with `SPEC.md` or `DEVELOPMENT_PLAN.md`, those documents win and this one is updated.

---

## Overview

This plan governs how the `hyperliquid-skills` submodule — a Dwellir-maintained reference library
for Hyperliquid L1 infrastructure — is integrated into the trading firm system. It covers:

- **Endpoint routing decisions** (which Dwellir service serves which data need)
- **Per-phase integration tasks** aligned with `DEVELOPMENT_PLAN.md`
- **Security and secrets model** for Dwellir API credentials
- **Submodule lifecycle** — pinning, update, and CI validation
- **Observability wiring** — `hyperliquid-exporter`, Grafana Agent operator, dashboards
- **Builder code injection** — fee attribution at the execution layer
- **Open questions** requiring resolution before each phase begins

This submodule provides **read infrastructure only**. All write operations (order placement,
cancellation, transfers) go directly to `api.hyperliquid.xyz/exchange` via the native API.
See [`references/native-api.md`](references/native-api.md).

---

## Architecture Summary: Read vs Write

```
┌──────────────────────────────────────────────────────────────────────┐
│  hyperliquid-trading-firm                                            │
├────────────────────────────┬─────────────────────────────────────────┤
│  READ  (Dwellir via        │  WRITE  (Hyperliquid native)            │
│  hyperliquid-skills)       │                                         │
│                            │                                         │
│  Market data ──────────────┤  Place orders ── api.hyperliquid.xyz   │
│  Order book (WS/gRPC) ─────┤  Cancel orders    /exchange            │
│  Funding rates, OI ────────┤  Set leverage     (EIP-712 signature)  │
│  Fill streams (gRPC) ──────┤  Transfers                             │
│  EVM state (JSON-RPC) ─────┤  Treasury spot orders (live mode only) │
│  Historical data ──────────┤                                         │
└────────────────────────────┴─────────────────────────────────────────┘
```

**Endpoint assignment by use case:**

| Data Need | Dwellir Endpoint | Reference |
|-----------|-----------------|-----------|
| Real-time order book (L2/L4) | Orderbook WebSocket | [`orderbook-websocket.md`](references/orderbook-websocket.md) |
| L1 block / fill stream | gRPC Gateway | [`grpc-gateway.md`](references/grpc-gateway.md) |
| Market data snapshots, funding, OI | Info API proxy | [`info-api.md`](references/info-api.md) |
| EVM state, smart contracts | HyperEVM JSON-RPC | [`hyperevm-json-rpc.md`](references/hyperevm-json-rpc.md) |
| Historical fills for backtesting | Historical Data API | [`historical-data.md`](references/historical-data.md) |
| Node health, latency metrics | `hyperliquid-exporter` (Prometheus) | See §Observability below |
| CLI ops, key management, CI checks | Dwellir CLI | [`dwellir-cli.md`](references/dwellir-cli.md) |

---

## Submodule Lifecycle

### Pinning Policy

The submodule **must always be pinned to a specific commit SHA**, never tracking a branch.
This prevents silent skill regressions during agent-driven operations.

```bash
# Verify current pin
git submodule status skills/hyperliquid-skills

# Update pin (intentional, reviewed upgrade only)
cd skills/hyperliquid-skills
git fetch origin
git checkout <new-sha>
cd ../..
git add skills/hyperliquid-skills
git commit -m "chore: pin hyperliquid-skills to <new-sha> — <reason>"
```

### CI Validation

Add the following to the CI pipeline (before all other test stages):

```yaml
# .github/workflows/ci.yml (add to existing workflow)
- name: Validate submodule pin
  run: |
    # Fails if submodule is dirty or on a branch instead of a commit
    git submodule status | grep -v "^-" | grep -v "^ " && echo "ERROR: submodule not initialized" && exit 1
    cd skills/hyperliquid-skills
    git rev-parse --abbrev-ref HEAD | grep -q "HEAD" || (echo "ERROR: hyperliquid-skills is tracking a branch, not a commit SHA" && exit 1)

- name: Validate skills reference files
  run: |
    # Confirm all expected reference files are present
    for f in references/info-api.md references/grpc-gateway.md references/orderbook-websocket.md \
              references/native-api.md references/hyperevm-json-rpc.md \
              references/historical-data.md references/dwellir-cli.md; do
      test -f skills/hyperliquid-skills/$f || (echo "ERROR: missing $f" && exit 1)
    done
```

### `skills-lock.json`

The root `skills-lock.json` must be updated whenever the submodule SHA is updated.
Format:

```json
{
  "hyperliquid-skills": {
    "sha": "<commit-sha>",
    "updated": "YYYY-MM-DD",
    "reason": "Upgraded to include flashblocks-visualizer reference",
    "updated_by": "<github-username>"
  }
}
```

---

## Phase 0 — Scaffolding Integration

**Dependency on:** `DEVELOPMENT_PLAN.md` Phase 0

### Tasks

- [ ] **S0-01** Initialize submodule in `.gitmodules` pinned to current HEAD SHA:
  ```
  [submodule "skills/hyperliquid-skills"]
      path = skills/hyperliquid-skills
      url = https://github.com/dwellir-public/hyperliquid-skills.git
  ```
- [ ] **S0-02** Add `DWELLIR_API_KEY` and `DWELLIR_ENDPOINT_BASE` to `.env.example` with
  inline documentation pointing to [`references/info-api.md`](references/info-api.md)
- [ ] **S0-03** Add `BUILDER_CODE` and `BUILDER_FEE_BPS` to `.env.example`; document that
  builder codes are injected at the execution layer only — never in strategy or agent code
- [ ] **S0-04** Add `HYPERLIQUID_GRPC_HOST` to `.env.example` defaulting to
  `api-hyperliquid-mainnet-grpc.n.dwellir.com:443`; document TLS requirement
- [ ] **S0-05** Add Dwellir CLI install step to `Makefile`:
  ```makefile
  install-dwellir-cli:
      curl -fsSL https://raw.githubusercontent.com/dwellir-public/cli/main/scripts/install.sh | sh
  ```
- [ ] **S0-06** Add submodule init/update to `Makefile` `boot` target:
  ```makefile
  boot: submodule-init
  submodule-init:
      git submodule update --init --recursive
  ```
- [ ] **S0-07** Add CI submodule pin validation (see §Submodule Lifecycle above)
- [ ] **S0-08** Create `infra/observability/` directory with placeholder for
  `hyperliquid-exporter` compose service (wired in Phase 4)
- [ ] **S0-09** Document `proto/` gRPC schema alignment requirements in
  `docs/tradingagents-integration.md`: the `StreamBlocks`, `StreamFills`, and
  `StreamOrderbookSnapshots` methods from the Dwellir gRPC gateway (see
  [`grpc-gateway.md`](references/grpc-gateway.md)) must have corresponding proto definitions
  in `proto/` before Phase 1 data adapters are written

### Exit Gate

✅ `git submodule status` shows pinned SHA, not a branch name
✅ `make submodule-init` completes without errors on a clean clone
✅ All Dwellir-related env vars present in `.env.example` with documentation
✅ `make install-dwellir-cli` installs `dwellir` binary
✅ `BUILDER_CODE` var documented with clear note: execution layer only

---

## Phase 1 — Data Ingestion Integration

**Dependency on:** `DEVELOPMENT_PLAN.md` Phase 1 (P1-01 through P1-06)

### Data Adapter Routing

Each data adapter must use the correct Dwellir endpoint. Implementation deviations
require an architecture note in `docs/api-contracts.md`.

| Adapter (from DEVELOPMENT_PLAN.md) | Dwellir Endpoint | Reference | Notes |
|-------------------------------------|-----------------|-----------|-------|
| P1-01: OHLCV, funding rate, OI | Info API proxy | [`info-api.md`](references/info-api.md) | Use `metaAndAssetCtxs` batch endpoint; cache `meta` for 5 min |
| P1-01: Order book snapshot | Info API proxy | [`info-api.md`](references/info-api.md) | `l2Book` for snapshots; L4 via Orderbook WS |
| P1-01: Order book streaming | Orderbook WebSocket | [`orderbook-websocket.md`](references/orderbook-websocket.md) | Primary streaming source for market-making strategies |
| P1-01: Fill stream (real-time) | gRPC `StreamFills` | [`grpc-gateway.md`](references/grpc-gateway.md) | Lower latency than Info API polling |
| P1-04: HL vault flows, liquidations | Info API proxy | [`info-api.md`](references/info-api.md) | `clearinghouseState`, `userFills` endpoints |
| Backtesting (Phase 4) | Historical Data API | [`historical-data.md`](references/historical-data.md) | Up to 24h via gRPC; longer history via separate request |

### Tasks

- [ ] **S1-01** Implement `apps/data/dwellir_info_client.py`: thin async wrapper around
  Dwellir Info API proxy; reads `DWELLIR_API_KEY` and `DWELLIR_ENDPOINT_BASE` from env;
  implements request batching and 5-minute metadata cache (`meta`, `spotMeta`, `perpDexs`)
- [ ] **S1-02** Implement `apps/data/dwellir_orderbook_ws.py`: WebSocket client for
  Dwellir Orderbook server; handles reconnection with exponential backoff; emits
  `OrderBookUpdate` typed events on internal event bus; tracks `last_update_timestamp`
  for stale-data detection
- [ ] **S1-03** Implement `apps/data/dwellir_grpc_client.py`: gRPC client wrapping
  `StreamFills` and `StreamOrderbookSnapshots` from
  `api-hyperliquid-mainnet-grpc.n.dwellir.com:443`; uses TLS (`grpc.ssl_channel_credentials()`);
  reads from generated stubs in `packages/schemas/` (proto files from `proto/`)
- [ ] **S1-04** Add stale-data sentinel to all three clients: if `last_update_timestamp`
  is > 60s old, set `data_source_stale: true` in `MarketSnapshot`; this feeds into
  `has_data_gap` flag per `DEVELOPMENT_PLAN.md` P1-06
- [ ] **S1-05** Add Prometheus counters to each client (wired to exporter in Phase 4):
  `dwellir_info_requests_total`, `dwellir_ws_reconnects_total`,
  `dwellir_grpc_stream_restarts_total`
- [ ] **S1-06** Write `tests/unit/data/test_stale_detection.py`: inject mock timestamp
  > 60s; verify `has_data_gap` is propagated correctly through to `ResearchPacket`
- [ ] **S1-07** Document all Dwellir endpoint URLs actually used (post-provisioning) in
  `docs/api-contracts.md` under a "Dwellir Endpoints" section

### Caching Rules (enforce in code review)

```python
# Semi-static metadata — cache 5 minutes (per SKILL.md best practices)
CACHE_TTL = {
    "meta": 300,
    "spotMeta": 300,
    "perpDexs": 300,
    "universe": 300,
}
# Live data — no cache, always fresh
NO_CACHE = ["l2Book", "clearinghouseState", "userFills", "fundingHistory"]
```

### Exit Gate

✅ All three clients (`info`, `ws`, `grpc`) connect successfully against Dwellir endpoints
✅ `has_data_gap: true` correctly set when any client's `last_update_timestamp` > 60s
✅ Metadata cache prevents redundant `meta`/`spotMeta` calls within TTL window
✅ Unit tests pass for stale-detection (S1-06)

---

## Phase 2 — Debate and Trader: No New Endpoints

Phase 2 (`DEVELOPMENT_PLAN.md` P2-01 through P2-11) does not introduce new Dwellir
integration points. The data clients built in Phase 1 feed the `ResearchPacket` assembler
which is consumed by bull/bear researchers and the trader agent.

### Tasks

- [ ] **S2-01** Confirm `ResearchPacket` proto definition in `proto/` includes a
  `data_sources` field enumerating which Dwellir endpoints contributed data; this enables
  post-hoc attribution in `DecisionTrace` audit records
- [ ] **S2-02** Add `dwellir_endpoint_versions` map to `MarketSnapshot` schema: records
  the Dwellir API version header returned with each request; enables regression detection
  if Dwellir upgrades a proxy endpoint

---

## Phase 3 — Risk + SAE: No New Endpoints

Phase 3 (`DEVELOPMENT_PLAN.md` P3-01 through P3-16) is internal to the risk and SAE
engines. No Dwellir endpoints are called from `apps/sae-engine/` — this is enforced by the
existing rule that SAE must have zero network calls in its hot path.

### Tasks

- [ ] **S3-01** Add grep-based CI check: confirm `apps/sae-engine/` contains zero
  references to `dwellir`, `grpc`, WebSocket clients, or `info_client` — SAE policy
  evaluation must be purely deterministic rule execution with no I/O
- [ ] **S3-02** Add SAE policy rule for Dwellir data staleness: if `market_snapshot.has_data_gap`
  is `true`, the SAE `stale_data` check must fire and reject the cycle — the data gap
  flag set in Phase 1 (S1-04) becomes a hard safety gate here

---

## Phase 4 — Paper Executor, Observability, and Backtesting

**Dependency on:** `DEVELOPMENT_PLAN.md` Phase 4 (P4-01 through P4-18)

This is the most Dwellir-infrastructure-intensive phase.

### Builder Code Integration

Builder codes (see [Dwellir builder codes guide](https://www.dwellir.com/guides/builder-codes))
allow fee attribution on every order routed through the system. This is a revenue stream at
firm scale and must be wired at the execution layer only.

```
Strategy engine          Execution engine         Hyperliquid Exchange
      │                        │                         │
      │── TradeIntent ─────────▶│                         │
      │                        │── order + builder_code ─▶│
      │                        │   (injected here only)   │
      │                        │◀── fill receipt ─────────│
```

- [ ] **S4-01** Implement builder code injection in `apps/executors/hyperliquid_paper.py`
  and `apps/executors/hyperliquid_live.py`: read `BUILDER_CODE` and `BUILDER_FEE_BPS`
  from env; append to every order request; **never** pass these values into strategy
  or agent layers
- [ ] **S4-02** Log builder code metadata in `FillReport`: record `builder_code`,
  `builder_fee_bps`, and computed `estimated_rebate_usdc` for each fill
- [ ] **S4-03** Add `builder_rebate_cumulative_usdc` metric to Prometheus export
  (reconciled against actual rebate when Dwellir provides a rebate reporting endpoint)
- [ ] **S4-04** Write test: verify that an `ExecutionRequest` missing `builder_code` is
  rejected by the executor (builder code is required for all live and paper fills)

### Observability Stack Integration

Deploy the full Dwellir observability stack alongside the trading system:

- [ ] **S4-05** Add `hyperliquid-exporter` service to `docker-compose.yml`:
  ```yaml
  hyperliquid-exporter:
    image: dwellir/hyperliquid-exporter:latest
    environment:
      - HL_NODE_URL=${HL_NODE_URL}
      - HL_VALIDATOR_ADDRESS=${HL_VALIDATOR_ADDRESS}
    ports:
      - "9100:9100"
    restart: unless-stopped
  ```
- [ ] **S4-06** Add `prometheus` service to `docker-compose.yml` scraping:
  - `hyperliquid-exporter` (node/validator metrics)
  - `orchestrator-api:9090/metrics` (trading system metrics)
  - All data client custom counters from S1-05
- [ ] **S4-07** Add `grafana` and `grafana-agent` services to `docker-compose.yml` using
  configs from `infra/observability/` (adapted from
  `dwellir-public/observability-configuration`); mount dashboard provisioning JSON
- [ ] **S4-08** Write `infra/observability/dashboards/trading-system.json`: Grafana
  dashboard panels for:
  - Cycle throughput (cycles/hour, fills/hour)
  - SAE rejection rate by check name
  - Data freshness gauge (ms since last Dwellir WS/gRPC update)
  - Builder rebate accumulation (cumulative USDC)
  - Drawdown and PnL curves
  - HITL gate open/closed status
  - Analyst score distribution heatmap per cycle
- [ ] **S4-09** Write `infra/observability/dashboards/node-health.json`: panels sourced
  from `hyperliquid-exporter` — block latency, validator uptime, peer count, sync status
- [ ] **S4-10** Wire Prometheus alerting rules (`infra/observability/alerts.yml`):
  - `HighDataStaleness` — any Dwellir client `last_update_age_seconds > 90`
  - `SAERejectionSpike` — SAE rejection rate > 50% over 5m window
  - `DrawdownBreachWarning` — portfolio drawdown > 80% of configured max
  - `DrawdownBreachCritical` — portfolio drawdown >= configured max (fires kill-switch)
  - `OrchestratorHeartbeatMissing` — no cycle in > 2× configured cycle interval
- [ ] **S4-11** Connect `DrawdownBreachCritical` alert to kill-switch endpoint:
  Alertmanager webhook → `POST /control/emergency-halt` on Orchestrator API;
  **this is the observability-to-risk-control bridge**; document in `docs/runbooks/`
- [ ] **S4-12** If deploying to Kubernetes (ServerDomes edge): apply
  `grafana-agent-k8s-operator` CRDs from `dwellir-public/grafana-agent-k8s-operator`;
  configure `GrafanaAgent`, `MetricsInstance`, and `LogsInstance` CRs pointing at
  the trading system's namespaced pods

### Backtesting with Historical Data

- [ ] **S4-13** Implement `apps/data/dwellir_historical_client.py`: fetches historical
  fill and order book data via gRPC `GetFills` and `GetOrderBookSnapshot` unary methods;
  note 24h retention limit — data beyond this window must be pre-fetched and stored in
  Postgres `historical_snapshots` table before it ages out
- [ ] **S4-14** Add a scheduled job (`apps/jobs/historical_archiver.py`) that runs every
  6 hours and writes gRPC historical data to Postgres before the 24h retention window
  expires; this is the long-term backtest data source for `backtest_runner.py` (P4-10)
- [ ] **S4-15** Document in `docs/api-contracts.md`: historical data coverage window,
  archival schedule, and the fallback path when gRPC data is unavailable (Info API
  `userFills` query with pagination)

### Dwellir CLI in Runbooks

- [ ] **S4-16** Document CLI usage in `docs/runbooks/operational-checks.md`:
  ```bash
  # Verify Dwellir endpoint health before a trading session
  dwellir endpoints search hyperliquid
  dwellir usage summary

  # Inspect live order book from terminal (emergency diagnostic)
  dwellir docs get hyperliquid/order-book-server
  ```

### Exit Gate

✅ `docker-compose up` starts full observability stack (exporter, Prometheus, Grafana)
  without errors
✅ `hyperliquid-exporter` Prometheus metrics visible at `localhost:9100/metrics`
✅ `DrawdownBreachCritical` alert fires in test scenario and POSTs to kill-switch endpoint
✅ Builder code present in 100% of paper fill logs (verified by test S4-04)
✅ Historical archiver runs and Postgres `historical_snapshots` table is populated
✅ Backtest runner consumes from Postgres (not live Dwellir endpoints) — no network
  calls from `backtest_runner.py` during test execution

---

## Phase 5 — Governance: No New Dwellir Endpoints

Phase 5 (`DEVELOPMENT_PLAN.md` P5-01 through P5-14) adds HITL and OpenClaw governance.
No new Dwellir data endpoints are introduced. The observability stack from Phase 4 must
be operational before Phase 5 begins (governance audit log panels depend on Prometheus).

### Tasks

- [ ] **S5-01** Add `dwellir_hitl_gate_open_total` and `dwellir_hitl_gate_approved_total`
  Prometheus counters to Orchestrator API; wire to Grafana governance dashboard

---

## Phase 6 — Optimizer Agent: No New Dwellir Endpoints

Phase 6 optimizer agent reads from Postgres `decision_traces` only. No Dwellir endpoints
are called by the optimizer. The Dwellir connection is strictly upstream (data ingestion).

---

## Phase 7 — Live Execution Hardening

**Dependency on:** `DEVELOPMENT_PLAN.md` Phase 7 (P7-01 through P7-20)

### Live Data Upgrade

In live mode, the latency profile of data feeds becomes a trading concern, not just an
operational one. Dwellir dedicated nodes eliminate shared rate limits and reduce
feed latency.

- [ ] **S7-01** Evaluate and provision a Dwellir dedicated node (Tokyo mainnet) before
  live trading begins; update all endpoint env vars to point to the dedicated node;
  document in `docs/infrastructure.md`
- [ ] **S7-02** Add latency measurement to all three data clients (`info`, `ws`, `grpc`):
  record `feed_latency_ms` as a Prometheus histogram; alert if p95 > 200ms
- [ ] **S7-03** Implement feed failover: if Dwellir WS/gRPC is unreachable for > 10s,
  fall back to native Hyperliquid WebSocket (`wss://api.hyperliquid.xyz/ws`) for order
  book data; log failover event; SAE `stale_data` check remains active during failover
  window

### Chaos Tests for Data Layer

- [ ] **S7-04** Add `make chaos-feed-disconnect` test: terminate Dwellir WS connection
  mid-cycle; verify `has_data_gap: true` propagates within 60s and SAE rejects the cycle
- [ ] **S7-05** Add `make chaos-grpc-timeout` test: simulate gRPC timeout on fill stream;
  verify executor receives no orders during the degraded window
- [ ] **S7-06** Add `make chaos-builder-code-missing` test: strip `BUILDER_CODE` from env;
  verify executor rejects order construction (test S4-04 extended to live executor)

### Exit Gate

✅ All three chaos tests (S7-04, S7-05, S7-06) pass
✅ Feed failover confirmed: Dwellir WS disconnect triggers native WS fallback within 10s
✅ Dedicated node provisioned and endpoint vars updated before any live order is submitted
✅ Feed latency p95 < 200ms on dedicated node (verified by Prometheus histogram)

---

## Security Model

### Secrets Handling

| Secret | Env Var | Scope | Storage |
|--------|---------|-------|---------|
| Dwellir API key | `DWELLIR_API_KEY` | Data clients only | Secret manager or `.env` (never hardcoded) |
| Builder code | `BUILDER_CODE` | Execution layer only | Same |
| Builder fee BPS | `BUILDER_FEE_BPS` | Execution layer only | Same |
| gRPC endpoint | `HYPERLIQUID_GRPC_HOST` | gRPC client only | `.env.example` default provided |
| HL wallet private key | `HL_PRIVATE_KEY` | Live executor only | Secret manager, never logged |

**Rules:**
- `DWELLIR_API_KEY` must never appear in logs, trace artifacts, or dashboard output
- `BUILDER_CODE` must never be passed to strategy or agent layers
- `HL_PRIVATE_KEY` must never appear in any file committed to the repo — CI must grep
  for private key patterns on every push

### Least-Privilege API Key Separation

Provision separate Dwellir API keys for:
1. **Research / staging** — read-only Info API and historical data
2. **Production trading** — Orderbook WS + gRPC streaming + Info API (higher rate limits)

Never use the production key in local development or CI.

---

## Dwellir CLI — Operational Integration

The [Dwellir CLI](references/dwellir-cli.md) (`dwellir`) is a diagnostic and operational
tool, not a runtime dependency. It must not be imported or called from any running service.

**Sanctioned uses:**
- Endpoint URL discovery during infrastructure provisioning
- API key inspection and rotation (`dwellir keys list`, `dwellir keys rotate`)
- Usage monitoring in pre-flight runbook checks (`dwellir usage summary`)
- Local developer debugging (inspect live order book, verify endpoint connectivity)
- CI pre-flight: verify API key is valid before deploying to staging

```bash
# Makefile target — run before staging deployment
check-dwellir-credentials:
    dwellir keys list | grep -q "hyperliquid" || (echo "ERROR: no Hyperliquid API key configured" && exit 1)
    dwellir usage summary
```

---

## Reference Map: Dwellir Repos → Trading Firm Components

| Dwellir Repo | Role in This Project | Integration Point |
|---|---|---|
| `hyperliquid-skills` (this repo) | AI agent skill library, endpoint reference docs | `skills/hyperliquid-skills/` submodule; consumed by agent prompts and data adapters |
| `hyperliquid-exporter` | Prometheus metrics for HL node health | `infra/observability/docker-compose.yml` service |
| `order_book_server` | Reference implementation for WS order book protocol | Pattern reference for `dwellir_orderbook_ws.py` client |
| `hyperliquid-orderbook-server-code-examples` | Client consumption patterns for order book server | Code patterns for `dwellir_orderbook_ws.py` |
| `gRPC-code-examples` | Client/server gRPC patterns | Validates `proto/` schema alignment with gateway interface |
| `hyperliquid-builder-codes-demo` | Builder code injection patterns | Execution layer (`apps/executors/`) reference |
| `grafana-agent-operator` | Grafana Agent for bare-metal / VM deployments | `infra/observability/` for non-K8s deployments |
| `grafana-agent-k8s-operator` | Grafana Agent for Kubernetes | `infra/observability/k8s/` for ServerDomes K8s deployments |
| `observability-configuration` | Pre-built Grafana dashboards and alert rules | Import into `infra/observability/dashboards/` |
| `cli` | Terminal tooling for endpoint management | Makefile targets, CI pre-flight, operational runbooks |

---

## Open Questions

- [ ] **gRPC proto files:** Dwellir distributes gateway proto files upon request
  (support@dwellir.com). Are they already available? Required before Phase 1 S1-03
  can be implemented. They must be committed to `proto/` and added to the codegen pipeline.
- [ ] **Orderbook WS auth:** Does the Dwellir Orderbook WebSocket require API key auth
  via header or query param? Required before Phase 1 S1-02. Check
  [`orderbook-websocket.md`](references/orderbook-websocket.md) or contact Dwellir support.
- [ ] **Builder code provisioning:** Has a builder code been provisioned through Dwellir
  or directly through Hyperliquid? Required before Phase 4 S4-01. See
  [Dwellir builder codes guide](https://www.dwellir.com/guides/builder-codes).
- [ ] **Dedicated node timing:** At what phase is the dedicated node (Tokyo) provisioned?
  Recommended: provision at start of Phase 4 so paper trading runs on the same
  infrastructure as live. Cost should be approved before Phase 3 begins.
- [ ] **`hyperliquid-exporter` image tag:** Is a specific version of
  `dwellir/hyperliquid-exporter` pinned for the observability stack? Pin before Phase 4
  S4-05 to prevent silent metric schema changes.
- [ ] **Historical data retention:** The gRPC gateway provides 24h of historical data.
  How far back does the backtest window need to go? If > 24h, the historical archiver
  (S4-14) must be deployed and running before the first backtest run.
- [ ] **Flashblocks integration:** The [Flashblocks Visualizer guide](https://www.dwellir.com/guides/flashblocks-visualizer)
  suggests a sub-block data stream may be available. Is this relevant to the execution
  latency profile? Evaluate before Phase 7 live readiness review.
- [ ] **Multi-region failover:** Dwellir operates edge servers in Singapore and Tokyo.
  Should the production system route to the geographically nearest node, or always
  use the Tokyo dedicated node? Define before Phase 7 S7-01.

---

## Milestone Summary

| Phase | Dwellir Integration Work | Critical Blocker |
|---|---|---|
| 0 | Submodule pin, env vars, CLI install, Makefile | gRPC proto files (open question) |
| 1 | Info API client, WS client, gRPC client, stale-data detection | WS auth method (open question) |
| 2 | `data_sources` field in proto schema | None |
| 3 | SAE `stale_data` check, SAE network-call CI guard | Phase 1 data clients operational |
| 4 | Builder codes, observability stack, historical archiver | Builder code provisioned, dedicated node approved |
| 5 | Governance metrics counters | Phase 4 observability stack operational |
| 6 | None | None |
| 7 | Dedicated node, feed failover, chaos tests for data layer | Dedicated node provisioned |
