# Bankr Integration with OpenClaw & HyperLiquid Trading Firm
## Concrete Interface Sketch — `BankrRail` Venue Adapter

> **Scope:** Extends the HyperLiquid Trading Firm (HL-TF) architecture to support Bankr as a
> second execution rail for EVM/Solana DeFi actions, while preserving SAE hard gates,
> DecisionTrace audit integrity, OpenClaw governance, and all existing proto contracts.
> Bankr is treated as a **low-trust external adapter** — logically equivalent to
> `HyperLiquidExecutor` but targeting Bankr-exposed chains (Base, Ethereum, Polygon,
> Unichain, Solana). The agent plane and SAE are **unchanged**.

---

## 1. Architecture Position

```
OpenClaw Control Plane  (cycle trigger, HITL, governance)
        │
Orchestrator API  (cycle coordinator, typed state store, event bus)
        │
   Agents Svc  (TradingAgents pipeline — unchanged)
        │
   SAE Engine  (deterministic, non-bypassable — unchanged)
        │  ExecutionDecision
   ┌────┴──────────────────────────────────────────────┐
   │                                                   │
HyperLiquidExecutor              BankrExecutor          ← NEW
(perps — existing)           (EVM/Solana DeFi via Bankr)
        │                              │
  HyperLiquid API           Bankr Skill API (OpenClaw Skill)
                                       │
                              Privy Server Wallet
                              (Base / ETH / Polygon /
                               Unichain / Solana)
```

**Key rule:** SAE emits a single `ExecutionDecision` per cycle. The Orchestrator inspects
the `venue` field in the approved `ExecutionRequest` to route to either executor.
No order ever bypasses SAE regardless of venue.

---

## 2. Proto Contract Extensions

### 2.1  `common.proto` — add `VenueRail` enum

```protobuf
// proto/common.proto  (addition only — no existing fields changed)

enum VenueRail {
  VENUE_RAIL_UNSPECIFIED = 0;
  HYPERLIQUID_PERPS      = 1;  // existing
  BANKR_EVM              = 2;  // NEW — Base, ETH, Polygon, Unichain
  BANKR_SOLANA           = 3;  // NEW — Solana
}

enum BankrActionType {
  BANKR_ACTION_UNSPECIFIED = 0;
  BANKR_SWAP               = 1;  // spot swap
  BANKR_LIMIT_ORDER        = 2;  // limit buy/sell
  BANKR_DCA                = 3;  // recurring DCA
  BANKR_STOP_LOSS          = 4;
  BANKR_LEVERAGED_TRADE    = 5;  // leveraged long/short
  BANKR_LEND               = 6;  // lend to protocol
  BANKR_BORROW             = 7;
  BANKR_POLYMARKET_POSITION = 8; // prediction market
}

enum BankrChain {
  BANKR_CHAIN_UNSPECIFIED = 0;
  BASE                    = 1;
  ETHEREUM                = 2;
  POLYGON                 = 3;
  UNICHAIN                = 4;
  SOLANA                  = 5;
}
```

### 2.2  `execution.proto` — extend `ExecutionRequest`

```protobuf
// proto/execution.proto  (additions to existing ExecutionRequest message)

message ExecutionRequest {
  tradingfirm.common.Meta       meta           = 1;
  string                        asset          = 2;   // e.g. "BTC-PERP", "USDC", "ETH"
  tradingfirm.common.Direction  action         = 3;
  double                        notional_usd   = 4;
  double                        leverage       = 5;
  string                        algo           = 6;   // TWAP, VWAP, MARKET, LIMIT, DCA …
  uint32                        max_slippage_bps = 7;
  bool                          reduce_only    = 8;
  string                        tif            = 9;

  // ── NEW: venue routing ──────────────────────────────────────────────────
  tradingfirm.common.VenueRail  venue          = 10;  // default = HYPERLIQUID_PERPS
  BankrParams                   bankr_params   = 11;  // populated iff venue = BANKR_*
}

// New message — only present when venue is BANKR_EVM or BANKR_SOLANA
message BankrParams {
  tradingfirm.common.BankrChain  chain              = 1;
  tradingfirm.common.BankrActionType action_type    = 2;
  string                         from_token         = 3;  // e.g. "USDC"
  string                         to_token           = 4;  // e.g. "ETH"
  double                         from_amount        = 5;  // in from_token units
  double                         limit_price        = 6;  // for LIMIT / STOP_LOSS
  uint32                         dca_interval_secs  = 7;  // for DCA
  uint32                         dca_periods        = 8;
  string                         protocol_hint      = 9;  // "uniswap", "aave", etc.
  bool                           sponsored_gas      = 10; // request Bankr gas sponsorship
  string                         wallet_id          = 11; // Privy server wallet ID
  map<string, string>            extra              = 12; // forward-compat extension bag
}
```

