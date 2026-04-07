# BankrRail Implementation Plan
## `multiclaw/bankr` — EVM/Solana DeFi Execution Rail for the HyperLiquid Trading Firm

> **Status:** Research/Design → Paper-Trading Validation in Progress  
> **Owner:** enuno  
> **Last Updated:** 2026-04-07  
> **Parent SPEC:** [`SPEC.md`](../../SPEC.md)  
> **Interface Sketch:** [`docs/bankr_openclaw_interface.md`](docs/bankr_openclaw_interface.md)  
> **Skill Orchestration:** [`bankr-agent-orchestration-README.md`](skills/)

---

## 1. Objective

Extend the HyperLiquid Autonomous Trading Firm (HL-TF) beyond its native HyperLiquid/HyperEVM perpetuals execution layer by integrating **Bankr** as a second, independently governed execution rail for EVM and Solana DeFi actions — without modifying the TradingAgents pipeline, SAE engine, or any existing proto contracts.

Bankr is treated as a **low-trust external venue adapter**, logically equivalent to `HyperLiquidExecutor` but targeting Bankr-exposed chains: Base, Ethereum, Polygon, Unichain, and Solana.

**Scope of this plan:**
- All new files, services, and schema changes required to wire BankrRail into HL-TF
- Phased delivery from stub scaffolding → paper validation → live promotion
- Safety invariants, HITL gates, circuit breakers, and audit requirements
- Agent skill loading matrix aligned to TradingAgents roles
- x402 micropayment layer for Analyst intelligence queries via Zerion

---

## 2. Key Capabilities Unlocked

| Bankr Capability | HL-TF Use Case |
|---|---|
| Spot swaps (EVM/Solana) | Spot hedges against HL perp positions |
| DCA / limit / stop-loss | Dollar-cost averaging; treasury USDC → ETH/BTC spot |
| Leveraged DeFi trades | Basis/carry strategies across EVM venues |
| Lend/borrow | Yield on idle stablecoins between HL trading cycles |
| Polymarket positions | Event-driven strategy overlay; prediction market signals |
| Privy server wallets | Agent-controlled, non-custodial wallets with gas sponsorship |
| Zerion x402 feeds | Self-funded per-call portfolio intelligence for the Analyst layer |

---

## 3. Architecture Position

BankrRail inserts **only at the execution layer**. The agent plane, SAE engine, and all existing proto contracts are unchanged.

```
OpenClaw Control Plane  (cycle trigger, HITL, governance)
        │
Orchestrator API        (cycle coordinator, typed state store, event bus)
        │
  Agents Svc            (TradingAgents pipeline — UNCHANGED)
        │
  SAE Engine            (deterministic, non-bypassable — UNCHANGED)
        │
  ExecutionDecision
   ┌────┴────────────────────────┐
   │                             │
HyperLiquidExecutor         BankrExecutor  ← NEW
(perps, existing)         (EVM/Solana DeFi via Bankr)
   │                             │
HyperLiquid API            Bankr Skill API
                                 │
                         Privy Server Wallet
                                 │
                   Base · ETH · Polygon · Unichain · Solana
```

**Key rule:** SAE emits a single `ExecutionDecision` per cycle. The Orchestrator inspects the `venue` field on each staged request and routes to `HyperLiquidExecutor` or `BankrExecutor`. No order ever bypasses SAE regardless of venue.

---

## 4. Design Principles

1. **Bankr is execution-only.** All reasoning, research, risk governance, and sizing decisions remain inside the TradingAgents pipeline. Bankr's natural-language agent features are never used — only typed skill endpoints are called, with parameters derived from `TraderDecisionSignal` → `ExecutionRequest`.
2. **Low trust, defence in depth.** `BankrExecutor` enforces its own wallet allowlist and notional bounds as a second line of defence *after* SAE. Failures always propagate as `FAILED FillReport` objects — never as exceptions that could trigger compensating trades on another venue.
3. **SAE controls BankrRail with two independent switches.** `enabled` (master) and `liveEnabled` (paper→live promotion gate). Promoting to live requires a Clawvisor HITL approval event recorded in the governance ledger.
4. **Atomic audit trail.** `bankrfills` are written to `DecisionTrace` atomically alongside `fillreports` (HL perp fills). A cycle cannot be marked complete if any BankrRail fill write is pending.
5. **Circuit breakers are unconditional.** A Redis rolling counter tracks `SAEBankrConfig.maxDailyVolumeUsd`. Exceeding it suspends BankrRail for the rest of the UTC day without requiring a restart.

