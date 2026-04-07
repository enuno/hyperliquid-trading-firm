# Hyperliquid-Claw OpenClaw Skill — Integration Plan
# Into: `enuno/hyperliquid-trading-firm`
# Version: 1.0.0
# Last Updated: 2026-04-07

---

## 1. Objective

Integrate the `hyperliquid-claw` OpenClaw skill (v3.0 Rust Edition) as the **live-execution MCP interface** inside the HyperLiquid Trading Firm scaffold.  
`hyperliquid-claw` provides the native MCP stdio server (`hl-mcp`) and Rust-powered trading primitives; the trading firm provides the multi-agent intelligence pipeline, SAE safety layer, Clawvisor HITL governance, treasury management, and audit trail.  

The integration couples these two systems cleanly by:
- Mapping `hl-mcp` tools to the Executors service in the trading firm.
- Using the Rust `ExchangeClient` (`exchange.rs`) as the canonical HL order submitter beneath the SAE layer.
- Surfacing `hyperliquid-claw` market-data tools (`hl_price`, `hl_market_scan`, `hl_analyze`) as the low-latency data feed into `HyperLiquidFeed`.
- Registering the skill with the OpenClaw Control Plane (Clawvisor) for HITL-governed trade execution.

---

## 2. Architectural Role Mapping

```
┌────────────────────────────────────────────────────────────────────────┐
│              HyperLiquid Trading Firm                                   │
│                                                                         │
│  OpenClaw Control Plane (Clawvisor)                                     │
│        │  HITL approvals, policy governance, kill-switch                │
│        ▼                                                                │
│  Orchestrator API ──────────────────────────────────────────────────┐  │
│        │  cycle coordinator, typed state, event bus, audit writer    │  │
│        ▼                                                             │  │
│  Agents Svc  →  SAE Engine  →  Executors Svc                        │  │
│        │              │               │                              │  │
│        │              │               ▼                              │  │
│        │              │    ┌──────────────────────────┐             │  │
│        │              │    │  hyperliquid-claw (hl-mcp)│  ◄── NEW  │  │
│        │              │    │  Rust MCP stdio server    │             │  │
│        │              │    │  ExchangeClient           │             │  │
│        │              │    │  MomentumEngine           │             │  │
│        │              │    │  HyperliquidClawVault.sol │             │  │
│        │              │    └──────────────────────────┘             │  │
│        │              │               │ FillReport                  │  │
│        │              │               ▼                              │  │
│  Treasury Mgr   Postgres/MLflow   DecisionTrace                     │  │
└────────────────────────────────────────────────────────────────────────┘
```

### Component Boundary Table

| Trading Firm Component | hyperliquid-claw Role | Interface |
|---|---|---|
| `HyperLiquidFeed` (data ingest) | `hl_price`, `hl_market_scan`, `hl_analyze` via `client.rs` | MCP tool call → JSON |
| `MomentumEngine` / `WaveDetector` | `signals.rs` Rust momentum engine | Shared signal schema |
| `Executors Svc` (paper/live) | `exchange.rs` `ExchangeClient`, `hl_market_buy/sell`, `hl_limit_buy/sell` | MCP stdio or direct Rust FFI |
| `SAE Engine` | Wraps every `hl_market_*` / `hl_limit_*` call — hard gate before execution | ExecutionDecision → hl-mcp |
| `Clawvisor HITL` | OpenClaw skill registration; HITL pause before `hl_market_buy/sell` | OpenClaw skill system prompt |
| `Treasury Manager` | Post-fill `hl_balance` polling; vault USDC accounting via `HyperliquidClawVault.sol` | MCP tool + on-chain |
| `DecisionTrace` | Immutable log includes `hl-mcp` tool name, params, fill response | Postgres JSON field |
| `Optimizer Agent` | Calls `hl_analyze` for regime-aware parameter tuning | MCP read-only tools only |

---

## 3. Integration Phases