### 2.3  `execution.proto` — extend `FillReport`

```protobuf
message FillReport {
  tradingfirm.common.Meta  meta            = 1;
  string                   venue_order_id  = 2;
  string                   asset           = 3;
  double                   filled_qty      = 4;
  double                   avg_price       = 5;
  double                   fees_usd        = 6;
  double                   slippage_bps    = 7;
  string                   status          = 8;   // FILLED | PARTIAL | FAILED | PENDING

  // ── NEW ─────────────────────────────────────────────────────────────────
  tradingfirm.common.VenueRail  venue      = 9;
  string                   onchain_tx_hash = 10;  // Bankr fills — EVM/Solana tx
  string                   chain_name      = 11;  // "base", "solana", etc.
  double                   gas_used_usd    = 12;
  string                   bankr_order_id  = 13;  // Bankr internal order ref
}
```

---

## 3. SAE Engine — BankrRail Policy Extension

SAE remains **deterministic and LLM-free**. The only change is an additional check block
for requests routed to Bankr. All existing invariants are preserved.

```typescript
// apps/sae-engine/src/sae-engine.ts  (addition to evaluateExecution)

import { ExecutionRequest, ExecutionContext, ExecutionDecision } from './types';
import { VenueRail } from '../../proto/common';
import { SAEBankrConfig }  from './types';

export function evaluateExecution(
  req: ExecutionRequest,
  ctx: ExecutionContext,
): ExecutionDecision {
  // ── existing checks (unchanged) ────────────────────────────────────────
  const violated: string[] = [];
  let sizeUsd = req.notionalUsd;

  // ... all existing Layer 0-3 checks ...

  // ── NEW: BankrRail-specific checks ─────────────────────────────────────
  if (req.venue === VenueRail.BANKR_EVM || req.venue === VenueRail.BANKR_SOLANA) {
    const bc = ctx.saeConfig.bankr;                      // SAEBankrConfig (see below)

    if (!bc.enabled) {
      violated.push('BANKR_RAIL_DISABLED');
    }

    if (!bc.allowedChains.includes(req.bankrParams?.chain!)) {
      violated.push('BANKR_CHAIN_NOT_ALLOWED');
    }

    if (!bc.allowedActionTypes.includes(req.bankrParams?.actionType!)) {
      violated.push('BANKR_ACTION_TYPE_NOT_ALLOWED');
    }

    // Bankr rail has a tighter notional cap than HL perps
    const bankrNotionalCap = bc.maxNotionalUsd;
    if (sizeUsd > bankrNotionalCap) {
      violated.push('BANKR_NOTIONAL_EXCEEDED');
      sizeUsd = bankrNotionalCap;
    }

    // Leverage on Bankr is capped independently (DeFi leverage is venue-specific risk)
    const bankrMaxLev = bc.maxLeverage;
    if (req.leverage > bankrMaxLev) {
      violated.push('BANKR_LEVERAGE_CLIPPED');
      // clipped — not rejected unless leverage === 1 limit exceeded hard
    }

    // No Bankr orders allowed in LIVE mode until BankrRail is promoted
    if (ctx.mode === 'live' && !bc.liveEnabled) {
      violated.push('BANKR_LIVE_NOT_ENABLED');
    }
  }

  if (violated.some(v => [
    'BANKR_RAIL_DISABLED',
    'BANKR_CHAIN_NOT_ALLOWED',
    'BANKR_ACTION_TYPE_NOT_ALLOWED',
    'BANKR_LIVE_NOT_ENABLED',
  ].includes(v))) {
    return {
      id: req.meta.cycleId,
      allowed: false,
      checksFailed: violated,
      checksPassed: [],
      stagedRequests: [],
      rejectionReason: `BankrRail blocked: ${violated.join(', ')}`,
    };
  }

  // All checks passed — emit approval (size may be clipped)
  return {
    id: req.meta.cycleId,
    allowed: true,
    checksPassed: ['BANKR_RAIL_POLICY'],
    checksFailed: violated,   // soft violations included for audit
    stagedRequests: [{ ...req, notionalUsd: sizeUsd }],
    rejectionReason: '',
  };
}
```

