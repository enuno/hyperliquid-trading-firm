# Configuration

## RSS Sources

`operations/IntelliClaw/config/rss_sources.txt`

Format: `label|class|url`

Lines beginning with `#` are comments.

### Source Classes and Base Confidence

| Class | Confidence | Use for |
|---|---|---|
| international | 0.74 | Major wire services, international outlets |
| state | 0.70 | State-controlled media |
| opposition | 0.69 | Opposition or exile media |
| sensor | 0.77 | Infrastructure monitors (NetBlocks etc.) |
| ugc | 0.60 | User-generated, social media |

### Adding a Source
```
My-Source|international|https://example.com/rss
```

## Cron Schedule

Default: `*/10 * * * *` (every 10 minutes)

Modify in crontab: `crontab -e`