### Phase 0 — Pre-requisites (Gate: all services boot; hl-mcp binary present)

**Tasks:**

- [ ] **P0-1** Add `hyperliquid-claw` as a git submodule under `multiclaw/hyperliquid-claw` (already present — verify submodule ref is pinned to a tagged release, not a floating branch HEAD).
- [ ] **P0-2** Add `hl-mcp` binary build step to `Makefile`:
  ```makefile
  build-hl-mcp:
      cd multiclaw/hyperliquid-claw && cargo build --release --bin hl-mcp
      cp multiclaw/hyperliquid-claw/target/release/hl-mcp bin/
  ```
- [ ] **P0-3** Add `hl-claw` CLI binary to the same `Makefile` target (used for local dev and smoke tests).
- [ ] **P0-4** Create `.env.example` entry for the skill:
  ```
  HYPERLIQUID_ADDRESS=0x...
  HYPERLIQUID_PRIVATE_KEY=        # leave blank in dev; populated via secret manager in prod
  HYPERLIQUID_TESTNET=1           # always 1 until Phase 4 gate passes
  ```
- [ ] **P0-5** Add `hl-mcp` to `docker-compose.yml` as a sidecar to `executors`:
  ```yaml
  hl-mcp:
    image: hl-mcp:local
    build:
      context: multiclaw/hyperliquid-claw
      dockerfile: ../../infra/docker/hl-mcp.Dockerfile
    environment:
      - HYPERLIQUID_ADDRESS=${HYPERLIQUID_ADDRESS}
      - HYPERLIQUID_PRIVATE_KEY=${HYPERLIQUID_PRIVATE_KEY}
      - HYPERLIQUID_TESTNET=${HYPERLIQUID_TESTNET}
    stdin_open: true
    tty: true
    restart: unless-stopped
  ```
- [ ] **P0-6** Add `hl-mcp.Dockerfile` at `infra/docker/hl-mcp.Dockerfile`.
- [ ] **P0-7** Register `hyperliquid-claw` skill in Clawvisor config at `apps/orchestrator-api/src/config/openclaw-skills.json`:
  ```json
  {
    "skills": [
      {
        "name": "hyperliquid-claw",
        "version": "3.0.0",
        "skill_path": "multiclaw/hyperliquid-claw/SKILL.md",
        "binary": "bin/hl-mcp",
        "requires_hitl": true,
        "hitl_tools": ["hl_market_buy", "hl_market_sell", "hl_limit_buy", "hl_limit_sell", "hl_cancel_all", "hl_set_leverage"]
      }
    ]
  }
  ```

**Exit Gate:** `make build-hl-mcp && hl-mcp --version` exits 0; `docker-compose up hl-mcp` starts without error on testnet.

---

### Phase 1 — Data Feed Integration (Gate: `HyperLiquidFeed` reads from `hl-mcp`; unit tests pass)

**Tasks:**

- [ ] **P1-1** Create `apps/agents/src/tools/hl_mcp_client.py` — a Python MCP stdio client wrapping `hl-mcp`:
  ```python
  # apps/agents/src/tools/hl_mcp_client.py
  import subprocess, json
  from typing import Any

  class HlMcpClient:
      """Thin wrapper over hl-mcp stdio MCP server."""

      def __init__(self, binary: str = "bin/hl-mcp"):
          self._proc = subprocess.Popen(
              [binary],
              stdin=subprocess.PIPE,
              stdout=subprocess.PIPE,
              stderr=subprocess.PIPE,
          )
          self._req_id = 0

      def call(self, tool: str, params: dict) -> Any:
          self._req_id += 1
          req = {"jsonrpc": "2.0", "id": self._req_id,
                 "method": "tools/call",
                 "params": {"name": tool, "arguments": params}}
          self._proc.stdin.write((json.dumps(req) + "\n").encode())
          self._proc.stdin.flush()
          line = self._proc.stdout.readline()
          resp = json.loads(line)
          if "error" in resp:
              raise RuntimeError(f"hl-mcp error: {resp['error']}")
          return resp["result"]["content"][0]["text"]

      def price(self, coin: str) -> float:
          return float(self.call("hl_price", {"coin": coin}))

      def market_scan(self, top_n: int = 10) -> list:
          raw = self.call("hl_market_scan", {"top_n": top_n})
          return json.loads(raw)

      def analyze(self, coin: str) -> dict:
          return json.loads(self.call("hl_analyze", {"coin": coin}))

      def balance(self) -> dict:
          return json.loads(self.call("hl_balance", {}))

      def positions(self) -> list:
          return json.loads(self.call("hl_positions", {}))
  ```