### 3.1  `SAEBankrConfig` interface

```typescript
// apps/sae-engine/src/types.ts  (append to SAEConfig)

export interface SAEBankrConfig {
  enabled:          boolean;        // master switch — default false
  liveEnabled:      boolean;        // second switch — must be true for live orders
  allowedChains:    BankrChain[];   // e.g. [BankrChain.BASE, BankrChain.SOLANA]
  allowedActionTypes: BankrActionType[];  // e.g. [BANKR_SWAP, BANKR_DCA]
  maxNotionalUsd:   number;         // hard cap per order, e.g. 5000
  maxLeverage:      number;         // e.g. 2.0 (lower than HL perps cap)
  maxDailyVolumeUsd: number;        // circuit breaker — total Bankr volume per day
  walletIdAllowlist: string[];      // Privy wallet IDs permitted for trading
}

// Append to existing SAEConfig:
export interface SAEConfig {
  // ... existing fields unchanged ...
  bankr: SAEBankrConfig;
}

// Recommended default (start disabled):
export const defaultSAEBankrConfig: SAEBankrConfig = {
  enabled:            false,
  liveEnabled:        false,
  allowedChains:      [],
  allowedActionTypes: [],
  maxNotionalUsd:     0,
  maxLeverage:        1.0,
  maxDailyVolumeUsd:  0,
  walletIdAllowlist:  [],
};
```

---

## 4. BankrExecutor — Python Implementation

