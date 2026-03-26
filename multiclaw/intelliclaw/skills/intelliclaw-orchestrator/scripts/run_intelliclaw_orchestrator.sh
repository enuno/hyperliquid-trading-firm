#!/usr/bin/env bash
set -e
WS="${1:-$(pwd)}"
echo "========================================"
echo " IntelliClaw Orchestrator — $(date -u)"
echo " Workspace: $WS"
echo "========================================"
run_skill() { echo ""; echo "--- [$1] ---"; bash "$WS/skills/$1/scripts/run.sh" "$WS"; }

run_skill intelliclaw-feed-harvester
echo ""
echo "--- [dedupe] ---"
bash "$WS/skills/intelliclaw-feed-harvester/scripts/dedupe.sh" "$WS"
run_skill intelliclaw-persian-normalizer
run_skill intelliclaw-claim-crosscheck
run_skill intelliclaw-risk-scorer
run_skill intelliclaw-telegraph-writer
run_skill intelliclaw-minutes-scribe
echo ""
echo "--- [onepager] ---"
bash "$WS/skills/intelliclaw-telegraph-writer/scripts/onepager.sh" "$WS"
echo ""
echo "========================================"
echo " Cycle complete: $(date -u)"
echo "========================================"
