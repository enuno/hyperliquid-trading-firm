# apps/jobs/src/research_asset.py

from apps.agents.src.tools.intelliclaw_client import get_intel_snapshot

def research_asset(asset: str):
    intel = get_intel_snapshot(asset)
    # Save into Postgres/Milvus for further LLM analysis
