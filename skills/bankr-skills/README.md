# Bankr Skills — Agent Orchestration Guide

> **Parent integration:** [`multiclaw/bankr/README.md`](../../multiclaw/bankr/README.md)  
> **Interface sketch:** [`multiclaw/bankr/docs/bankr_openclaw_interface.md`](../../multiclaw/bankr/docs/bankr_openclaw_interface.md)  
> **OpenClaw skill descriptor:** [`config/openclaw-skills/bankr-rail.skill.json`](../../config/openclaw-skills/bankr-rail.skill.json)

This directory contains Bankr skill knowledge packages organized into three families:

| Prefix | Audience | Purpose |
|---|---|---|
| `bankr-agent-*` | AI agent layer (TradingAgents pipeline) | Behavioral guidance — what an agent *should* do and *must not* do when invoking Bankr capabilities |
| `bankr-dev-*` | Developer / integration layer | Implementation patterns — how to wire Bankr API calls into HL-TF services |
| `bankr-x402-sdk-*` | x402 micropayment layer | SDK patterns for per-call Bankr data access funded via Zerion x402 USDC micropayments |

---

## Why These Skills Exist

The HyperLiquid Trading Firm uses a TradingAgents-style pipeline in which specialized agent roles (Analyst, Quant, Trader, Risk, Executor) collaborate under OpenClaw governance and a deterministic SAE safety layer. Bankr extends that pipeline to EVM and Solana DeFi execution without changing the agent logic or SAE contracts.

**These skill packages solve a specific problem:** the agents and developers working inside HL-TF need precise, scoped behavioral contracts for each Bankr capability — not Bankr's public user-facing documentation, but rules and patterns expressed in terms of HL-TF's own architecture (SAE policy, `ExecutionRequest`, `FillReport`, `DecisionTrace`, OpenClaw HITL).

Each skill subdirectory is intended to be loaded as a context module by an agent role or referenced by a developer implementing the corresponding `BankrExecutor` component.

---

## Skill Map — Agent Layer (`bankr-agent-*`)

These skills define **behavioral contracts for AI agents**. Each is scoped to a single Bankr capability domain. An agent role should load only the skills relevant to its function.

| Skill | Primary agent role | What it governs |
|---|---|---|
| [`bankr-agent-agent-profiles`](./bankr-agent-agent-profiles/) | Orchestrator / OpenClaw | Agent identity, wallet ownership, trust boundaries, multi-agent delegation rules |
| [`bankr-agent-arbitrary-transactions`](./bankr-agent-arbitrary-transactions/) | Risk · Executor | When arbitrary onchain transactions are permitted; SAE pre-approval requirements; what constitutes an unsafe call |
| [`bankr-agent-automation`](./bankr-agent-automation/) | Trader · Executor | Scheduling DCA, recurring orders, and automated job pipelines; idempotency expectations; cancellation semantics |
| [`bankr-agent-error-handling`](./bankr-agent-error-handling/) | All roles | How agents interpret and propagate Bankr API errors; retry logic; what constitutes a hard stop vs. a soft retry |
| [`bankr-agent-job-workflow`](./bankr-agent-job-workflow/) | Orchestrator · Trader | Lifecycle of a Bankr job (submit → pending → filled/failed); how agents poll, timeout, and reconcile |
| [`bankr-agent-leverage-trading`](./bankr-agent-leverage-trading/) | Trader · Risk | Leverage cap enforcement; interaction with `SAEBankrConfig.maxLeverage`; prohibited leverage action types |
| [`bankr-agent-llm-gateway`](./bankr-agent-llm-gateway/) | Analyst · Orchestrator | Using Bankr's LLM gateway for market intelligence queries; prompt construction; response parsing and validation |
| [`bankr-agent-market-research`](./bankr-agent-market-research/) | Analyst | Querying Bankr market data endpoints; combining Bankr signals with existing Zerion/HyperLiquid feeds |
| [`bankr-agent-nft-operations`](./bankr-agent-nft-operations/) | Executor | NFT buy/sell/transfer mechanics; when NFT actions are in scope for the trading firm (narrow use cases only) |
| [`bankr-agent-polymarket`](./bankr-agent-polymarket/) | Analyst · Trader | Opening and closing Polymarket positions as an event-driven strategy overlay; position sizing constraints |
| [`bankr-agent-portfolio`](./bankr-agent-portfolio/) | Analyst · Risk | Reading cross-chain portfolio state via Bankr; reconciling with HL-TF internal position tracking |
| [`bankr-agent-safety-access-control`](./bankr-agent-safety-access-control/) | SAE · Risk | Wallet allowlists; action-type restrictions; per-agent permission scope; circuit breaker behavior |
| [`bankr-agent-sign-submit-api`](./bankr-agent-sign-submit-api/) | Executor | Transaction signing flow; when to use sponsored gas; how agents submit signed transactions via the Bankr API |
| [`bankr-agent-token-deployment`](./bankr-agent-token-deployment/) | Executor | Token contract deployment via Bankr; authorization gates; when deployment actions require HITL approval |
| [`bankr-agent-token-trading`](./bankr-agent-token-trading/) | Trader · Executor | Spot token swaps, limit orders, stop-losses; mapping `BankrActionType` enums to agent decision signals |
| [`bankr-agent-transfers`](./bankr-agent-transfers/) | Executor | Cross-chain token transfers; wallet-to-wallet and protocol-to-wallet flows; audit trail requirements |

