# Skills Reference

Each skill is a self-contained directory with a `scripts/run.sh` entry point.

## intelliclaw-feed-harvester
Fetches and parses RSS feeds from configured sources. Uses Python for robust XML parsing. Outputs deduplicated claim JSON array.

## intelliclaw-persian-normalizer
Normalizes entity names and performs multilingual cleanup/tagging. Local-only — no external translation API dependency.

## intelliclaw-claim-crosscheck
Compares claims across sources for potential contradictions. Outputs a structured report. Contradiction detection logic is extensible.

## intelliclaw-risk-scorer
Assigns a risk tier (low/medium/high) to each claim based on source class confidence. Designed for keyword-boost extension.

## intelliclaw-telegraph-writer
Formats scored claims as intelligence dispatches and appends them to the telegraph ledger in Markdown.

## intelliclaw-minutes-scribe
Appends a brief cycle summary (claim count, high-risk count) to the running minutes log.

## intelliclaw-orchestrator
Single entry point. Runs all six skills in sequence. Accepts workspace path as argument.
```bash
bash skills/intelliclaw-orchestrator/scripts/run_intelliclaw_orchestrator.sh /path/to/workspace
```