- [ ] **P1-2** Wire `HlMcpClient.price()` and `HlMcpClient.market_scan()` into `HyperLiquidFeed` (replaces direct HTTP calls to `api.hyperliquid.xyz/info`). The feed should continue to call the HL REST endpoint directly for high-frequency OHLCV data; `hl-mcp` is used for signals and account data.

- [ ] **P1-3** Map `HlMcpClient.analyze()` output to the `AnalystScore` protobuf schema:
  ```python
  # Mapping: hl_analyze → AnalystScore
  # hl_analyze returns: { coin, signal, confidence, price_change_pct, volume_vs_oi, funding_rate }
  # AnalystScore fields: analyst, score, confidence, keypoints, evidence_refs, data_gap
  def hl_analyze_to_analyst_score(raw: dict) -> AnalystScore:
      signal_map = {"STRONG_BULLISH": 1.0, "BULLISH": 0.5,
                    "NEUTRAL": 0.0, "BEARISH": -0.5, "STRONG_BEARISH": -1.0}
      return AnalystScore(
          analyst="hyperliquid_momentum",
          score=signal_map.get(raw.get("signal", "NEUTRAL"), 0.0),
          confidence=raw.get("confidence", 0.0),
          keypoints=[
              f"price_change_pct={raw.get('price_change_pct')}",
              f"volume_vs_oi={raw.get('volume_vs_oi')}",
              f"funding_rate={raw.get('funding_rate')}",
          ],
          evidence_refs=["hl_analyze"],
          data_gap=raw.get("signal") is None,
      )
  ```

- [ ] **P1-4** Add `hl_momentum` analyst stub at `apps/agents/src/analysts/hl_momentum.py` that calls `HlMcpClient.analyze()` and outputs a typed `AnalystScore` fed into `ResearchPacket`.

- [ ] **P1-5** Unit tests at `apps/agents/tests/test_hl_mcp_client.py`:
  - Mock `hl-mcp` subprocess; assert `price()`, `analyze()`, `market_scan()` parse correctly.
  - Assert `hl_analyze_to_analyst_score` maps all five signal values correctly.

**Exit Gate:** `pytest apps/agents/tests/test_hl_mcp_client.py` passes; `HyperLiquidFeed` successfully reads price and scan data from `hl-mcp` in integration test against testnet.

---

### Phase 2 — SAE-Gated Execution Integration (Gate: paper trades flow through SAE → hl-mcp; DecisionTrace captured)

**Tasks:**

- [ ] **P2-1** Create `apps/executors/src/hyperliquid_live.py` adapter that calls `HlMcpClient` for live order submission:
  ```python
  # apps/executors/src/hyperliquid_live.py
  class HyperLiquidLiveExecutor:
      """Live executor: SAE-approved ExecutionRequest → hl-mcp → FillReport."""

      def __init__(self, client: HlMcpClient):
          self._client = client

      def execute(self, req: ExecutionRequest) -> FillReport:
          # Only reached if SAE ExecutionDecision.allowed == True
          if req.algo in ("MARKET", "IOC"):
              if req.action == Direction.LONG:
                  raw = self._client.call("hl_market_buy",
                      {"coin": req.asset, "size": req.notional_usd / self._client.price(req.asset)})
              else:
                  raw = self._client.call("hl_market_sell",
                      {"coin": req.asset, "size": req.notional_usd / self._client.price(req.asset)})
          elif req.algo == "LIMIT":
              if req.action == Direction.LONG:
                  raw = self._client.call("hl_limit_buy",
                      {"coin": req.asset, "size": req.size, "price": req.limit_price})
              else:
                  raw = self._client.call("hl_limit_sell",
                      {"coin": req.asset, "size": req.size, "price": req.limit_price})
          return FillReport.from_hl_response(json.loads(raw), req)
  ```

