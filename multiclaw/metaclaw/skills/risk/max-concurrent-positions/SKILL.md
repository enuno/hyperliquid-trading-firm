---
name: max-concurrent-positions
description: Use before opening any new position to determine whether adding it would violate concurrent position limits. Enforces per-strategy, per-direction, per-correlation-cluster, and total portfolio limits. Integrates kill-switch tier state and regime conditions to dynamically tighten caps. Always consult this skill after kelly-position-sizing-perps and before slippage-budget-enforcement.
category: agentic
---

# Max Concurrent Positions

## When This Skill Activates

Apply this skill:

- Immediately after `kelly-position-sizing-perps` produces a sized
  notional — before any order is submitted
- When evaluating whether a second leg or scale-in is permitted on an
  existing position
- At session open to audit the inherited position count and confirm
  caps are not already breached from a prior session
- After any kill-switch tier change — tier changes dynamically tighten
  all caps and may require immediate position reduction
- When a new strategy is added to the active strategy set — check
  whether combined capacity of all strategies fits within portfolio caps
- During regime transitions — trending → ranging or low → high cascade
  score changes the effective caps

---

## Cap Hierarchy

Concurrent position limits are enforced at **five nested levels**.
A new position must clear **all five** before entry is permitted.
The binding cap is the one that produces the smallest allowed count
at the moment of evaluation.

```
Level 1: Total portfolio positions          (global ceiling)
Level 2: Per-direction (long / short)       (directional concentration)
Level 3: Per-correlation-cluster            (correlated exposure grouping)
Level 4: Per-strategy                       (single strategy capacity)
Level 5: Per-asset                          (repeat position guard)
```

---

## Default Cap Table

Caps are defined in `kill_switch_config.yaml` and dynamically
overridden by kill-switch tier and regime state.

| Cap Level | Normal | Tier 1 Post | Tier 2 Post | Tier 3 Recovery | Tier 4 |
|---|---|---|---|---|---|
| Total portfolio | 6 | 4 | 3 | 1 | 0 |
| Per-direction (long or short) | 4 | 3 | 2 | 1 | 0 |
| Per-correlation-cluster | 2 | 2 | 1 | 1 | 0 |
| Per-strategy | 3 | 2 | 2 | 1 | 0 |
| Per-asset | 1 | 1 | 1 | 1 | 0 |

> **Tier 4 is always 0** — no positions of any kind while an emergency
> shutdown is active. This cap is enforced independently by
> `drawdown-kill-switch-trigger`; this skill cross-checks it.

---

## Correlation Clusters

Assets are grouped into correlation clusters based on empirically
observed co-movement. A position in any asset within a cluster counts
toward that cluster's cap. Clusters are not fixed — they are
re-evaluated when the rolling 30-day correlation matrix changes
significantly (threshold: correlation drift > 0.15 for a pair).

### Default Cluster Definitions

```python
CORRELATION_CLUSTERS = {
    "btc_majors": {
        "assets": ["BTC", "ETH", "SOL", "BNB"],
        "min_correlation": 0.70,   # observed 30d rolling
        "description": "Large-cap proof-of-work and L1 majors",
    },
    "eth_ecosystem": {
        "assets": ["ETH", "OP", "ARB", "MATIC", "BASE"],
        "min_correlation": 0.75,
        "description": "Ethereum and L2 ecosystem tokens",
    },
    "defi_bluechip": {
        "assets": ["AAVE", "UNI", "CRV", "SNX", "MKR"],
        "min_correlation": 0.65,
        "description": "DeFi protocol governance tokens",
    },
    "high_beta_alt": {
        "assets": ["DOGE", "SHIB", "PEPE", "WIF", "BONK"],
        "min_correlation": 0.60,
        "description": "High-beta meme and retail-driven tokens",
    },
    "perp_funding_plays": {
        "assets": [],   # populated dynamically from funding rate screening
        "min_correlation": 0.50,
        "description": "Assets currently in elevated funding regime",
    },
}

# Note: an asset may appear in multiple clusters (e.g. ETH in both
# btc_majors and eth_ecosystem). A new ETH position counts against
# BOTH cluster caps simultaneously.
def get_clusters_for_asset(asset: str) -> list[str]:
    return [
        name for name, cluster in CORRELATION_CLUSTERS.items()
        if asset in cluster["assets"]
    ]
```

