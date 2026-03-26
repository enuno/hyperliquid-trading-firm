# Architecture

IntelliClaw is a modular skill-based pipeline running on the OpenClaw agentic framework.

## Design Principles

- **Stateless skills** — each skill reads inputs and writes outputs independently
- **File-based state** — all inter-skill communication is via JSON files in `live/`
- **Single orchestrator** — one script drives the entire pipeline in sequence
- **Cron-driven** — no persistent daemon; runs on schedule and exits cleanly

## Runtime

- Python 3.10+ (harvester, normalizer)
- bash (orchestrator, all other skills)
- jq (JSON processing)
- curl (HTTP fetching)

## Data Flow
```
rss_sources.txt → harvester → raw-claims.json
                              → normalizer → normalized-claims.json
                                             → crosscheck → crosscheck-report.json
                                             → risk-scorer → scored-claims.json
                                                             → telegraph-writer → ledger.md
                                                             → minutes-scribe → minutes.md
```

## Scaling

Each skill can be run independently or replaced. To add a new source type, add a row to `rss_sources.txt`. To add a new output format, add a new skill and register it in the orchestrator.