---

## 5. Proto Contract Extensions

### 5.1 `proto/common.proto` — Add VenueRail, BankrActionType, BankrChain enums

```protobuf
// proto/common.proto — additions only; no existing fields changed

enum VenueRail {
  VENUE_RAIL_UNSPECIFIED = 0;
  HYPERLIQUID_PERPS      = 1;  // existing
  BANKR_EVM              = 2;  // NEW — Base, ETH, Polygon, Unichain
  BANKR_SOLANA           = 3;  // NEW — Solana
}

enum BankrActionType {
  BANKR_ACTION_UNSPECIFIED   = 0;
  BANKR_SWAP                 = 1;
  BANKR_LIMIT_ORDER          = 2;
  BANKR_DCA                  = 3;
  BANKR_STOP_LOSS            = 4;
  BANKR_LEVERAGED_TRADE      = 5;
  BANKR_LEND                 = 6;
  BANKR_BORROW               = 7;
  BANKR_POLYMARKET_POSITION  = 8;
}

enum BankrChain {
  BANKR_CHAIN_UNSPECIFIED = 0;
  BASE      = 1;
  ETHEREUM  = 2;
  POLYGON   = 3;
  UNICHAIN  = 4;
  SOLANA    = 5;
}
```

### 5.2 `proto/execution.proto` — Extend ExecutionRequest with BankrParams

```protobuf
// proto/execution.proto — additions to existing ExecutionRequest message

message ExecutionRequest {
  // ... all existing fields unchanged (fields 1–9) ...
  tradingfirm.common.VenueRail venue = 10;  // default: HYPERLIQUID_PERPS
  BankrParams bankr_params           = 11;  // populated iff venue == BANKR_*
}

// New message — only present when venue is BANKR_EVM or BANKR_SOLANA
message BankrParams {
  tradingfirm.common.BankrChain      chain             = 1;
  tradingfirm.common.BankrActionType action_type       = 2;
  string   from_token        = 3;   // e.g. "USDC"
  string   to_token          = 4;   // e.g. "ETH"
  double   from_amount       = 5;   // in from_token units
  double   limit_price       = 6;   // for LIMIT / STOP_LOSS
  uint32   dca_interval_secs = 7;   // for DCA
  uint32   dca_periods       = 8;
  string   protocol_hint     = 9;   // "uniswap", "aave", etc.
  bool     sponsored_gas     = 10;  // request Bankr gas sponsorship
  string   wallet_id         = 11;  // Privy server wallet ID
  map<string, string> extra  = 12;  // forward-compat extension bag
}
```

### 5.3 `proto/execution.proto` — Extend FillReport with BankrRail fields

```protobuf
message FillReport {
  // ... all existing fields unchanged (fields 1–8) ...
  tradingfirm.common.VenueRail venue = 9;   // NEW
  string  onchain_tx_hash  = 10;  // EVM/Solana tx hash
  string  chain_name       = 11;  // "base", "solana", etc.
  double  gas_used_usd     = 12;
  string  bankr_order_id   = 13;  // Bankr internal order ref
}
```

---

## 6. SAE Engine — BankrRail Policy Extension

### 6.1 `apps/sae-engine/src/types.ts` — SAEBankrConfig interface

```typescript
export interface SAEBankrConfig {
  enabled:            boolean;      // master switch — default: false
  liveEnabled:        boolean;      // requires HITL approval
  allowedChains:      BankrChain[];
  allowedActionTypes: BankrActionType[];
  maxNotionalUsd:     number;       // hard cap per order
  maxLeverage:        number;       // independent from HL perps cap
  maxDailyVolumeUsd:  number;       // rolling circuit breaker (Redis)
  walletIdAllowlist:  string[];     // Privy wallet IDs
}

// Append to existing SAEConfig:
export interface SAEConfig {
  // ...existing fields unchanged...
  bankr: SAEBankrConfig;
}

// Recommended default — ships fully disabled, all caps zero:
export const defaultSAEBankrConfig: SAEBankrConfig = {
  enabled: false, liveEnabled: false,
  allowedChains: [], allowedActionTypes: [],
  maxNotionalUsd: 0, maxLeverage: 1.0,
  maxDailyVolumeUsd: 0, walletIdAllowlist: [],
};
```