---

## Core Position Registry

```python
from dataclasses import dataclass, field
from typing import Optional
import time

@dataclass
class OpenPosition:
    position_id: str          # unique identifier (uuid)
    asset: str                # e.g. "ETH"
    direction: str            # "long" or "short"
    strategy_id: str          # which strategy opened this position
    notional_usd: float       # current notional size
    margin_usd: float         # current margin consumed
    entry_timestamp_utc: float
    unrealised_pnl_usd: float = 0.0
    leverage: float = 1.0
    clusters: list[str] = field(default_factory=list)  # populated on creation

@dataclass
class PositionRegistry:
    positions: dict[str, OpenPosition] = field(default_factory=dict)
    # key: position_id

    def count_total(self) -> int:
        return len(self.positions)

    def count_by_direction(self, direction: str) -> int:
        return sum(1 for p in self.positions.values() if p.direction == direction)

    def count_by_cluster(self, cluster: str) -> int:
        return sum(1 for p in self.positions.values() if cluster in p.clusters)

    def count_by_strategy(self, strategy_id: str) -> int:
        return sum(1 for p in self.positions.values() if p.strategy_id == strategy_id)

    def count_by_asset(self, asset: str) -> int:
        return sum(1 for p in self.positions.values() if p.asset == asset)

    def total_margin_usd(self) -> float:
        return sum(p.margin_usd for p in self.positions.values())

    def total_notional_usd(self) -> float:
        return sum(p.notional_usd for p in self.positions.values())

    def net_direction_notional(self) -> float:
        """Positive = net long, negative = net short."""
        longs  = sum(p.notional_usd for p in self.positions.values() if p.direction == "long")
        shorts = sum(p.notional_usd for p in self.positions.values() if p.direction == "short")
        return longs - shorts
```

---

## Effective Cap Resolver

```python
from enum import Enum

class KillSwitchTier(Enum):
    NONE   = 0
    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3
    TIER_4 = 4

# Base caps — override via kill_switch_config.yaml
BASE_CAPS = {
    "total":       6,
    "directional": 4,
    "cluster":     2,
    "strategy":    3,
    "asset":       1,
}

# Tier overrides — each tier tightens caps relative to base
TIER_CAP_OVERRIDES = {
    KillSwitchTier.NONE:   {"total": 6,  "directional": 4, "cluster": 2, "strategy": 3, "asset": 1},
    KillSwitchTier.TIER_1: {"total": 4,  "directional": 3, "cluster": 2, "strategy": 2, "asset": 1},
    KillSwitchTier.TIER_2: {"total": 3,  "directional": 2, "cluster": 1, "strategy": 2, "asset": 1},
    KillSwitchTier.TIER_3: {"total": 1,  "directional": 1, "cluster": 1, "strategy": 1, "asset": 1},
    KillSwitchTier.TIER_4: {"total": 0,  "directional": 0, "cluster": 0, "strategy": 0, "asset": 0},
}

def resolve_effective_caps(
    kill_switch_tier: KillSwitchTier,
    cascade_score: int,          # 0-10 from liquidation-cascade-risk
    funding_regime: str,         # "NORMAL" | "ELEVATED" | "EXTREME"
    is_post_tier3_recovery: bool = False,
) -> dict:
    """
    Resolve effective position caps after applying all dynamic modifiers.
    Returns a dict with keys: total, directional, cluster, strategy, asset.
    The most restrictive (minimum) value at each level wins.
    """
    caps = dict(TIER_CAP_OVERRIDES[kill_switch_tier])

    # Cascade regime tightening
    if cascade_score >= 8:
        # CRITICAL: treat like Tier 3 regardless of kill-switch tier
        caps = {k: min(caps[k], TIER_CAP_OVERRIDES[KillSwitchTier.TIER_3][k])
                for k in caps}
    elif cascade_score >= 5:
        # HIGH: reduce total and cluster by 1
        caps["total"]   = max(0, caps["total"]   - 1)
        caps["cluster"] = max(0, caps["cluster"] - 1)

    # Funding regime tightening
    if funding_regime == "EXTREME":
        caps["total"]       = max(0, caps["total"]       - 1)
        caps["directional"] = max(0, caps["directional"] - 1)
    elif funding_regime == "ELEVATED":
        caps["total"]       = max(0, caps["total"]       - 1)

    # Post-Tier-3 recovery protocol (first 5 sessions)
    if is_post_tier3_recovery:
        caps = {k: min(caps[k], TIER_CAP_OVERRIDES[KillSwitchTier.TIER_3][k])
                for k in caps}

    return caps
```