```python
# apps/executors/bankr_executor.py
"""
BankrExecutor  —  execution adapter for Bankr-skill-backed DeFi orders.

Contract:
  Input:  ExecutionDecision with venue = BANKR_EVM or BANKR_SOLANA
  Output: FillReport

Trust model:
  - This adapter is LOW-TRUST external infrastructure.
  - Every call is wrapped in retry + timeout logic.
  - All inputs are already SAE-approved; this adapter does NOT re-validate policy.
  - All results are written to DecisionAuditLog before being returned.
  - On any Bankr API failure: return FAILED FillReport; do NOT raise to the
    Orchestrator in a way that could trigger a fallback trade on another venue.
"""

import uuid
import time
import logging
from dataclasses import dataclass, field
from typing import Optional
import httpx

log = logging.getLogger(__name__)

# ── Bankr Skill API wrapper ─────────────────────────────────────────────────

BANKR_SKILL_BASE = "https://api.bankr.bot/v1"   # update when Bankr publishes stable SDK

@dataclass
class BankrSkillRequest:
    """Typed mapping from ExecutionRequest.BankrParams → Bankr Skill API payload."""
    wallet_id:       str
    chain:           str             # "base" | "ethereum" | "polygon" | "unichain" | "solana"
    action_type:     str             # "swap" | "limit" | "dca" | "stop_loss" | "leverage" | "lend"
    from_token:      str
    to_token:        str
    from_amount:     float
    limit_price:     Optional[float] = None
    dca_interval:    Optional[int]   = None   # seconds
    dca_periods:     Optional[int]   = None
    max_slippage_bps: int            = 50
    sponsored_gas:   bool            = True
    idempotency_key: str             = field(default_factory=lambda: str(uuid.uuid4()))
    protocol_hint:   Optional[str]   = None   # "uniswap" | "aave" | None


@dataclass
class BankrSkillResponse:
    order_id:     str
    status:       str    # "submitted" | "filled" | "failed" | "pending"
    tx_hash:      Optional[str]
    filled_qty:   float
    avg_price:    float
    fees_usd:     float
    slippage_bps: float
    gas_used_usd: float
    chain:        str
    error_msg:    Optional[str] = None


class BankrSkillClient:
    """
    Thin HTTP client wrapping the Bankr skill endpoint.
    Replace with official Bankr SDK when available.
    Uses idempotency keys for safe retries.
    """

    def __init__(self, api_key: str, timeout: float = 15.0, max_retries: int = 3):
        self._api_key    = api_key
        self._timeout    = timeout
        self._max_retries = max_retries

    def submit_order(self, req: BankrSkillRequest) -> BankrSkillResponse:
        payload = {
            "wallet_id":        req.wallet_id,
            "chain":            req.chain,
            "action":           req.action_type,
            "from_token":       req.from_token,
            "to_token":         req.to_token,
            "from_amount":      req.from_amount,
            "limit_price":      req.limit_price,
            "dca_interval_sec": req.dca_interval,
            "dca_periods":      req.dca_periods,
            "max_slippage_bps": req.max_slippage_bps,
            "sponsored_gas":    req.sponsored_gas,
            "protocol_hint":    req.protocol_hint,
        }
        headers = {
            "Authorization":    f"Bearer {self._api_key}",
            "Idempotency-Key":  req.idempotency_key,
            "Content-Type":     "application/json",
        }
        last_err: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.post(
                        f"{BANKR_SKILL_BASE}/orders",
                        json=payload,
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return BankrSkillResponse(
                        order_id     = data["order_id"],
                        status       = data["status"],
                        tx_hash      = data.get("tx_hash"),
                        filled_qty   = float(data.get("filled_qty", 0)),
                        avg_price    = float(data.get("avg_price", 0)),
                        fees_usd     = float(data.get("fees_usd", 0)),
                        slippage_bps = float(data.get("slippage_bps", 0)),
                        gas_used_usd = float(data.get("gas_used_usd", 0)),
                        chain        = data.get("chain", req.chain),
                    )
            except Exception as e:
                last_err = e
                wait = 2 ** attempt
                log.warning(
                    "BankrSkillClient: attempt %d/%d failed (%s), retrying in %ds",
                    attempt, self._max_retries, e, wait,
                )
                time.sleep(wait)

        # All retries exhausted — return a FAILED response (do NOT raise)
        log.error("BankrSkillClient: all retries exhausted for order %s", req.idempotency_key)
        return BankrSkillResponse(
            order_id     = req.idempotency_key,
            status       = "failed",
            tx_hash      = None,
            filled_qty   = 0.0,
            avg_price    = 0.0,
            fees_usd     = 0.0,
            slippage_bps = 0.0,
            gas_used_usd = 0.0,
            chain        = req.chain,
            error_msg    = str(last_err),
        )


# ── BankrExecutor ───────────────────────────────────────────────────────────

CHAIN_ENUM_TO_STR = {
    1: "base",
    2: "ethereum",
    3: "polygon",
    4: "unichain",
    5: "solana",
}

ACTION_ENUM_TO_STR = {
    1: "swap",
    2: "limit",
    3: "dca",
    4: "stop_loss",
    5: "leverage",
    6: "lend",
    7: "borrow",
    8: "polymarket",
}


class BankrExecutor:
    """
    Venue adapter — routes SAE-approved ExecutionDecision.stagedRequests
    with venue=BANKR_EVM/BANKR_SOLANA to the Bankr skill API.

    Invariants enforced here (defence-in-depth, SAE is still primary):
      - Wallet ID must be in the local allowlist (matches SAE config).
      - notional_usd must be > 0 and <= hard_cap_usd.
      - On any failure: log, record FAILED FillReport, return — never raise.
      - idempotency_key is derived from cycleId + sliceIndex so retries are safe.
    """

    def __init__(
        self,
        client:          BankrSkillClient,
        wallet_allowlist: list[str],
        hard_cap_usd:    float,
        audit_logger,    # reference to DecisionAuditLogger
    ):
        self._client          = client
        self._wallet_allowlist = set(wallet_allowlist)
        self._hard_cap_usd    = hard_cap_usd
        self._audit           = audit_logger

    def execute(self, decision, cycle_id: str) -> list[dict]:
        """
        Execute all staged BankrRail requests from an ExecutionDecision.
        Returns a list of FillReport dicts (matching FillReport proto shape).
        """
        fill_reports = []
        for i, req in enumerate(decision.staged_requests):
            fill = self._execute_one(req, cycle_id, slice_index=i)
            fill_reports.append(fill)
            # Write to audit log BEFORE returning
            self._audit.write_fill(cycle_id=cycle_id, fill_report=fill)
        return fill_reports

    def _execute_one(self, req, cycle_id: str, slice_index: int) -> dict:
        bp = req.bankr_params
        wallet_id = bp.wallet_id

        # Defence-in-depth guard
        if wallet_id not in self._wallet_allowlist:
            log.error("BankrExecutor: wallet %s not in allowlist — rejecting", wallet_id)
            return self._failed_fill(req, cycle_id, "WALLET_NOT_ALLOWED")

        if req.notional_usd <= 0 or req.notional_usd > self._hard_cap_usd:
            log.error(
                "BankrExecutor: notional %.2f out of range [0, %.2f]",
                req.notional_usd, self._hard_cap_usd,
            )
            return self._failed_fill(req, cycle_id, "NOTIONAL_OUT_OF_RANGE")

        skill_req = BankrSkillRequest(
            wallet_id        = wallet_id,
            chain            = CHAIN_ENUM_TO_STR.get(bp.chain, "base"),
            action_type      = ACTION_ENUM_TO_STR.get(bp.action_type, "swap"),
            from_token       = bp.from_token,
            to_token         = bp.to_token,
            from_amount      = bp.from_amount,
            limit_price      = bp.limit_price or None,
            dca_interval     = bp.dca_interval_secs or None,
            dca_periods      = bp.dca_periods or None,
            max_slippage_bps = req.max_slippage_bps,
            sponsored_gas    = bp.sponsored_gas,
            protocol_hint    = bp.protocol_hint or None,
            idempotency_key  = f"{cycle_id}-slice{slice_index}",
        )

        log.info(
            "BankrExecutor: submitting order cycle=%s slice=%d chain=%s action=%s "
            "from=%s to=%s amount=%.4f",
            cycle_id, slice_index,
            skill_req.chain, skill_req.action_type,
            skill_req.from_token, skill_req.to_token, skill_req.from_amount,
        )

        resp = self._client.submit_order(skill_req)

        return {
            "meta": {
                "cycle_id":            cycle_id,
                "correlation_id":      req.meta.correlation_id,
                "strategy_version":    req.meta.strategy_version,
                "prompt_policy_version": req.meta.prompt_policy_version,
            },
            "venue_order_id":   resp.order_id,
            "asset":            f"{skill_req.from_token}/{skill_req.to_token}",
            "filled_qty":       resp.filled_qty,
            "avg_price":        resp.avg_price,
            "fees_usd":         resp.fees_usd,
            "slippage_bps":     resp.slippage_bps,
            "status":           resp.status,
            "venue":            "BANKR_EVM" if bp.chain <= 4 else "BANKR_SOLANA",
            "onchain_tx_hash":  resp.tx_hash,
            "chain_name":       resp.chain,
            "gas_used_usd":     resp.gas_used_usd,
            "bankr_order_id":   resp.order_id,
        }

    def _failed_fill(self, req, cycle_id: str, reason: str) -> dict:
        return {
            "meta":            {"cycle_id": cycle_id},
            "venue_order_id":  "",
            "asset":           getattr(req, "asset", "UNKNOWN"),
            "filled_qty":      0.0,
            "avg_price":       0.0,
            "fees_usd":        0.0,
            "slippage_bps":    0.0,
            "status":          "FAILED",
            "venue":           "BANKR_EVM",
            "onchain_tx_hash": None,
            "chain_name":      "",
            "gas_used_usd":    0.0,
            "bankr_order_id":  "",
            "error_reason":    reason,
        }
```

