#!/usr/bin/env bash
set -euo pipefail
WS="${1:-.}"
python3 "$WS/skills/intelliclaw-feed-harvester/scripts/rss_harvester.py" \
  "$WS/operations/IntelliClaw/config/rss_sources.txt" \
  "$WS/operations/IntelliClaw/live/raw-claims.json"