### 6.2 `apps/sae-engine/src/bankr-policy.ts` — BankrRail check block

Appended to `evaluateExecution()` after all existing Layer 0–3 checks. Enforces chain/action-type allowlists, per-order notional cap, leverage cap, and the live-mode gate.

```typescript
// apps/sae-engine/src/bankr-policy.ts (addition to evaluateExecution)

if (req.venue === VenueRail.BANKR_EVM || req.venue === VenueRail.BANKR_SOLANA) {
  const bc = ctx.saeConfig.bankr;
  if (!bc.enabled)
    violated.push('BANKRAIL_DISABLED');
  if (!bc.allowedChains.includes(req.bankrParams?.chain!))
    violated.push('BANKR_CHAIN_NOT_ALLOWED');
  if (!bc.allowedActionTypes.includes(req.bankrParams?.actionType!))
    violated.push('BANKR_ACTION_TYPE_NOT_ALLOWED');
  if (sizeUsd > bc.maxNotionalUsd)
    violated.push('BANKR_NOTIONAL_EXCEEDED');   // soft — clips to cap
  if (req.leverage > bc.maxLeverage)
    violated.push('BANKR_LEVERAGE_CLIPPED');    // soft — clips to maxLeverage
  if (ctx.mode === 'live' && !bc.liveEnabled)
    violated.push('BANKR_LIVE_NOT_ENABLED');
}
```

**Hard-block violations** (`allowed: false` returned immediately): `BANKRAIL_DISABLED`, `BANKR_CHAIN_NOT_ALLOWED`, `BANKR_ACTION_TYPE_NOT_ALLOWED`, `BANKR_LIVE_NOT_ENABLED`.

**Soft violations** (logged in audit, not blocking): `BANKR_NOTIONAL_EXCEEDED` clips `sizeUsd` to cap; `BANKR_LEVERAGE_CLIPPED` clips to `maxLeverage`.

---

## 7. BankrExecutor — Python Venue Adapter

**File:** `apps/executors/bankr_executor.py`

### 7.1 BankrSkillClient

Thin HTTP client wrapping the Bankr Skill API. Stateless, retries with exponential backoff, idempotency keys derived from `cycleId-sliceIndex`. Replace with official Bankr SDK when stable.

```python
BANKR_SKILL_BASE = "https://api.bankr.bot/v1"

class BankrSkillClient:
    def __init__(self, api_key: str, timeout: float = 15.0, max_retries: int = 3): ...
    def submit_order(self, req: BankrSkillRequest) -> BankrSkillResponse: ...
    # On all retries exhausted: returns BankrSkillResponse(status="failed") — NEVER raises
```

Key rules:
- Every request carries `Idempotency-Key: {cycleId}-slice{sliceIndex}` to make retries safe.
- Retries exhausted → return `FAILED` response; do **NOT** raise to the Orchestrator.
- Timeout is 15 s per attempt; wait `2^attempt` seconds between retries.

### 7.2 BankrExecutor

```python
class BankrExecutor:
    """
    Venue adapter: routes SAE-approved ExecutionDecision.staged_requests
    with venue=BANKR_EVM|BANKR_SOLANA to the Bankr Skill API.

    Defence-in-depth invariants (SAE is primary; these are second-line):
    - wallet_id must be in local allowlist (mirrors SAEBankrConfig).
    - notional_usd must be > 0 and <= hard_cap_usd.
    - On any failure: log, record FAILED FillReport, return — NEVER raise.
    - idempotency_key is derived from cycleId+sliceIndex for safe retries.
    """
    def execute(self, decision, cycle_id: str) -> list[dict]: ...
    def execute_one(self, req, cycle_id: str, slice_index: int) -> dict: ...
    def failed_fill(self, req, cycle_id: str, reason: str) -> dict: ...
```