---

## Admission Check

```python
@dataclass
class AdmissionResult:
    admitted: bool
    binding_cap_level: str      # "total" | "directional" | "cluster" | "strategy" | "asset" | "none"
    binding_cap_value: int
    current_count_at_binding: int
    reason: str
    effective_caps: dict
    registry_snapshot: dict     # counts at time of check

def check_admission(
    registry: PositionRegistry,
    candidate_asset: str,
    candidate_direction: str,
    candidate_strategy_id: str,
    kill_switch_tier: KillSwitchTier,
    cascade_score: int,
    funding_regime: str,
    is_post_tier3_recovery: bool = False,
) -> AdmissionResult:
    """
    Check whether a new position may be opened.
    Returns AdmissionResult with admitted=True or False and full reasoning.
    """
    caps = resolve_effective_caps(
        kill_switch_tier, cascade_score, funding_regime, is_post_tier3_recovery
    )

    candidate_clusters = get_clusters_for_asset(candidate_asset)

    snapshot = {
        "total":       registry.count_total(),
        "directional": registry.count_by_direction(candidate_direction),
        "strategy":    registry.count_by_strategy(candidate_strategy_id),
        "asset":       registry.count_by_asset(candidate_asset),
        "clusters":    {c: registry.count_by_cluster(c) for c in candidate_clusters},
    }

    # Check each cap level in priority order (most restrictive first)

    # Level 5: per-asset (repeat position guard)
    if snapshot["asset"] >= caps["asset"]:
        return AdmissionResult(
            admitted=False,
            binding_cap_level="asset",
            binding_cap_value=caps["asset"],
            current_count_at_binding=snapshot["asset"],
            reason=f"Asset cap reached: {snapshot['asset']}/{caps['asset']} "
                   f"positions already open on {candidate_asset}. "
                   f"Close existing {candidate_asset} position before opening a new one.",
            effective_caps=caps,
            registry_snapshot=snapshot,
        )

    # Level 1: total portfolio
    if snapshot["total"] >= caps["total"]:
        return AdmissionResult(
            admitted=False,
            binding_cap_level="total",
            binding_cap_value=caps["total"],
            current_count_at_binding=snapshot["total"],
            reason=f"Total portfolio cap reached: {snapshot['total']}/{caps['total']} "
                   f"positions open. Close at least one position before adding "
                   f"{candidate_asset} {candidate_direction}.",
            effective_caps=caps,
            registry_snapshot=snapshot,
        )

    # Level 2: per-direction
    if snapshot["directional"] >= caps["directional"]:
        return AdmissionResult(
            admitted=False,
            binding_cap_level="directional",
            binding_cap_value=caps["directional"],
            current_count_at_binding=snapshot["directional"],
            reason=f"Directional cap reached: {snapshot['directional']}/{caps['directional']} "
                   f"{candidate_direction} positions open. "
                   f"Adding another {candidate_direction} increases directional concentration "
                   f"beyond the current regime limit.",
            effective_caps=caps,
            registry_snapshot=snapshot,
        )

    # Level 3: per-correlation-cluster
    for cluster in candidate_clusters:
        cluster_count = snapshot["clusters"].get(cluster, 0)
        if cluster_count >= caps["cluster"]:
            return AdmissionResult(
                admitted=False,
                binding_cap_level="cluster",
                binding_cap_value=caps["cluster"],
                current_count_at_binding=cluster_count,
                reason=f"Correlation cluster cap reached for '{cluster}': "
                       f"{cluster_count}/{caps['cluster']} positions in this cluster. "
                       f"{candidate_asset} belongs to cluster '{cluster}'. "
                       f"Reduce correlated exposure before adding this position.",
                effective_caps=caps,
                registry_snapshot=snapshot,
            )

    # Level 4: per-strategy
    if snapshot["strategy"] >= caps["strategy"]:
        return AdmissionResult(
            admitted=False,
            binding_cap_level="strategy",
            binding_cap_value=caps["strategy"],
            current_count_at_binding=snapshot["strategy"],
            reason=f"Strategy cap reached: {snapshot['strategy']}/{caps['strategy']} "
                   f"positions open for strategy '{candidate_strategy_id}'. "
                   f"This strategy has reached its concurrent position limit.",
            effective_caps=caps,
            registry_snapshot=snapshot,
        )

    # All caps cleared
    return AdmissionResult(
        admitted=True,
        binding_cap_level="none",
        binding_cap_value=0,
        current_count_at_binding=0,
        reason="All concurrent position caps cleared.",
        effective_caps=caps,
        registry_snapshot=snapshot,
    )
```

