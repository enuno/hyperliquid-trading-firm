#!/usr/bin/env bash
WS="${1:-.}"
SCORED="$WS/operations/IntelliClaw/live/scored-claims.json"
MINUTES="$WS/operations/IntelliClaw/live/intelliclaw-running-minutes.md"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
COUNT=$(jq length "$SCORED" 2>/dev/null || echo 0)
HIGH=$(jq '[.[] | select(.risk=="high")] | length' "$SCORED" 2>/dev/null || echo 0)
{ echo "### $TIMESTAMP"; echo "- Claims processed: $COUNT"; echo "- High-risk signals: $HIGH"; echo ""; } >> "$MINUTES"
echo "[minutes-scribe] Minutes updated"
