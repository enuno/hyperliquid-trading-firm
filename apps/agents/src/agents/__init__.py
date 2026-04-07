"""
apps/agents/src/agents/__init__.py
===================================
Agent package exports.

Add new agent classes here as they are implemented.
Keep imports lazy (inside TYPE_CHECKING guards) where agents have heavy
dependencies that should not be loaded unless the agent is actually used.
"""

from .research_agent import ResearchAgent

__all__ = [
    "ResearchAgent",
]