---

## Registry Maintenance

```python
def register_position(
    registry: PositionRegistry,
    position: OpenPosition,
) -> PositionRegistry:
    """
    Add a newly opened position to the registry.
    Called immediately after confirmed exchange fill.
    Populates correlation clusters for the position.
    """
    position.clusters = get_clusters_for_asset(position.asset)
    registry.positions[position.position_id] = position
    return registry

def deregister_position(
    registry: PositionRegistry,
    position_id: str,
) -> PositionRegistry:
    """
    Remove a closed position from the registry.
    Called immediately after confirmed exchange close.
    """
    registry.positions.pop(position_id, None)
    return registry

def reconcile_registry(
    registry: PositionRegistry,
    exchange_positions: list[dict],  # from HyperLiquid /info clearinghouseState
) -> tuple[PositionRegistry, list[str]]:
    """
    Reconcile local registry against live exchange position state.
    Called at session open and after any API reconnect.
    Returns updated registry and list of discrepancy warnings.

    Discrepancy types:
    - Position in registry but not on exchange (phantom position)
    - Position on exchange but not in registry (shadow position)
    - Notional mismatch > 1% (partial fill or manual intervention)
    """
    warnings = []
    exchange_ids = {p["positionId"] for p in exchange_positions}
    registry_ids = set(registry.positions.keys())

    # Phantom positions
    for pid in registry_ids - exchange_ids:
        warnings.append(f"PHANTOM_POSITION: {pid} in registry but not on exchange. Removing.")
        registry.positions.pop(pid, None)

    # Shadow positions
    for ep in exchange_positions:
        pid = ep["positionId"]
        if pid not in registry_ids:
            warnings.append(
                f"SHADOW_POSITION: {pid} ({ep.get('asset')} {ep.get('direction')}) "
                f"on exchange but not in registry. Adding."
            )
            registry.positions[pid] = OpenPosition(
                position_id=pid,
                asset=ep["asset"],
                direction=ep["direction"],
                strategy_id="UNKNOWN_RECONCILED",
                notional_usd=ep["notionalUsd"],
                margin_usd=ep["marginUsd"],
                entry_timestamp_utc=ep.get("entryTimestamp", time.time()),
                leverage=ep.get("leverage", 1.0),
                clusters=get_clusters_for_asset(ep["asset"]),
            )

    # Notional mismatch
    for ep in exchange_positions:
        pid = ep["positionId"]
        if pid in registry.positions:
            local_n  = registry.positions[pid].notional_usd
            remote_n = ep["notionalUsd"]
            if abs(local_n - remote_n) / max(remote_n, 1) > 0.01:
                warnings.append(
                    f"NOTIONAL_MISMATCH: {pid} local={local_n:.2f} "
                    f"exchange={remote_n:.2f}. Updating to exchange value."
                )
                registry.positions[pid].notional_usd = remote_n

    return registry, warnings
```

---

## Regime-Driven Cap Tightening Logic

Beyond kill-switch tier, the following real-time signals automatically
tighten caps within a session. The `resolve_effective_caps()` function
handles these; this table documents the design intent:

| Signal | Source Skill | Cap Tightening | Rationale |
|---|---|---|---|
| Cascade score ≥ 5 (HIGH) | `liquidation-cascade-risk` | total −1, cluster −1 | Book fragility elevates correlated liquidation risk |
| Cascade score ≥ 8 (CRITICAL) | `liquidation-cascade-risk` | All caps → Tier 3 limits | Imminent cascade; portfolio must be minimal |
| Funding regime ELEVATED | `high-funding-carry-avoidance` | total −1 | Carry cost silently reduces edge on all open positions |
| Funding regime EXTREME | `high-funding-carry-avoidance` | total −1, directional −1 | Extreme funding: long positions bleed carry rapidly |
| Kill-switch Tier 1 | `drawdown-kill-switch-trigger` | Per Tier 1 override table | Session soft stop in effect |
| Kill-switch Tier 3 recovery | `drawdown-kill-switch-trigger` | total=1 for first 5 sessions | Recovery protocol; avoid re-triggering Tier 3 |

---

## Net Directional Exposure Check

Beyond position count, net directional notional must stay within
bounds to prevent de facto one-sided book construction across
multiple positions:

```python
MAX_NET_DIRECTIONAL_PCT_NAV = 1.50   # 150% of NAV net long or net short

def check_net_directional_exposure(
    registry: PositionRegistry,
    candidate_direction: str,
    candidate_notional_usd: float,
    portfolio_nav_usd: float,
) -> dict:
    """
    Check whether adding the candidate notional would breach the net
    directional exposure cap. Separate from position count checks.
    """
    current_net = registry.net_direction_notional()
    candidate_signed = candidate_notional_usd if candidate_direction == "long" else -candidate_notional_usd
    projected_net = current_net + candidate_signed
    projected_net_pct_nav = abs(projected_net) / portfolio_nav_usd

    permitted = projected_net_pct_nav <= MAX_NET_DIRECTIONAL_PCT_NAV
    return {
        "permitted": permitted,
        "current_net_usd": current_net,
        "projected_net_usd": projected_net,
        "projected_net_pct_nav": projected_net_pct_nav * 100,
        "cap_pct_nav": MAX_NET_DIRECTIONAL_PCT_NAV * 100,
        "reason": (
            "Net directional exposure within cap."
            if permitted else
            f"Net directional cap breached: projected {projected_net_pct_nav*100:.1f}% "
            f"of NAV net {'long' if projected_net > 0 else 'short'} vs cap of "
            f"{MAX_NET_DIRECTIONAL_PCT_NAV*100:.0f}%. Reduce existing "
            f"{'long' if projected_net > 0 else 'short'} exposure or take the "
            f"opposite direction to reduce net."
        ),
    }
```

---

## Worked Example — Full Admission Pipeline

```
Inputs:
  Portfolio NAV:               $200,000
  Kill-switch tier:            NONE
  Cascade score:               5  (HIGH — tightens total -1, cluster -1)
  Funding regime:              ELEVATED (tightens total -1)
  Post-Tier-3 recovery:        False

Effective caps after regime modifiers:
  Base NONE caps:  total=6, directional=4, cluster=2, strategy=3, asset=1
  Cascade HIGH:    total=5, cluster=1
  Funding ELEVATED: total=4
  Final caps:      total=4, directional=4, cluster=1, strategy=3, asset=1

Current open positions:
  1. BTC-long  (btc_majors cluster, strategy: trending-bull)
  2. ETH-long  (btc_majors + eth_ecosystem clusters, strategy: trending-bull)
  3. OP-long   (eth_ecosystem cluster, strategy: funding-carry)

Candidate: SOL-long, strategy: trending-bull

Step 1 — Asset check:
  SOL count in registry: 0  <  asset cap 1  ✔

Step 2 — Total check:
  Total open: 3  <  effective total cap 4  ✔

Step 3 — Directional check:
  Long count: 3  <  directional cap 4  ✔

Step 4 — Cluster check:
  SOL clusters: [btc_majors]
  btc_majors count: 2 (BTC + ETH)  >=  cluster cap 1  ✗

Result: REJECTED
  binding_cap_level:  "cluster"
  reason: "Correlation cluster cap reached for 'btc_majors': 2/1
           positions in this cluster. SOL belongs to cluster
           'btc_majors'. Reduce correlated exposure before adding
           this position."

Implication: Agent should not add SOL while both BTC and ETH are
open. Options: close BTC or ETH first (freeing the btc_majors
cluster slot), or wait for a different asset in a different cluster.
```

---

## Configuration