- [ ] **P2-2** Add SAE policy check for `hyperliquid-claw`-specific safety constraints:
  - Enforce the `hl-mcp` **5% slippage cap** as a SAE assertion (redundant but belt-and-suspenders).
  - Enforce the **20% equity warning** from `SKILL.md` as a SAE hard reject (not just a warn).
  - Add `max_concurrent_positions: 1` check aligned with momentum strategy `risk_parameters`.
  - Add `max_hold_hours: 4` position age circuit breaker evaluated in the reconciler.

- [ ] **P2-3** Add `hl_tool_name` and `hl_tool_params` fields to `DecisionTrace` JSON schema:
  ```json
  // Append to existing DecisionTrace schema
  {
    "hl_execution": {
      "tool": "hl_market_buy",
      "params": { "coin": "BTC", "size": 0.001 },
      "raw_response": "...",
      "fill_price": 88000.0,
      "fill_size": 0.001,
      "slippage_bps": 12
    }
  }
  ```

- [ ] **P2-4** Add `hl_cancel_all` to the SAE **kill switch** path — on any circuit breaker trigger, the first action is `HlMcpClient.call("hl_cancel_all", {})` before position flattening.

- [ ] **P2-5** Add `hl_set_leverage` call at the start of each decision cycle, setting leverage from `ExecutionApproval.final_leverage` before any order is submitted.

- [ ] **P2-6** Paper-mode validation: run 48-hour paper trade session on testnet; assert DecisionTraces are written for every cycle; assert no SAE bypasses.

**Exit Gate:** 48h paper run on testnet produces ≥10 complete `DecisionTrace` records with `hl_execution` field populated; no unhandled exceptions in executor logs; SAE kill switch successfully calls `hl_cancel_all` in simulated circuit breaker test.

---

### Phase 3 — Clawvisor HITL + OpenClaw Control Plane (Gate: HITL pause/approve flow works end-to-end)

**Tasks:**

- [ ] **P3-1** Register the `hyperliquid-claw` SKILL.md system prompt with Clawvisor's OpenClaw adapter. Extend the skill system prompt to include the trading firm's HITL safety rules:
  ```yaml
  # Append to SKILL.md system_prompt (do not overwrite)
  TRADING FIRM INTEGRATION RULES:
  1. All trade decisions originate from the multi-agent pipeline — never from direct user requests in production.
  2. HITL approval is required for every hl_market_buy, hl_market_sell, hl_limit_buy, hl_limit_sell in LIVE mode.
  3. hl_cancel_all is always permitted without HITL — it is the emergency stop.
  4. Never set leverage above 10x without explicit fund manager approval in ExecutionApproval.
  5. Position flattening (reduce-only) is always permitted without HITL.
  ```

- [ ] **P3-2** Add a Clawvisor HITL ruleset entry in `apps/orchestrator-api/src/config/hitl-ruleset.json`:
  ```json
  {
    "rules": [
      {
        "id": "hl-trade-approval",
        "description": "Require human approval for any hl-mcp order execution in LIVE mode",
        "trigger": { "trade_mode": "LIVE", "hl_tool": ["hl_market_buy","hl_market_sell","hl_limit_buy","hl_limit_sell"] },
        "action": "pause",
        "timeout_seconds": 120,
        "on_timeout": "reject"
      },
      {
        "id": "hl-leverage-cap",
        "description": "Hard reject if requested leverage > 10x",
        "trigger": { "hl_tool": "hl_set_leverage", "leverage_gt": 10 },
        "action": "reject"
      }
    ]
  }
  ```

