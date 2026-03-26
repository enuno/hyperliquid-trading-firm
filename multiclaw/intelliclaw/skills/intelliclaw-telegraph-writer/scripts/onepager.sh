#!/usr/bin/env bash
set -euo pipefail
WS="${1:-.}"
SCORED="$WS/operations/IntelliClaw/live/scored-claims.json"
ONEPAGER="$WS/operations/IntelliClaw/live/intelliclaw-onepager-ledger.md"
[ -f "$SCORED" ] || { echo "[onepager] No scored claims"; exit 1; }

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
HIGH=$(jq '[.[] | select(.risk=="high")] | length' "$SCORED")
TOTAL=$(jq length "$SCORED")

{
echo "# IntelliClaw — Multi-Topic Signals One-Pager"
echo "_Last updated: ${TIMESTAMP}_"
echo ""
echo "**Cycle summary:** ${TOTAL} signals processed · ${HIGH} high-risk"
echo ""
echo "## Top High-Risk Signals"
echo ""
jq -r '
  [.[] | select(.risk=="high")] | .[0:5] |
  .[] |
  "**\(.source)** — \(.text)\n> _confidence: \(.confidence) · \(.ts)_\n"
' "$SCORED"
echo ""
echo "## Source Breakdown"
echo ""
jq -r '
  group_by(.source) |
  map({source: .[0].source, count: length, high: (map(select(.risk=="high")) | length)}) |
  sort_by(-.high) |
  .[] |
  "- **\(.source):** \(.count) signals, \(.high) high-risk"
' "$SCORED"
} > "$ONEPAGER"

echo "[onepager] Written ${HIGH} high-risk signals to $ONEPAGER"