---

## 5. Orchestrator Routing Extension

```typescript
// apps/orchestrator-api/src/executor-router.ts  (addition)

import { ExecutionDecision, VenueRail } from '../../proto';
import { HyperLiquidExecutor }  from './executors/hyperliquid';
import { BankrExecutor }        from './executors/bankr';      // new

export async function routeExecution(
  decision: ExecutionDecision,
  cycleId:  string,
  hyper:    HyperLiquidExecutor,
  bankr:    BankrExecutor,
): Promise<FillReport[]> {

  // Partition staged requests by venue
  const hyperRequests = decision.stagedRequests
    .filter(r => r.venue === VenueRail.HYPERLIQUID_PERPS || !r.venue);

  const bankrRequests = decision.stagedRequests
    .filter(r => r.venue === VenueRail.BANKR_EVM || r.venue === VenueRail.BANKR_SOLANA);

  const fills: FillReport[] = [];

  // Execute in parallel only if both are independent orders
  // (do NOT fan-out if one is a hedge of the other — sequence them)
  if (hyperRequests.length > 0) {
    const hFills = await hyper.execute({ ...decision, stagedRequests: hyperRequests }, cycleId);
    fills.push(...hFills);
  }

  if (bankrRequests.length > 0) {
    const bFills = await bankr.execute({ ...decision, stagedRequests: bankrRequests }, cycleId);
    fills.push(...bFills);
  }

  return fills;
}
```

