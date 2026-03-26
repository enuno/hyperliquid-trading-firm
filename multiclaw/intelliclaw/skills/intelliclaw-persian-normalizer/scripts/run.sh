#!/usr/bin/env bash
set -euo pipefail
WS="${1:-.}"
IN="$WS/operations/IntelliClaw/live/raw-claims.json"
OUT="$WS/operations/IntelliClaw/live/normalized-claims.json"
[ -f "$IN" ] || { echo "[normalizer] No input at $IN"; exit 1; }
jq '
map(
  .text |= (
    gsub("&nbsp;";" ") | gsub("&amp;";"&") | gsub("&lt;";"<") | gsub("&gt;";">")
    | gsub("Teheran";"Tehran") | gsub("Esfahan";"Isfahan")
    | gsub("Mashad";"Mashhad") | gsub("Tabrizh";"Tabriz")
    | gsub("\u200c";"") | gsub("  ";" ")
  )
  | if .lang == "fa" then .lang = "fa-normalized" else . end
)
' "$IN" > "$OUT"
echo "[persian-normalizer] Normalized $(jq length "$OUT") claims -> $OUT"
