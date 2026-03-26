#!/usr/bin/env bash
WS="${1:-.}"
IN="$WS/operations/IntelliClaw/live/scored-claims.json"
LEDGER="$WS/operations/IntelliClaw/live/intelliclaw-telegraph-ledger.md"
[ ! -f "$IN" ] && echo "[telegraph-writer] No scored claims" && exit 1
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
{ echo ""; echo "## Dispatch — $TIMESTAMP"; echo "";
jq -r '.[] | "**[\(.risk | ascii_upcase)]** \(.ts) — \(.source)  \n> \(.text)  \n> confidence: \(.confidence)\n"' "$IN"
echo "---"; } >> "$LEDGER"
echo "[telegraph-writer] Appended dispatch to ledger"