- [ ] **P3-3** Wire Clawvisor HITL approval gate into the executor flow between SAE `ExecutionDecision.allowed == true` and `HyperLiquidLiveExecutor.execute()`.

- [ ] **P3-4** Add `GET /control/hl-status` endpoint to Orchestrator API returning:
  ```json
  {
    "hl_mcp_alive": true,
    "testnet": true,
    "open_positions": 0,
    "open_orders": 0,
    "account_equity_usd": 10000.0,
    "last_fill_ms": 1712345678000
  }
  ```

- [ ] **P3-5** Add `POST /control/emergency-close` endpoint that calls `hl_cancel_all` then submits reduce-only market sells for all open positions — bypasses HITL, requires SAE kill-switch flag.

- [ ] **P3-6** Expose HITL approval queue in the Dashboard UI at `/governance/hitl-queue`.

**Exit Gate:** HITL pause fires on a paper-mode LIVE trade attempt; approval via OpenClaw releases the order; rejection correctly routes to `DecisionTrace.hl_execution: null`; emergency close endpoint tested.

---

### Phase 4 — Vault & Treasury Integration (Gate: on-chain USDC accounting reconciles with HL account)

**Tasks:**

- [ ] **P4-1** Deploy `HyperliquidClawVault.sol` to a testnet EVM chain (Arbitrum Sepolia or HyperEVM testnet):
  ```bash
  cd multiclaw/hyperliquid-claw
  forge install OpenZeppelin/openzeppelin-contracts
  forge build
  forge test
  forge script script/Deploy.s.sol --rpc-url $TESTNET_RPC_URL --broadcast
  ```

- [ ] **P4-2** Wire vault USDC deposit/withdrawal to the Treasury Manager:
  - On significant realized PnL (configurable threshold), Treasury Manager triggers vault `recordTrade()` on-chain.
  - USDC conversion triggers call vault `withdraw()` for the conversion amount.

- [ ] **P4-3** Add vault address and ABI to `.env.example`:
  ```
  HL_VAULT_ADDRESS=0x...
  HL_VAULT_RPC_URL=https://...
  ```

- [ ] **P4-4** Add `hl_balance` polling (every 60s) to the Treasury Manager's reconciliation loop; assert on-chain vault balance matches HL account equity within a 1% tolerance; emit alert if drift exceeds threshold.

- [ ] **P4-5** Add `treasury_event.vault_tx_hash` field to the `DecisionTrace` treasury section.

- [ ] **P4-6** Add vault deployment addresses to `infra/contracts/deployed.json` with network, block, and deployer metadata.

**Exit Gate:** Vault deployed and verified on testnet; Treasury Manager reconciliation runs for 24h without drift alert; `forge test` passes 100%.

---

### Phase 5 — Momentum Strategy Configuration (Gate: strategy validated in paper trading; Sharpe ≥ 0.8 over 30 days)

**Tasks:**

- [ ] **P5-1** Create `apps/agents/src/strategies/hl_momentum_strategy.py` that wraps the `hyperliquid-claw` Momentum Scalp strategy as a `StrategySpec`:
  ```python
  HL_MOMENTUM_STRATEGY = StrategySpec(
      name="hl_momentum_scalp",
      entry_conditions={
          "price_change_pct_min": 0.5,    # signal threshold from SKILL.md
          "volume_vs_oi_min": 1.5,         # volume confirmation
          "funding_rate_contrarian": True, # funding rate filter
      },
      risk_parameters={
          "position_size_pct": 0.10,
          "max_loss_pct": 0.01,
          "take_profit_pct": 0.02,
          "max_concurrent_positions": 1,
          "max_hold_hours": 4,
      },
      safety_limits={
          "slippage_cap_pct": 0.05,
          "position_warning_pct": 0.20,
      },
      instrument_type="PERP",
      venue="HYPERLIQUID",
  )
  ```

