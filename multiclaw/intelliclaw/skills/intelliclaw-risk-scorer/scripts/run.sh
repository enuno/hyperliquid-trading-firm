#!/usr/bin/env bash
set -euo pipefail
WS="${1:-.}"
IN="$WS/operations/IntelliClaw/live/normalized-claims.json"
OUT="$WS/operations/IntelliClaw/live/scored-claims.json"
[ -f "$IN" ] || { echo "[risk-scorer] No input" && exit 1; }
jq '
def high_keywords: [
  "blackout","internet shutdown","protest","arrested","killed","missile",
  "sanctions","nuclear","executed","explosion","attack","coup","revolt",
  "uprising","crackdown","detained","jailed","airstrike","warship","blockade"
];
map(
  . + {
    risk: (
      if .confidence >= 0.8 then "high"
      elif .confidence >= 0.65 then "medium"
      else "low" end
    )
  }
  | if (.risk != "high") then
      . + {
        risk: (
          if ((.text | ascii_downcase) as $t |
            high_keywords | any(. as $kw | $t | contains($kw)))
          then "high" else .risk end
        )
      }
    else . end
)
' "$IN" > "$OUT"
echo "[risk-scorer] Scored $(jq length "$OUT") claims"