### 7.3 Chain / Action enum maps

```python
CHAIN_ENUM_TO_STR  = {1:"base", 2:"ethereum", 3:"polygon", 4:"unichain", 5:"solana"}
ACTION_ENUM_TO_STR = {1:"swap", 2:"limit", 3:"dca", 4:"stoploss",
                      5:"leverage", 6:"lend", 7:"borrow", 8:"polymarket"}
```

---

## 8. Orchestrator Routing Extension

**File:** `apps/orchestrator-api/src/executor-router.ts`

```typescript
export async function routeExecution(
  decision: ExecutionDecision, cycleId: string,
  hyper: HyperLiquidExecutor, bankr: BankrExecutor
): Promise<FillReport[]> {
  const hyperRequests = decision.stagedRequests
    .filter(r => r.venue === VenueRail.HYPERLIQUID_PERPS || !r.venue);
  const bankrRequests = decision.stagedRequests
    .filter(r => r.venue === VenueRail.BANKR_EVM || r.venue === VenueRail.BANKR_SOLANA);

  const fills: FillReport[] = [];
  // Execute HL perps first; Bankr second.
  // Never fan-out in parallel when a Bankr order is a hedge of an HL order — sequence them.
  if (hyperRequests.length > 0)
    fills.push(...await hyper.execute({...decision, stagedRequests: hyperRequests}, cycleId));
  if (bankrRequests.length > 0)
    fills.push(...await bankr.execute({...decision, stagedRequests: bankrRequests}, cycleId));
  return fills;
}
```

---

## 9. OpenClaw Skill Registration

**File:** `config/openclaw-skills/bankr-rail.skill.json`

```json
{
  "skill_id": "bankr-rail-v1",
  "display_name": "BankrRail — EVM/Solana DeFi Executor",
  "version": "1.0.0",
  "vendor": "bankr.bot",
  "trust_level": "low_trust_external",
  "rail": "bankr",
  "governance": {
    "requires_hitl_for_live_promotion": true,
    "requires_hitl_for_chain_addition": true,
    "sae_config_key": "bankr"
  },
  "default_sae_policy": {
    "enabled": false, "live_enabled": false,
    "allowed_chains": [], "allowed_action_types": [],
    "max_notional_usd": 0, "max_leverage": 1.0,
    "max_daily_volume_usd": 0, "wallet_id_allowlist": []
  },
  "hitl_rules": [
    {"name":"bankr_live_promotion",
     "when":{"event_type":"bankr_rail_live_enabled"},
     "require_approval":true, "timeout_seconds":3600, "on_timeout":"reject"},
    {"name":"bankr_chain_addition",
     "when":{"event_type":"bankr_allowed_chain_updated"},
     "require_approval":true, "timeout_seconds":1800, "on_timeout":"reject"},
    {"name":"bankr_large_order",
     "when":{"bankr_notional_usd_gte":2500},
     "require_approval":true, "timeout_seconds":300, "on_timeout":"reject"}
  ],
  "observability": {
    "metrics_prefix": "bankr_executor",
    "required_labels": ["chain", "action_type", "status", "cycle_id"]
  }
}
```

### HITL Gate Summary

| Event | Gate | Timeout | On Timeout |
|---|---|---|---|
| `bankr_rail_live_enabled` | Clawvisor approval required | 1 hour | Reject |
| `bankr_allowed_chain_updated` | Clawvisor approval required | 30 min | Reject |
| BankrRail order ≥ $2,500 notional | Approval required | 5 min | Reject |

---

## 10. DecisionTrace Extension

The existing `decision_traces` Postgres table gains a `bankr_fills` JSONB array alongside `fill_reports` (HL perp fills). Both are written **atomically** — a cycle cannot be marked complete if any BankrRail fill write is pending.