---

## Skill Map — Developer Layer (`bankr-dev-*`)

These skills define **implementation patterns for engineers** building `BankrExecutor`, `BankrSkillClient`, and related services inside HL-TF.

| Skill | Primary component | What it implements |
|---|---|---|
| [`bankr-dev-api-basics`](./bankr-dev-api-basics/) | `BankrSkillClient` | Authentication, base URL, rate limits, error codes, pagination, and API versioning |
| [`bankr-dev-api-workflow`](./bankr-dev-api-workflow/) | `BankrSkillClient` | End-to-end order lifecycle: construct → sign → submit → poll → reconcile |
| [`bankr-dev-arbitrary-transactions`](./bankr-dev-arbitrary-transactions/) | `BankrExecutor` | Encoding and submitting arbitrary EVM/Solana calldata; ABI encoding patterns |
| [`bankr-dev-automation`](./bankr-dev-automation/) | Jobs layer | Implementing recurring job scheduling; Redis-backed job state; idempotency keys for DCA and stop-loss orders |
| [`bankr-dev-client-patterns`](./bankr-dev-client-patterns/) | `BankrSkillClient` | HTTP client construction; retry-with-backoff; timeout handling; idempotency key design |
| [`bankr-dev-leverage-trading`](./bankr-dev-leverage-trading/) | `BankrExecutor` | Leverage order construction; collateral management; interaction with Bankr leveraged trade endpoints |
| [`bankr-dev-market-research`](./bankr-dev-market-research/) | Data ingestion | Polling Bankr market data; normalizing responses into HL-TF's internal signal schema |
| [`bankr-dev-nft-operations`](./bankr-dev-nft-operations/) | `BankrExecutor` | NFT action API calls; metadata handling; transaction confirmation |
| [`bankr-dev-polymarket`](./bankr-dev-polymarket/) | `BankrExecutor` | Polymarket position API; order book access; settlement and resolution queries |
| [`bankr-dev-portfolio`](./bankr-dev-portfolio/) | Reconciliation jobs | Cross-chain balance queries; position snapshot construction; drift detection vs. internal ledger |
| [`bankr-dev-project-templates`](./bankr-dev-project-templates/) | Scaffolding | Starter templates for new Bankr-integrated services; directory layout conventions; config schema |
| [`bankr-dev-safety-access-control`](./bankr-dev-safety-access-control/) | `SAEBankrConfig` | Implementing wallet allowlists, action-type restrictions, and daily volume circuit breakers in code |
| [`bankr-dev-sign-submit-api`](./bankr-dev-sign-submit-api/) | `BankrSkillClient` | Privy server wallet signing flow; gas sponsorship; transaction submission and receipt parsing |
| [`bankr-dev-token-deployment`](./bankr-dev-token-deployment/) | `BankrExecutor` | ERC-20 / SPL token deployment via Bankr API; constructor parameters; deployment confirmation |
| [`bankr-dev-token-trading`](./bankr-dev-token-trading/) | `BankrExecutor` | Swap, limit, and stop-loss order construction; slippage parameters; protocol hint routing |
| [`bankr-dev-transfers`](./bankr-dev-transfers/) | `BankrExecutor` | Token transfer construction; multi-hop bridge patterns; confirmation and receipt handling |