---

## 6. OpenClaw Skill Registration  (BankrRail governance surface)

```json
// config/openclaw-skills/bankr-rail.skill.json
// Declares the BankrRail to OpenClaw so operators can:
//   - enable/disable the rail from the control plane
//   - set per-chain and per-action allowlists
//   - trigger HITL gates before first live BankrRail order

{
  "skill_id":      "bankr-rail-v1",
  "display_name":  "BankrRail — EVM/Solana DeFi Executor",
  "version":       "1.0.0",
  "vendor":        "bankr.bot",
  "trust_level":   "low_trust_external",
  "rail":          "bankr",
  "governance": {
    "requires_hitl_for_live_promotion": true,
    "requires_hitl_for_chain_addition": true,
    "sae_config_key":                  "bankr"
  },
  "default_sae_policy": {
    "enabled":              false,
    "live_enabled":         false,
    "allowed_chains":       [],
    "allowed_action_types": [],
    "max_notional_usd":     0,
    "max_leverage":         1.0,
    "max_daily_volume_usd": 0,
    "wallet_id_allowlist":  []
  },
  "hitl_rules": [
    {
      "name":               "bankr_live_promotion",
      "when":               { "event_type": "bankr_rail_live_enabled" },
      "require_approval":   true,
      "timeout_seconds":    3600,
      "on_timeout":         "reject"
    },
    {
      "name":               "bankr_chain_addition",
      "when":               { "event_type": "bankr_allowed_chain_updated" },
      "require_approval":   true,
      "timeout_seconds":    1800,
      "on_timeout":         "reject"
    },
    {
      "name":               "bankr_large_order",
      "when":               { "bankr_notional_usd_gte": 2500 },
      "require_approval":   true,
      "timeout_seconds":    300,
      "on_timeout":         "reject"
    }
  ],
  "observability": {
    "metrics_prefix":  "bankr_executor",
    "required_labels": ["chain", "action_type", "status", "cycle_id"]
  }
}
```

---

## 7. DecisionTrace Extension

