# apps/agents/src/tools/intelliclaw_client.py

import requests
from . import config
from ..types.intel import IntelSnapshot

BASE_URL = config.INTELLICLAW_URL

def get_intel_snapshot(asset: str) -> IntelSnapshot:
    resp = requests.get(f"{BASE_URL}/intel/snapshot", params={"asset": asset}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    # Map JSON to IntelSnapshot dataclass
    return IntelSnapshot(**data)