- [ ] **P5-2** Wire `hl_momentum` analyst signal into the Trader agent's synthesis step as a high-weight input alongside the ATLAS analyst reports.

- [ ] **P5-3** Add `max_hold_hours` circuit breaker to the reconciler: if a position has been open longer than `StrategySpec.risk_parameters.max_hold_hours`, emit a SAE-level close request.

- [ ] **P5-4** Backtest `hl_momentum_scalp` over the last 90 days of HL perp data:
  - Use `hl-claw scan` output replayed from historical snapshots.
  - Metrics: Sharpe, max drawdown, win rate, profit factor, turnover.
  - Compare to buy-and-hold BTC baseline.
  - Acceptance threshold: Sharpe ≥ 0.8, max drawdown ≤ 15%.

- [ ] **P5-5** Log strategy backtest run to MLflow under experiment `hl_momentum_scalp_backtest`.

- [ ] **P5-6** 30-day paper trading run with full decision cycle (agents → SAE → hl-mcp testnet). Collect `DecisionTrace` records; compute live metrics via Optimizer Agent.

**Exit Gate:** Backtest Sharpe ≥ 0.8, max drawdown ≤ 15%; paper run Sharpe ≥ 0.5 (lower threshold due to testnet slippage); no SAE policy violations; Optimizer Agent has ≥ 1 approved parameter suggestion logged in MLflow.

---

### Phase 6 — Production Promotion (Gate: all Phase 0–5 gates passed; security audit complete)

**Tasks:**

- [ ] **P6-1** Rotate `HYPERLIQUID_PRIVATE_KEY` from dev/test to a production key managed by a secret manager (Vault, AWS Secrets Manager, or Bitwarden Secrets Manager).
- [ ] **P6-2** Set `HYPERLIQUID_TESTNET=` (empty) in production `.env` — this is the only change that activates mainnet.
- [ ] **P6-3** Run secret scanning on all files that touch `HYPERLIQUID_PRIVATE_KEY` to confirm no key material is logged or persisted in `DecisionTrace`.
- [ ] **P6-4** Security review checklist:
  - [ ] `hl-mcp` runs as a non-root user in Docker.
  - [ ] Private key is never logged at any log level.
  - [ ] `hl_cancel_all` is idempotent and tested under concurrent SAE + HITL calls.
  - [ ] Vault contract has `pause()` tested; `emergencyDrain()` access-controlled to owner.
  - [ ] OpenClaw skill registered with read-only key separate from trading key.
- [ ] **P6-5** Load test: simulate 100 concurrent decision cycles; assert `hl-mcp` handles queued stdio requests without deadlock.
- [ ] **P6-6** Runbook written at `docs/runbooks/hl-mcp-ops.md` covering: restart procedure, key rotation, emergency close, vault pause.
- [ ] **P6-7** ArgoCD production deployment manifest at `infra/k8s/production/hl-mcp.yaml`.

**Exit Gate:** Security audit signoff; load test passes; ArgoCD deploys cleanly to production cluster; first live trade executed and `DecisionTrace` written with `hl_execution.fill_price` populated.

---

## 4. Risk Controls Summary

The following controls are **non-negotiable** and enforced at multiple layers:

| Control | Layer | Source |
|---|---|---|
| 5% slippage cap | `exchange.rs` (Rust) + SAE | `SKILL.md` + SAE policy |
| 20% equity hard reject | SAE (upgraded from warn) | `SKILL.md` → P2-2 |
| Max 1 concurrent position | SAE + reconciler | `SKILL.md` strategy params |
| Max 4h hold time | Reconciler circuit breaker | `SKILL.md` strategy params |
| HITL pause on LIVE orders | Clawvisor | P3-2 |
| Leverage cap ≤ 10x | Clawvisor hard reject | P3-2 |
| Kill switch → `hl_cancel_all` | SAE kill switch | P2-4 |
| No auto-retry on failed trade | `hl-mcp` by design | `SKILL.md` |
| Private key never logged | Logger config + secret scan | P6-4 |
| Vault position limit | `HyperliquidClawVault.sol` | Contract-level |

---

## 5. Open Questions

The following decisions are **blockers** for specific phases and require explicit resolution before work proceeds:

| # | Question | Blocking Phase | Decision Owner |
|---|---|---|---|
| OQ-1 | Run `hl-mcp` as a Docker sidecar (stdio over named pipe) or compile as a Rust library called via PyO3 FFI from the executor? Sidecar is simpler; FFI eliminates process overhead. | Phase 0 | Infra/Systems |
| OQ-2 | Which testnet EVM chain for `HyperliquidClawVault.sol`? Arbitrum Sepolia or HyperEVM testnet? | Phase 4 | Smart contract lead |
| OQ-3 | Does the Optimizer Agent have write access to `hl_set_leverage`, or is it read-only and submits parameter suggestions via Clawvisor for human approval? | Phase 5 | Risk / Governance |
| OQ-4 | Is `hl_momentum_scalp` the sole live strategy at launch, or does it run alongside another strategy in the multi-strategy allocator? If multi-strategy, adjust `max_concurrent_positions` accordingly. | Phase 5 | Strategy lead |
| OQ-5 | Treasury USDC conversion threshold: what realized PnL (USD or %) triggers a vault `recordTrade()` call? | Phase 4 | Treasury policy |

---

## 6. File Map — New Files This Integration Adds

```
hyperliquid-trading-firm/
├── multiclaw/
│   └── hyperliquid-claw/
│       └── IMPLEMENTATION_PLAN.md          ← this file
├── infra/
│   ├── docker/
│   │   └── hl-mcp.Dockerfile
│   ├── k8s/
│   │   └── production/
│   │       └── hl-mcp.yaml
│   └── contracts/
│       └── deployed.json
├── apps/
│   ├── agents/
│   │   └── src/
│   │       ├── tools/
│   │       │   └── hl_mcp_client.py        ← Phase 1
│   │       ├── analysts/
│   │       │   └── hl_momentum.py          ← Phase 1
│   │       └── strategies/
│   │           └── hl_momentum_strategy.py ← Phase 5
│   ├── executors/
│   │   └── src/
│   │       └── hyperliquid_live.py         ← Phase 2
│   └── orchestrator-api/
│       └── src/
│           └── config/
│               ├── openclaw-skills.json    ← Phase 0
│               └── hitl-ruleset.json       ← Phase 3
└── docs/
    └── runbooks/
        └── hl-mcp-ops.md                   ← Phase 6
```

---

## 7. References

- [`SKILL.md`](./SKILL.md) — OpenClaw skill definition (v3.0.0, Rust Edition)
- [`README.md`](./README.md) — hyperliquid-claw architecture and CLI reference
- [`exchange.rs`](./exchange.rs) — Rust `ExchangeClient` (EIP-712 signing, order submission)
- [`signals.rs`](./signals.rs) — Rust `MomentumEngine` (signal classification)
- [`server.rs`](./server.rs) — MCP stdio server implementation
- [`HyperliquidClawVault.sol`](./HyperliquidClawVault.sol) — Solidity vault (SafeERC20, ReentrancyGuard)
- [`SPEC.md`](../../SPEC.md) — Trading firm architecture specification (authoritative)
- [`DEVELOPMENTPLAN.md`](../../DEVELOPMENTPLAN.md) — Trading firm phased development plan

> **Rule:** If this document conflicts with `SPEC.md`, `SPEC.md` wins. Update this document and open a PR to resolve.