The existing `DecisionTrace` JSON stored in Postgres gains a `bankr_fills` array alongside
`fill_reports` (the HL fills). Both are written atomically before reconciliation.

```json
// Postgres: decision_traces table — bankr_fills field addition
{
  "cycle_id":   "cyc01JQ...",
  "asset":      "BTC-PERP",
  "mode":       "paper",

  "...existing fields...": "...",

  "fill_reports": [
    { "venue": "HYPERLIQUID_PERPS", "venue_order_id": "hl-abc123", "status": "FILLED", "..." }
  ],

  "bankr_fills": [
    {
      "venue":           "BANKR_EVM",
      "chain_name":      "base",
      "bankr_order_id":  "bnkr-xyz789",
      "onchain_tx_hash": "0xabc...def",
      "asset":           "USDC/ETH",
      "filled_qty":      0.42,
      "avg_price":       2380.10,
      "slippage_bps":    12,
      "gas_used_usd":    0.07,
      "fees_usd":        0.34,
      "status":          "FILLED",
      "idempotency_key": "cyc01JQ...-slice0"
    }
  ]
}
```

---

## 8. Repo Layout — New Files Only

```
apps/
  executors/
    bankr_executor.py          ← BankrExecutor + BankrSkillClient
    bankr_executor_test.py     ← unit tests with mock Bankr API
  sae-engine/src/
    bankr-policy.ts            ← SAEBankrConfig + BankrRail check block
    bankr-policy.test.ts

proto/
  common.proto                 ← + VenueRail, BankrActionType, BankrChain enums
  execution.proto              ← + BankrParams, extended FillReport

config/
  openclaw-skills/
    bankr-rail.skill.json      ← OpenClaw skill descriptor

jobs/
  bankr_tca_analyzer.py        ← post-trade TCA: slippage, gas, fill rate by chain/action
```

---

## 9. Validation Plan

| Stage | Action | Pass Criterion |
|---|---|---|
| **Unit** | Mock Bankr API returns FILLED/FAILED — assert FillReport shapes match proto | All fields populated; FAILED returns gracefully |
| **SAE policy** | Inject BankrRail requests with chain/action/notional edge cases | Only allowlisted chains/actions pass; notional clipped correctly |
| **Paper — Base swap** | DCA USDC→ETH on Base, $100 notional, SAE `max_notional_usd=500` | Fills recorded in DecisionTrace; slippage within bounds |
| **OpenClaw HITL** | Attempt to set `live_enabled=true` without HITL approval | Request blocked; HITL gate opens; approval required |
| **Circuit breaker** | Inject `max_daily_volume_usd` breach mid-session | BankrRail halts; HL perps continue unaffected |
| **Bankr API outage** | Return 500 for all Bankr calls | FAILED FillReports emitted; Orchestrator does NOT reroute to HL; cycle completes with partial fills |
| **Audit completeness** | Run 50 paper cycles with mixed HL + Bankr orders | Every cycle has matching HL fill_reports + bankr_fills; no orphaned orders |

---

## 10. Safety Invariants — BankrRail Additions to SPEC Section 9.1

```
10. No BankrRail ExecutionRequest is submitted without BankrParams.wallet_id
    present in SAEBankrConfig.walletIdAllowlist.

11. BankrRail live_enabled=true requires a Clawvisor HITL approval event
    (event_type: bankr_rail_live_enabled) recorded in governance_events table.

12. BankrExecutor failures NEVER trigger a compensating trade on HyperLiquid
    or any other venue. Failure propagates as a FAILED FillReport only.

13. Bankr fills are written to DecisionTrace atomically with HL fills.
    A cycle cannot be marked "complete" if any BankrRail fill write is pending.

14. SAEBankrConfig.maxDailyVolumeUsd is tracked via a rolling counter in Redis
    (key: bankr:daily_volume:{date}). Exceeding it sets BankrRail to SUSPENDED
    for the remainder of the UTC day; SAE hard-blocks all subsequent BankrRail
    requests without requiring a restart.
```
