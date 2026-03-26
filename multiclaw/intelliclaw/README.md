# IntelliClaw

> 🌊 Real-time multi-topic signals pipeline — harvest, normalize, score, and dispatch open-source intelligence from configurable live feeds every 10 minutes.

Built on [OpenClaw](https://github.com/AIML-Solutions) · Operated by [AIML Solutions](https://www.aiml-solutions.com)

---

## What It Does

IntelliClaw is an autonomous OSINT pipeline for monitoring any topic or event domain (geopolitics, markets, infrastructure, incident response, and historical timelines). It normalizes multilingual content, cross-checks claims for contradictions, scores signals by risk level, and dispatches structured intelligence updates to a live ledger.
```
RSS Feeds (7 sources)
       │
       ▼
┌─────────────────┐
│  feed-harvester │  pulls & parses RSS → raw-claims.json
└────────┬────────┘
         │
         ▼
┌──────────────────────┐
│  persian-normalizer  │  entity normalization, FA detection
└────────┬─────────────┘
         │
         ▼
┌───────────────────┐
│  claim-crosscheck │  contradiction detection → crosscheck-report.json
└────────┬──────────┘
         │
         ▼
┌──────────────┐
│  risk-scorer │  confidence × keyword boost → scored-claims.json
└──────┬───────┘
       │
       ▼
┌───────────────────┐
│ telegraph-writer  │  dispatches → telegraph-ledger.md
└──────┬────────────┘
       │
       ▼
┌────────────────┐
│ minutes-scribe │  cycle summary → running-minutes.md
└────────────────┘
```

**Cycle time:** 10 minutes (cron) · **Claims per cycle:** ~210 · **Sources:** 7

---

## Sources

| Label | Class | Coverage |
|---|---|---|
| Reuters-World | international | Wire service |
| AP-World | international | Wire service |
| BBC-World | international | Global coverage |
| Al-Jazeera | international | Regional/global analysis |
| Financial-Times-Markets | markets | Markets and macro coverage |
| NetBlocks-Global | sensor | Infrastructure/internet signals |
| Event-Topic-Feed | configurable | User-selected topic stream |

---

## Quick Start

### Requirements

- Python 3.10+
- `jq`
- `bash`
- `curl`

### Install
```bash
git clone https://github.com/AIML-Solutions/intelliclaw.git
cd intelliclaw
```

### Run a single cycle
```bash
bash skills/intelliclaw-orchestrator/scripts/run_intelliclaw_orchestrator.sh .
```

### Run every 10 minutes (cron)
```bash
crontab -e
```

Add:
```
*/10 * * * * cd /path/to/intelliclaw && bash skills/intelliclaw-orchestrator/scripts/run_intelliclaw_orchestrator.sh . >> operations/IntelliClaw/live/cycle.log 2>&1
```

### Check dependencies
```bash
bash operations/IntelliClaw/scripts/check_dependencies.sh
```

---

## Configuration

Edit `operations/IntelliClaw/config/rss_sources.txt` to add or remove sources:
```
# label|class|url
Reuters-World|international|https://...
```

Supported classes: `international`, `state`, `opposition`, `sensor`, `ugc`

Each class maps to a base confidence score. See `docs/CONFIGURATION.md`.

---

## Output Files

| File | Description |
|---|---|
| `live/raw-claims.json` | Raw harvested claims |
| `live/normalized-claims.json` | Normalized and language-tagged claims |
| `live/crosscheck-report.json` | Contradiction analysis |
| `live/scored-claims.json` | Risk-scored claims |
| `live/intelliclaw-telegraph-ledger.md` | Live intelligence dispatches |
| `live/intelliclaw-running-minutes.md` | Cycle-by-cycle summary log |
| `live/cycle.log` | Cron execution log |

---

## Roadmap

- [x] RSS harvest pipeline (7 sources)
- [x] Multilingual normalization
- [x] Claim cross-check
- [x] Risk scoring
- [x] Telegraph ledger dispatch
- [x] 10-min autonomous cron cycle
- [ ] SignalCockpit integration (browser auth)
- [ ] Contradiction persistence across cycles
- [ ] Cross-cycle deduplication
- [ ] One-pager prose summary
- [ ] Optional translation toggle for multilingual streams
- [ ] Web dashboard
- [ ] Public API

---

## Project Structure
```
intelliclaw/
├── skills/
│   ├── intelliclaw-feed-harvester/
│   ├── intelliclaw-persian-normalizer/
│   ├── intelliclaw-claim-crosscheck/
│   ├── intelliclaw-risk-scorer/
│   ├── intelliclaw-telegraph-writer/
│   ├── intelliclaw-minutes-scribe/
│   └── intelliclaw-orchestrator/
├── operations/
│   └── IntelliClaw/
│       ├── config/
│       │   └── rss_sources.txt
│       ├── scripts/
│       │   └── check_dependencies.sh
│       └── live/          ← gitignored outputs
└── docs/
    ├── ARCHITECTURE.md
    ├── PIPELINE.md
    ├── SKILLS.md
    ├── CONFIGURATION.md
    └── CONTRIBUTING.md
```

---

## License

MIT © 2026 [AIML Solutions](https://www.aiml-solutions.com)