```yaml
# multiclaw/metaclaw/concurrent_positions_config.yaml

concurrent_positions:
  base_caps:
    total:       6
    directional: 4
    cluster:     2
    strategy:    3
    asset:       1

  net_directional_cap_pct_nav: 150   # 150% of NAV net long or short

  correlation_clusters:
    btc_majors:
      assets: [BTC, ETH, SOL, BNB]
      min_correlation: 0.70
    eth_ecosystem:
      assets: [ETH, OP, ARB, MATIC]
      min_correlation: 0.75
    defi_bluechip:
      assets: [AAVE, UNI, CRV, SNX, MKR]
      min_correlation: 0.65
    high_beta_alt:
      assets: [DOGE, SHIB, PEPE, WIF, BONK]
      min_correlation: 0.60

  reconciliation:
    run_at_session_open: true
    run_on_reconnect: true
    shadow_position_action: add_with_warning   # "add_with_warning" | "halt_until_reviewed"
    phantom_position_action: remove_with_warning

  audit_log_path: logs/audit/position_registry.jsonl
  state_store_path: logs/state/position_registry.json
```

---

## Audit JSONL Schema

```json
{
  "event": "position_admission_rejected",
  "timestamp_utc": "2026-04-07T22:00:00Z",
  "candidate_asset": "SOL",
  "candidate_direction": "long",
  "candidate_strategy_id": "trending-bull",
  "candidate_notional_usd": 2353,
  "admitted": false,
  "binding_cap_level": "cluster",
  "binding_cap_value": 1,
  "current_count_at_binding": 2,
  "reason": "Correlation cluster cap reached for 'btc_majors': 2/1 positions.",
  "effective_caps": {"total": 4, "directional": 4, "cluster": 1, "strategy": 3, "asset": 1},
  "kill_switch_tier": 0,
  "cascade_score": 5,
  "funding_regime": "ELEVATED",
  "registry_snapshot": {
    "total": 3,
    "directional": 3,
    "strategy": 2,
    "asset": 0,
    "clusters": {"btc_majors": 2}
  }
}
```

---

## Integration with Other Skills

- **`kelly-position-sizing-perps`** (risk/): Kelly produces
  `final_notional_usd`. This skill checks whether that position is
  even admissible before the notional is sent to execution. Kelly
  sizing and admission check are always run in sequence: Kelly first,
  admission second.
- **`drawdown-kill-switch-trigger`** (risk/): Tier state feeds
  directly into `resolve_effective_caps()`. On Tier 3 recovery, the
  maximum concurrent position count is 1 for the first 5 sessions —
  this skill enforces that constraint. On Tier 4, this skill cross-
  checks and returns `admitted=False` for all candidates.
- **`liquidation-cascade-risk`** (regime-detection/): Cascade score
  of 5+ reduces total and cluster caps within the session. Score of
  8+ maps all caps to Tier 3 limits regardless of kill-switch state.
- **`high-funding-carry-avoidance`** (regime-detection/): Funding
  regime ELEVATED or EXTREME reduces total and directional caps. The
  carry skill's `funding_regime` field is a required input to
  `resolve_effective_caps()`.
- **`slippage-budget-enforcement`** (execution/): Only called after
  this skill returns `admitted=True`. The execution pipeline order is:
  Kelly → Admission → Slippage → Order Submission.

---

## Quick Decision Tree

```
New position candidate arrives — run in order:
│
├── 1. Check kill-switch state (drawdown-kill-switch-trigger)
│     state.trading_permitted()? → No → HALT. Do not proceed.
│
├── 2. Resolve effective caps
│     resolve_effective_caps(tier, cascade_score, funding_regime, recovery)
│
├── 3. Run admission check
│     result = check_admission(registry, asset, direction, strategy,
│                              tier, cascade_score, funding_regime)
│     result.admitted == False? → Log rejection. Do not proceed.
│     Inform strategy: reason + binding_cap_level
│
├── 4. Check net directional exposure
│     check_net_directional_exposure(registry, direction, notional, nav)
│     permitted == False? → Log rejection. Do not proceed.
│
├── 5. Proceed to slippage-budget-enforcement
│     Pass final_notional_usd as initial_size_usd
│
├── 6. On confirmed fill:
│     register_position(registry, new_position)
│     persist_state(registry)
│     Log position_admission_accepted audit event
│
└── 7. On confirmed close:
      deregister_position(registry, position_id)
      persist_state(registry)
      Log position_closed audit event
```