```json
{
  "cycle_id": "cyc01JQ...",
  "fill_reports": [
    {"venue": "HYPERLIQUID_PERPS", "venue_order_id": "hl-abc123", "status": "FILLED"}
  ],
  "bankr_fills": [
    {
      "venue": "BANKR_EVM",
      "chain_name": "base",
      "bankr_order_id": "bnkr-xyz789",
      "onchain_tx_hash": "0xabc...def",
      "asset": "USDC→ETH",
      "filled_qty": 0.42,
      "avg_price": 2380.10,
      "slippage_bps": 12,
      "gas_used_usd": 0.07,
      "fees_usd": 0.34,
      "status": "FILLED",
      "idempotency_key": "cyc01JQ...-slice0"
    }
  ]
}
```

---

## 11. Agent Role Skill Loading Matrix

Each TradingAgents role loads only the Bankr skills relevant to its function scope. Loading skills outside scope is a misconfiguration caught at startup by OpenClaw.

| Agent Role | Must Load | May Load (Situational) |
|---|---|---|
| **Analyst** | `bankr-agent-market-research` `bankr-agent-portfolio` | `bankr-x402-sdk-capabilities` `bankr-x402-sdk-balance-queries` `bankr-agent-llm-gateway` `bankr-agent-polymarket` |
| **Quant** | `bankr-agent-market-research` | `bankr-agent-leverage-trading` `bankr-agent-polymarket` |
| **Trader** | `bankr-agent-token-trading` `bankr-agent-automation` `bankr-agent-job-workflow` | `bankr-agent-leverage-trading` `bankr-agent-polymarket` |
| **Risk** | `bankr-agent-safety-access-control` `bankr-agent-error-handling` | `bankr-agent-arbitrary-transactions` `bankr-agent-leverage-trading` |
| **Executor** | `bankr-agent-token-trading` `bankr-agent-sign-submit-api` `bankr-agent-transfers` `bankr-agent-error-handling` | `bankr-agent-arbitrary-transactions` `bankr-agent-token-deployment` `bankr-agent-nft-operations` |

> **Rule:** The Risk agent must not load execution skills. The Analyst must not load signing or transfer skills. All skill-scope violations are caught at agent startup by OpenClaw and treated as misconfigurations.

---

## 12. Integration Patterns

### Pattern 1 — Standard BankrRail Order (most common)

```
Analyst    → reads market data              (bankr-agent-market-research)
Quant      → sizes position                 (internal HL-TF quant engine)
Trader     → emits TraderDecisionSignal      venue=BANKR_EVM
SAE        → evaluates SAEBankrConfig       (bankr-agent-safety-access-control)
Executor   → constructs BankrSkillRequest   (bankr-agent-token-trading, bankr-agent-sign-submit-api)
BankrSkillClient → submits order            (bankr-dev-api-workflow)
BankrExecutor    → polls for fill           (bankr-agent-job-workflow)
FillReport       → written to DecisionTrace (bankr-agent-error-handling on failure path)
```

### Pattern 2 — DCA Automation Job

```
Trader     → schedules recurring DCA        (bankr-agent-automation)
Jobs layer → persists job state (Redis)     (bankr-dev-automation, idempotency keys)
Each slice → flows through Pattern 1
Circuit breaker → monitors daily volume     (bankr-agent-safety-access-control)
```

### Pattern 3 — Analyst x402 Market Intelligence Query

```
Analyst    → needs cross-chain portfolio context   (bankr-x402-sdk-capabilities)
x402 client → injects payment header              (bankr-x402-sdk-client-patterns)
BankrZerion → returns portfolio data              (bankr-x402-sdk-balance-queries)
Analyst    → normalizes data into signal schema    (bankr-dev-market-research)
```

### Pattern 4 — Event-Driven Polymarket Overlay

```
Analyst    → detects macro event signal            (bankr-agent-market-research)
Analyst    → emits Polymarket position signal      (bankr-agent-polymarket)
SAE        → evaluates notional / action type      (bankr-agent-safety-access-control)
Executor   → opens Polymarket position via Bankr   (bankr-dev-polymarket)
Position   → tracked in DecisionTrace bankr_fills  (bankr-agent-job-workflow)
```

---

## 13. TCA Analyzer Job

**File:** `jobs/bankr_tca_analyzer.py`

Post-trade slippage, gas cost, and fill-rate analysis by chain and action type. Runs after each BankrRail fill batch; feeds results into the observability layer and the RL execution agent's replay buffer.

