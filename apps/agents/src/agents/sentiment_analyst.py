# apps/agents/src/agents/sentiment_analyst.py

from ..tools.intelliclaw_client import get_intel_snapshot

class SentimentAnalystAgent:
    def generate_report(self, asset: str):
        intel = get_intel_snapshot(asset)

        # Use intel.overall_sentiment / headlines to build AnalystReport
        # This becomes your SentimentAnalystReport used by the rest of the pipeline.
