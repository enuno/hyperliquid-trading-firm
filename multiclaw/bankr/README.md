# BankrRail — Multi-Chain Execution Layer for the HyperLiquid Trading Firm

> **Status:** Research & Design — Paper-trading validation in progress  
> **Integration target:** [`multiclaw/bankr/docs/bankr_openclaw_interface.md`](./docs/bankr_openclaw_interface.md)  
> **Parent system:** [HyperLiquid Autonomous Trading Firm](../../README.md)

---

## Objective

Extend the HyperLiquid Trading Firm (HL-TF) beyond its native HyperLiquid/HyperEVM execution
layer by integrating [Bankr](https://bankr.bot) as a **second execution rail** for EVM and
Solana DeFi actions — while preserving every existing safety guarantee: SAE hard gates,
DecisionTrace audit integrity, OpenClaw governance, and all existing proto contracts.

Bankr is treated as a **low-trust external venue adapter**, architecturally equivalent to
`HyperLiquidExecutor` but targeting Bankr-exposed chains (Base, Ethereum, Polygon, Unichain,
Solana). The agent plane, SAE engine, and TradingAgents pipeline are **unchanged**.

---

## Why Bankr

The HL-TF is purpose-built for HyperLiquid perpetuals. Bankr unlocks complementary
capabilities without requiring the firm to write its own vault contracts, DeFi transaction
infrastructure, or multi-chain wallet stack:

| Capability | Use case in HL-TF |
|---|---|
| Spot swaps (EVM + Solana) | Spot hedges against HL perp positions |
| DCA / limit / stop-loss | Dollar-cost averaging treasury USDC into ETH/BTC spot |
| Leveraged DeFi trades | Basis / carry strategies across EVM venues |
| Lend / borrow | Yield on idle stablecoins between HL trading cycles |
| Polymarket positions | Event-driven strategy overlay; prediction market signals |
| Privy server wallets | Agent-controlled non-custodial wallets with gas sponsorship |
| Zerion x402 feeds | Self-funded per-call portfolio intelligence for the Analyst layer |

---

## Architecture Position

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
HyperLiquidExecutor              BankrExecutor
(perps — existing)           (EVM/Solana DeFi via Bankr)
        │                              │
  HyperLiquid API           Bankr Skill API (OpenClaw Skill)
                                       │
                              Privy Server Wallet
                              (Base / ETH / Polygon /
                               Unichain / Solana)
```

**Key rule:** The SAE emits a single `ExecutionDecision` per cycle. The Orchestrator inspects
the `venue` field of each staged request to route to `HyperLiquidExecutor` or `BankrExecutor`.
**No order ever bypasses SAE, regardless of venue.**

---

## Design Principles

1. **Bankr is execution-only.** All reasoning, research, risk governance, and sizing decisions
   remain inside the TradingAgents-style pipeline. Bankr natural-language agent features are
   not used; only typed skill endpoints are called, with parameters derived from
   `TraderDecisionSignal` → `ExecutionRequest`.

2. **Low trust, defence in depth.** `BankrExecutor` enforces its own wallet allowlist and
   notional bounds as a second line of defence after SAE. It never raises exceptions that
   could trigger compensating trades on another venue — failures always propagate as
   `FAILED` `FillReport` objects.

3. **SAE controls the BankrRail with two independent switches.** `enabled` (master) and
   `liveEnabled` (paper → live promotion gate). Promoting to live requires a Clawvisor HITL
   approval event recorded in the governance ledger.

4. **Atomic audit trail.** `bankr_fills` are written to `DecisionTrace` atomically alongside
   `fill_reports` (HL perp fills). A cycle cannot be marked complete if any BankrRail fill
   write is pending.

5. **Circuit breakers are unconditional.** A Redis rolling counter tracks
   `SAEBankrConfig.maxDailyVolumeUsd`. Exceeding it suspends BankrRail for the rest of the
   UTC day; SAE hard-blocks all subsequent BankrRail requests without requiring a restart.

---

## Components

| Component | Location | Language | Description |
|---|---|---|---|
| `BankrExecutor` | `apps/executors/bankr_executor.py` | Python | Venue adapter; wraps `BankrSkillClient` |
| `BankrSkillClient` | `apps/executors/bankr_executor.py` | Python | HTTP client for Bankr Skill API with idempotency + retry |
| `SAEBankrConfig` | `apps/sae-engine/src/bankr-policy.ts` | TypeScript | Policy block appended to `SAEConfig` |
| `BankrParams` proto | `proto/execution.proto` | Protobuf | Sub-message on `ExecutionRequest` |
| `VenueRail` enum | `proto/common.proto` | Protobuf | `HYPERLIQUID_PERPS \| BANKR_EVM \| BANKR_SOLANA` |
| Executor router | `apps/orchestrator-api/src/executor-router.ts` | TypeScript | Partitions staged requests by `VenueRail` |
| OpenClaw skill | `config/openclaw-skills/bankr-rail.skill.json` | JSON | HITL rules, trust level, observability config |
| TCA analyzer | `jobs/bankr_tca_analyzer.py` | Python | Post-trade slippage/gas/fill-rate analysis by chain and action |

---

## Supported Chains & Actions

**Chains:** Base · Ethereum · Polygon · Unichain · Solana

**Action types:**

| `BankrActionType` | Description |
|---|---|
| `BANKR_SWAP` | Spot token swap |
| `BANKR_LIMIT_ORDER` | Limit buy / sell |
| `BANKR_DCA` | Recurring dollar-cost average |
| `BANKR_STOP_LOSS` | Stop-loss on a DeFi position |
| `BANKR_LEVERAGED_TRADE` | Leveraged long / short on Bankr-supported venues |
| `BANKR_LEND` | Lend tokens to a lending protocol |
| `BANKR_BORROW` | Borrow against collateral |
| `BANKR_POLYMARKET_POSITION` | Open / close a Polymarket prediction market position |

---

## SAE Policy Configuration

All BankrRail requests are governed by `SAEBankrConfig`, appended to the existing `SAEConfig`:

```typescript
interface SAEBankrConfig {
  enabled:             boolean;        // master switch — default false
  liveEnabled:         boolean;        // second switch — requires HITL approval
  allowedChains:       BankrChain[];
  allowedActionTypes:  BankrActionType[];
  maxNotionalUsd:      number;         // hard cap per order
  maxLeverage:         number;         // independent from HL perps cap
  maxDailyVolumeUsd:   number;         // rolling circuit breaker (Redis)
  walletIdAllowlist:   string[];       // Privy wallet IDs permitted for trading
}
```

The default configuration ships with all switches disabled and all caps set to zero.
No live BankrRail order can be placed without explicit operator activation via OpenClaw.

---

## OpenClaw Governance (HITL Gates)

| Event | Gate | Timeout | On timeout |
|---|---|---|---|
| `bankr_rail_live_enabled` | Requires approval | 1 hour | Reject |
| `bankr_allowed_chain_updated` | Requires approval | 30 min | Reject |
| BankrRail order ≥ $2,500 notional | Requires approval | 5 min | Reject |

---

## Safety Invariants (additions to SPEC §9.1)

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
    for the remainder of the UTC day.
```

---

## Validation Plan

| Stage | Action | Pass criterion |
|---|---|---|
| Unit | Mock Bankr API returns FILLED / FAILED — assert `FillReport` shapes match proto | All fields populated; FAILED returns gracefully |
| SAE policy | Inject BankrRail requests with chain / action / notional edge cases | Only allowlisted chains/actions pass; notional clipped correctly |
| Paper — Base swap | DCA USDC→ETH on Base, $100 notional, `max_notional_usd=500` | Fills recorded in DecisionTrace; slippage within bounds |
| OpenClaw HITL | Attempt to set `live_enabled=true` without HITL approval | Request blocked; HITL gate opens; approval required |
| Circuit breaker | Inject `max_daily_volume_usd` breach mid-session | BankrRail halts; HL perps continue unaffected |
| Bankr API outage | Return 500 for all Bankr calls | FAILED FillReports emitted; Orchestrator does NOT reroute to HL |
| Audit completeness | Run 50 paper cycles with mixed HL + Bankr orders | Every cycle has matching `fill_reports` + `bankr_fills`; no orphaned orders |

---

## Risks & Failure Modes

- **Opaque Bankr/Privy internals** — signing policy changes or Bankr API bugs can break
  execution assumptions. Mitigate: treat as low-trust external; wrap in adapter with local
  invariants; monitor fill rate and slippage via TCA analyzer.
- **Multi-chain operational complexity** — Base/Ethereum/Solana introduce chain-specific
  failure modes (reorgs, congestion, MEV) not yet modelled in the SAE.
  Mitigate: start with Base only; expand chain allowlist incrementally.
- **Architecture discipline drift** — developers treating BankrExecutor as a peer agent.
  Mitigate: skill descriptor enforces `trust_level: low_trust_external`; code review checklist.
- **Key scope / security** — Bankr API keys and Privy wallet IDs must be stored in the
  secrets manager (never hardcoded); wallets should use least-privilege Privy policies scoped
  to the approved action types only.

---

## Related Documents

- [`docs/bankr_openclaw_interface.md`](./docs/bankr_openclaw_interface.md) — Full concrete
  interface sketch: proto extensions, `BankrExecutor` Python implementation, SAE policy
  TypeScript, orchestrator router, OpenClaw skill descriptor, DecisionTrace extension,
  and repo layout.
- [Bankr](https://bankr.bot) — Official platform
- [Privy Agentic Wallets](https://docs.privy.io/recipes/agent-integrations/agentic-wallets)
- [Zerion AI Agent Integration](https://zerion.io/blog/build-best-ai-crypto-agent/)
- [BankrBot × Privy Case Study](https://privy.io/blog/bankrbot-case-study)