---

## Skill Map — x402 SDK Layer (`bankr-x402-sdk-*`)

These skills cover the **Zerion x402 micropayment SDK**, which Bankr integrates to enable per-API-call data access funded by USDC micropayments. In HL-TF, this is the primary mechanism for the Analyst agent to access Bankr/Zerion market intelligence without flat-rate subscriptions.

| Skill | HL-TF use case | What it covers |
|---|---|---|
| [`bankr-x402-sdk-balance-queries`](./bankr-x402-sdk-balance-queries/) | Analyst — cross-chain balance reads | Querying wallet and protocol balances via x402-gated endpoints; cost per call; result caching strategy |
| [`bankr-x402-sdk-capabilities`](./bankr-x402-sdk-capabilities/) | Integration planning | Enumeration of all x402-gated Bankr capabilities; access tiers; which endpoints require x402 vs. API key |
| [`bankr-x402-sdk-client-patterns`](./bankr-x402-sdk-client-patterns/) | `BankrSkillClient` | x402 HTTP client construction; payment header injection; retry semantics when payment fails |
| [`bankr-x402-sdk-job-management`](./bankr-x402-sdk-job-management/) | Jobs layer | Managing x402-funded async jobs; tracking micropayment cost per job; budget caps per cycle |
| [`bankr-x402-sdk-project-templates`](./bankr-x402-sdk-project-templates/) | Scaffolding | Starter templates for x402-integrated services; wallet funding requirements; env var conventions |
| [`bankr-x402-sdk-token-swaps`](./bankr-x402-sdk-token-swaps/) | Executor — x402-funded swaps | Executing swaps through the x402 payment layer; cost estimation; swap receipt parsing |
| [`bankr-x402-sdk-transaction-builder`](./bankr-x402-sdk-transaction-builder/) | `BankrExecutor` | Building x402-aware transactions; encoding payment proofs; transaction sequencing |
| [`bankr-x402-sdk-wallet-operations`](./bankr-x402-sdk-wallet-operations/) | Privy wallet layer | x402 wallet funding, draining, and balance management; minimum balance thresholds; automated top-up |

---

## Agent Role → Skill Matrix

The TradingAgents pipeline uses five primary agent roles. Use this matrix to determine which skill packages each role should load at initialization.

| Agent Role | Must load | May load (situational) |
|---|---|---|
| **Analyst** | `bankr-agent-market-research` · `bankr-agent-portfolio` · `bankr-x402-sdk-capabilities` | `bankr-agent-llm-gateway` · `bankr-x402-sdk-balance-queries` · `bankr-agent-polymarket` |
| **Quant** | `bankr-agent-market-research` | `bankr-agent-leverage-trading` · `bankr-agent-polymarket` |
| **Trader** | `bankr-agent-token-trading` · `bankr-agent-automation` · `bankr-agent-job-workflow` | `bankr-agent-leverage-trading` · `bankr-agent-polymarket` |
| **Risk** | `bankr-agent-safety-access-control` · `bankr-agent-error-handling` | `bankr-agent-arbitrary-transactions` · `bankr-agent-leverage-trading` |
| **Executor** | `bankr-agent-token-trading` · `bankr-agent-sign-submit-api` · `bankr-agent-transfers` · `bankr-agent-error-handling` | `bankr-agent-arbitrary-transactions` · `bankr-agent-token-deployment` · `bankr-agent-nft-operations` |

> **Rule:** An agent role must never load a skill from a domain outside its function scope.  
> The Risk agent must not load execution skills. The Analyst must not load signing or transfer skills.  
> Scope violation is treated as a misconfiguration and should be caught at startup by OpenClaw.

---

## Integration Patterns

### Pattern 1 — Standard BankrRail Order (most common)