Metrics tracked per `(chain, action_type)` bucket:
- `avg_slippage_bps` / `p95_slippage_bps`
- `avg_gas_usd` / `p95_gas_usd`
- `fill_rate` (FILLED / total)
- `avg_latency_ms`
- `daily_volume_usd` (cross-checked against Redis circuit breaker counter)

---

## 14. Safety Invariants (Additions to SPEC §9.1)

10. No `BankrRail ExecutionRequest` is submitted without `BankrParams.wallet_id` present in `SAEBankrConfig.walletIdAllowlist`.
11. `BankrRail liveEnabled=true` requires a Clawvisor HITL approval event (`event_type: bankr_rail_live_enabled`) recorded in the `governance_events` table.
12. `BankrExecutor` failures **NEVER** trigger a compensating trade on HyperLiquid or any other venue. Failure propagates as a `FAILED FillReport` only.
13. Bankr fills are written to `DecisionTrace` **atomically** with HL fills. A cycle cannot be marked complete if any BankrRail fill write is pending.
14. `SAEBankrConfig.maxDailyVolumeUsd` is tracked via a rolling counter in Redis key `bankr_daily_volume_{date}`. Exceeding it sets BankrRail to `SUSPENDED` for the remainder of the UTC day. SAE hard-blocks all subsequent BankrRail requests without requiring a restart.

---

## 15. Security Model

| Concern | Control |
|---|---|
| Bankr API keys | Secrets manager (Vault / k8s Secret). Never hardcoded. Env var: `BANKR_API_KEY`. |
| Privy wallet IDs | Stored alongside API keys. Only IDs in `SAEBankrConfig.walletIdAllowlist` may be used. |
| Least privilege | Each Privy wallet scoped to minimum required action types. Swap-only wallet must not be used for deployment. |
| Key rotation | Covered in `bankr-dev-safety-access-control` skill. In-flight orders during rotation propagate as FAILED. |
| x402 wallet | Separate USDC wallet from trading wallets. Funded from treasury only up to `per_cycle_budget_cap`. |
| Log redaction | API keys and wallet IDs are masked in all trace output. `bankr_order_id` and `tx_hash` are logged; secrets are not. |

---

## 16. Repo Layout — New Files Only

```
apps/
  executors/
    bankr_executor.py          # BankrExecutor + BankrSkillClient
    bankr_executor_test.py     # Unit tests with mock Bankr API
  sae-engine/src/
    bankr-policy.ts            # SAEBankrConfig + BankrRail check block
    bankr-policy.test.ts       # SAE unit tests for BankrRail edge cases
proto/
  common.proto                 # VenueRail, BankrActionType, BankrChain (+additions)
  execution.proto              # BankrParams message, extended FillReport (+additions)
config/
  openclaw-skills/
    bankr-rail.skill.json      # OpenClaw skill descriptor / HITL governance
jobs/
  bankr_tca_analyzer.py        # Post-trade TCA: slippage, gas, fill rate by chain/action
multiclaw/bankr/
  README.md                    # BankrRail architecture overview (existing)
  IMPLEMENTATION_PLAN.md       # This document
  docs/
    bankr_openclaw_interface.md  # Concrete interface sketch (existing)
  skills/                      # Bankr skill knowledge packages (submodule)
```

---

## 17. Phased Delivery Plan

### Phase 0 — Proto + SAE Stubs
*Gate: all SAE unit tests green; `defaultSAEBankrConfig` ships all-disabled; no live orders possible.*

| Task | File | Done |
|---|---|---|
| Add `VenueRail`, `BankrActionType`, `BankrChain` enums | `proto/common.proto` | ☐ |
| Add `BankrParams` message, extend `FillReport` | `proto/execution.proto` | ☐ |
| Add `SAEBankrConfig` interface + `defaultSAEBankrConfig` | `apps/sae-engine/src/types.ts` | ☐ |
| Append BankrRail check block to `evaluateExecution()` | `apps/sae-engine/src/bankr-policy.ts` | ☐ |
| Unit tests: edge-case chain/action/notional requests | `apps/sae-engine/src/bankr-policy.test.ts` | ☐ |

---

