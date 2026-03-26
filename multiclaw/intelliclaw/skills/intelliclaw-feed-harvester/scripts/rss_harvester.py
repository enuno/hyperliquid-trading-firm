#!/usr/bin/env python3
import hashlib, json, re, sys, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone

src = sys.argv[1] if len(sys.argv) > 1 else "operations/IntelliClaw/config/rss_sources.txt"
out = sys.argv[2] if len(sys.argv) > 2 else "operations/IntelliClaw/live/raw-claims.json"

def clean(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", " ", s).strip()

def detect_lang(text):
    return "fa" if re.search(r"[\u0600-\u06FF]", text or "") else "en"

def conf_for(cls):
    return {"international": 0.74, "state": 0.70, "opposition": 0.69, "sensor": 0.77, "ugc": 0.60}.get(cls, 0.66)

records = []
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

with open(src, "r", encoding="utf-8") as f:
    lines = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]

for ln in lines:
    try:
        label, cls, url = ln.split("|", 2)
    except ValueError:
        continue
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            data = r.read()
    except Exception as e:
        print(f"[feed-harvester] SKIP {label}: {e}", file=sys.stderr)
        continue
    try:
        root = ET.fromstring(data)
    except Exception as e:
        print(f"[feed-harvester] XML ERR {label}: {e}", file=sys.stderr)
        continue

    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    for it in items[:30]:
        title = clean(it.findtext("title") or it.findtext("{http://www.w3.org/2005/Atom}title") or "")
        desc  = clean(it.findtext("description") or it.findtext("summary") or it.findtext("{http://www.w3.org/2005/Atom}summary") or "")
        link  = it.findtext("link") or ""
        if not link:
            lnode = it.find("link") or it.find("{http://www.w3.org/2005/Atom}link")
            if lnode is not None:
                link = lnode.attrib.get("href", "")
        if not title:
            continue
        text = f"{title} — {desc}" if desc else title
        hid  = hashlib.sha1(f"{label}|{title}|{link}".encode("utf-8")).hexdigest()
        records.append({
            "id": hid, "ts": now, "source": label,
            "source_class": cls, "lang": detect_lang(text),
            "text": text, "link": link, "confidence": conf_for(cls)
        })

uniq = {r["id"]: r for r in records}
out_data = list(uniq.values())

with open(out, "w", encoding="utf-8") as f:
    json.dump(out_data, f, ensure_ascii=False, indent=2)

print(f"[feed-harvester] Wrote {len(out_data)} claims to {out}")