```
Analyst reads market data     → bankr-agent-market-research
Quant sizes the position       → (internal HL-TF quant engine)
Trader emits TraderDecisionSignal with venue=BANKR_EVM
SAE evaluates against SAEBankrConfig → bankr-agent-safety-access-control
Executor constructs BankrSkillRequest → bankr-agent-token-trading + bankr-agent-sign-submit-api
BankrSkillClient submits order         → bankr-dev-api-workflow
BankrExecutor polls for fill           → bankr-agent-job-workflow
FillReport written to DecisionTrace    → bankr-agent-error-handling (on failure path)
```

### Pattern 2 — DCA Automation Job

```
Trader schedules recurring DCA    → bankr-agent-automation
Jobs layer persists job state     → bankr-dev-automation (Redis idempotency)
Each DCA slice flows Pattern 1 above
Circuit breaker monitors daily volume → bankr-agent-safety-access-control
```

### Pattern 3 — Analyst x402 Market Intelligence Query

```
Analyst needs cross-chain portfolio context   → bankr-x402-sdk-capabilities
x402 client injects payment header            → bankr-x402-sdk-client-patterns
Bankr/Zerion endpoint returns portfolio data  → bankr-x402-sdk-balance-queries
Analyst normalizes data into signal schema    → bankr-dev-market-research
```

### Pattern 4 — Event-Driven Polymarket Overlay

```
Analyst detects macro event signal             → bankr-agent-market-research
Analyst emits Polymarket position signal       → bankr-agent-polymarket
SAE evaluates notional + action type           → bankr-agent-safety-access-control
Executor opens Polymarket position via Bankr   → bankr-dev-polymarket
Position tracked in DecisionTrace bankr_fills  → bankr-agent-job-workflow
```

---

## Trust Model

All Bankr skills operate under the **low-trust external adapter** principle established in the BankrRail architecture. Regardless of which skill is loaded:

- Skills provide behavioral guidance and implementation patterns. They do not bypass SAE.
- Every Bankr API call originates from code that has already been approved by the SAE engine.
- Agent roles must not use LLM-generated Bankr API parameters directly in production without SAE evaluation.
- The `bankr-agent-safety-access-control` and `bankr-dev-safety-access-control` skills take precedence over all other skills in any conflict.

---

## Security Notes

- **API keys:** Bankr API keys are stored in the secrets manager. Never hardcode. The `bankr-dev-api-basics` skill documents the expected env var names.
- **Wallet IDs:** Privy server wallet IDs are stored alongside API keys. Only wallet IDs present in `SAEBankrConfig.walletIdAllowlist` may be used.
- **Least privilege:** Each Privy wallet should be scoped to the minimum required action types. A wallet authorized only for swaps must not be used for token deployment.
- **Key rotation:** See `bankr-dev-safety-access-control` for key rotation procedures and the expected behavior of in-flight orders during rotation.
- **x402 wallet funding:** The x402 USDC wallet used for micropayments is separate from trading wallets. It is funded from the treasury only up to a per-cycle budget cap defined in `SAEBankrConfig`.

---

## Related Documents

| Document | Location |
|---|---|
| BankrRail integration overview | [`multiclaw/bankr/README.md`](../../multiclaw/bankr/README.md) |
| Concrete interface sketch (proto, SAE, executor, router) | [`multiclaw/bankr/docs/bankr_openclaw_interface.md`](../../multiclaw/bankr/docs/bankr_openclaw_interface.md) |
| OpenClaw skill descriptor | [`config/openclaw-skills/bankr-rail.skill.json`](../../config/openclaw-skills/bankr-rail.skill.json) |
| Bankr platform | [bankr.bot](https://bankr.bot) |
| Privy agentic wallets | [docs.privy.io](https://docs.privy.io/recipes/agent-integrations/agentic-wallets) |
| Zerion x402 integration | [zerion.io/blog/build-best-ai-crypto-agent](https://zerion.io/blog/build-best-ai-crypto-agent/) |
| BankrBot × Privy case study | [privy.io/blog/bankrbot-case-study](https://privy.io/blog/bankrbot-case-study) |