### Phase 1 — BankrExecutor + Router
*Gate: mock API tests pass; FAILED fills handled gracefully; Orchestrator does NOT reroute to HL on failure.*

| Task | File | Done |
|---|---|---|
| Implement `BankrSkillClient` with retry/idempotency | `apps/executors/bankr_executor.py` | ☐ |
| Implement `BankrExecutor` with defence-in-depth guards | `apps/executors/bankr_executor.py` | ☐ |
| Add `routeExecution()` venue-partition logic | `apps/orchestrator-api/src/executor-router.ts` | ☐ |
| Unit tests: mock Bankr API FILLED/FAILED | `apps/executors/bankr_executor_test.py` | ☐ |

---

### Phase 2 — DecisionTrace + Audit Atomicity
*Gate: 50 paper cycles with mixed HL+Bankr orders; no orphaned fills.*

| Task | File | Done |
|---|---|---|
| Add `bankr_fills` JSONB column to `decision_traces` | DB migration | ☐ |
| Write Bankr fills atomically alongside HL fills | Orchestrator reconciliation | ☐ |
| Validate `idempotency_key` uniqueness per cycle | `bankr_executor.py` | ☐ |

---

### Phase 3 — OpenClaw Skill + HITL Gates
*Gate: all three HITL gate scenarios verified (live promotion, chain addition, large order).*

| Task | File | Done |
|---|---|---|
| Register `bankr-rail.skill.json` with OpenClaw | `config/openclaw-skills/bankr-rail.skill.json` | ☐ |
| Wire `bankr_rail_live_enabled` HITL gate | Clawvisor governance events | ☐ |
| Wire `bankr_allowed_chain_updated` HITL gate | Clawvisor governance events | ☐ |
| Wire large-order gate (≥ $2,500) | SAE + Clawvisor | ☐ |

---

### Phase 4 — Paper Validation
*Gate: Base swap and DCA validated end-to-end; all circuit breaker and outage scenarios pass.*

| Test Scenario | Acceptance Criterion |
|---|---|
| Paper swap: USDC→ETH on Base, $100 notional (`maxNotionalUsd: 500`) | Fills in DecisionTrace; slippage ≤ bound |
| Paper DCA: 5 daily USDC→BTC slices | Each slice idempotent; Redis counter tracks daily volume; no duplicate fills |
| Circuit breaker: inject `maxDailyVolumeUsd` breach mid-session | BankrRail halts; HL perps continue unaffected |
| Bankr API outage: return 500 for all calls | FAILED FillReports emitted; Orchestrator does NOT reroute to HL |
| Audit completeness: 50 mixed HL+Bankr paper cycles | Every cycle has matching `fill_reports` + `bankr_fills`; no orphaned orders |

---

### Phase 5 — x402 Analyst Intelligence
*Gate: Analyst x402 queries cost-tracked and cached; budget cap enforced per cycle.*

| Task | File | Done |
|---|---|---|
| Implement `BankrZerion` x402 client for Analyst | `apps/agents/src/tools/bankr_zerion_client.py` | ☐ |
| Add x402 payment header injection | Per `bankr-x402-sdk-client-patterns` skill | ☐ |
| Per-cycle x402 budget cap in `SAEBankrConfig` | `apps/sae-engine/src/types.ts` | ☐ |
| Cache x402 responses (15-min TTL, Redis) | Per `bankr-x402-sdk-balance-queries` skill | ☐ |
| Unit tests: mock x402 endpoint, verify cost tracking | `apps/agents/tests/` | ☐ |

---

### Phase 6 — TCA Analyzer + Observability
*Gate: Grafana BankrRail dashboard live; TCA output wired to RL replay buffer.*

| Task | File | Done |
|---|---|---|
| Implement `bankr_tca_analyzer.py` | `jobs/bankr_tca_analyzer.py` | ☐ |
| Emit Prometheus metrics: `bankr_executor_{fill_rate,slippage_bps,gas_usd,latency_ms}` | Prometheus / Grafana | ☐ |
| Add BankrRail panel to trading firm dashboard | `apps/dashboard/` | ☐ |
| Wire TCA output to RL execution agent replay buffer | `apps/jobs/src/rl_execution_trainer.py` | ☐ |

---

