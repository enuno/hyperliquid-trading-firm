# Contributing

## Adding a Skill

1. Create `skills/intelliclaw-<name>/scripts/run.sh`
2. Accept workspace path as `$1`
3. Read from `operations/IntelliClaw/live/`
4. Write output to `operations/IntelliClaw/live/`
5. Register in `skills/intelliclaw-orchestrator/scripts/run_intelliclaw_orchestrator.sh`

## Adding a Source

Edit `operations/IntelliClaw/config/rss_sources.txt` — no code changes needed.

## Improving the Risk Scorer

Edit `skills/intelliclaw-risk-scorer/scripts/run.sh`. The scoring logic is plain `jq` — easy to extend with keyword matching.

## Code Style

- bash scripts: `set -euo pipefail`, explicit variable quoting
- Python: stdlib only where possible, no external dependencies for core pipeline
- All scripts must accept workspace path as first argument
