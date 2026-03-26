# Pipeline Reference

## Stage 1 — feed-harvester
- **Input:** `operations/IntelliClaw/config/rss_sources.txt`
- **Output:** `live/raw-claims.json`
- **Method:** Python `urllib` + `xml.etree.ElementTree`
- **Volume:** ~30 items per source, ~210 total per cycle
- **Dedup:** SHA1 of `label|title|link`

## Stage 2 — multilingual-normalizer
- **Input:** `live/raw-claims.json`
- **Output:** `live/normalized-claims.json`
- **Method:** `jq` string substitution
- **Normalizes:** entity aliases, punctuation cleanup, zero-width chars, and locale-aware normalization
- **Lang tag:** preserve locale with normalized marker when transformed

## Stage 3 — claim-crosscheck
- **Input:** `live/normalized-claims.json`
- **Output:** `live/crosscheck-report.json`
- **Method:** Structural comparison (contradiction detection placeholder)

## Stage 4 — risk-scorer
- **Input:** `live/normalized-claims.json`
- **Output:** `live/scored-claims.json`
- **Scoring:** confidence ≥ 0.8 → high, ≥ 0.65 → medium, else low

## Stage 5 — telegraph-writer
- **Input:** `live/scored-claims.json`
- **Output:** `live/intelliclaw-telegraph-ledger.md` (append)
- **Format:** Markdown dispatch blocks with risk level, timestamp, source, text

## Stage 6 — minutes-scribe
- **Input:** `live/scored-claims.json`
- **Output:** `live/intelliclaw-running-minutes.md` (append)
- **Format:** Cycle summary with claim count and high-risk signal count
