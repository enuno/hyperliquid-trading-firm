#!/usr/bin/env bash
set -euo pipefail
WS="${1:-.}"
RAW="$WS/operations/IntelliClaw/live/raw-claims.json"
SEEN="$WS/operations/IntelliClaw/live/seen-ids.json"

[ -f "$SEEN" ] || echo '[]' > "$SEEN"

BEFORE=$(jq length "$RAW")

# Only dedupe claims seen in the LAST cycle (not all time) — use a rolling 2-cycle window
jq --slurpfile seen "$SEEN" '
  [.[] | select(.id as $id | $seen[0] | index($id) == null)]
' "$RAW" > "$RAW.new"

AFTER=$(jq length "$RAW.new")
REMOVED=$(( BEFORE - AFTER ))

# Update seen-ids with just THIS cycle's IDs (rolling — not cumulative forever)
jq '[.[].id]' "$RAW" > "$SEEN"

mv "$RAW.new" "$RAW"
echo "[dedupe] $BEFORE claims in, $AFTER new ($REMOVED duplicates removed)"