### Phase 7 — Live Promotion
*Gate: Clawvisor HITL approval recorded; canary live on Base with minimal caps.*

| Step | Action |
|---|---|
| 1 | Operator initiates `bankr_rail_live_enabled` event via Clawvisor |
| 2 | HITL gate opens; Clawvisor approval required within 1 hour |
| 3 | On approval: `liveEnabled=true` written to `SAEConfig`; event recorded in `governance_events` |
| 4 | Initial live parameters: Base only; `BANKR_SWAP` only; `maxNotionalUsd: 500`; `maxDailyVolumeUsd: 5000` |
| 5 | Monitor fill rate, slippage, gas vs. paper benchmarks for ≥ 72 hours |
| 6 | Expand chain allowlist / action types via `bankr_allowed_chain_updated` HITL gates |

---

## 18. Risks & Failure Modes

| Risk | Severity | Mitigation |
|---|---|---|
| Opaque Bankr/Privy internals — signing policy changes or API bugs break execution | Medium | Low-trust adapter pattern; local invariants in `BankrExecutor`; TCA fill-rate monitoring |
| Multi-chain operational complexity — reorgs, MEV, congestion not yet modelled in SAE | Medium | Start with Base only; expand chain allowlist incrementally via HITL gates |
| Architecture discipline drift — developers treating `BankrExecutor` as a peer agent | Low | `bankr-rail.skill.json` enforces `trust_level: low_trust_external`; code review checklist |
| Key scope — Bankr API keys / Privy wallet IDs over-scoped or exposed | High | Secrets manager only; least-privilege Privy policies; key rotation in `bankr-dev-safety-access-control` |
| Bankr API outage during live trading | Medium | FAILED FillReports propagate cleanly; HL perps unaffected; no compensating trades triggered |
| x402 wallet budget exhaustion | Low | Per-cycle budget cap; separate USDC wallet; automated top-up threshold alert |

---

## 19. Validation Plan Summary

| Stage | Action | Pass Criterion |
|---|---|---|
| Unit | Mock Bankr API returns FILLED/FAILED | FillReport shapes match proto; FAILED returns gracefully |
| SAE policy | Inject edge-case chain/action/notional requests | Only allowlisted chains/actions pass; notional clipped correctly |
| Paper — Base | USDC→ETH swap, $100 notional | Fills in DecisionTrace; slippage within bounds |
| OpenClaw HITL | Attempt `liveEnabled=true` without HITL approval | Request blocked; gate opens; approval required |
| Circuit breaker | Inject `maxDailyVolumeUsd` breach mid-session | BankrRail halts; HL perps continue unaffected |
| Bankr API outage | Return 500 for all calls | FAILED FillReports; Orchestrator does NOT reroute to HL |
| Audit completeness | 50 mixed HL+Bankr paper cycles | Every cycle has `fill_reports` + `bankr_fills`; no orphaned orders |

---

## 20. Related Documents

| Document | Location |
|---|---|
| BankrRail integration overview | [`multiclaw/bankr/README.md`](README.md) |
| Concrete interface sketch (proto, SAE, executor, router) | [`multiclaw/bankr/docs/bankr_openclaw_interface.md`](docs/bankr_openclaw_interface.md) |
| Bankr skill orchestration guide | [`multiclaw/bankr/skills/`](skills/) |
| HL-TF master SPEC | [`SPEC.md`](../../SPEC.md) |
| OpenClaw skill descriptor | [`config/openclaw-skills/bankr-rail.skill.json`](../../config/openclaw-skills/bankr-rail.skill.json) |
| Bankr platform | [bankr.bot](https://bankr.bot) |
| Privy agentic wallets | [docs.privy.io](https://docs.privy.io) |
| Zerion x402 integration | [zerion.io/blog/build-best-ai-crypto-agent](https://zerion.io/blog/build-best-ai-crypto-agent) |
| BankrBot Privy case study | [privy.io/blog/bankrbot-case-study](https://privy.io/blog/bankrbot-case-study) |

---

*This document is maintained alongside the BankrRail implementation. Update phase gate checkboxes as each milestone is reached. All changes to safety invariants (§14) require a SPEC.md amendment and Clawvisor governance approval.*
