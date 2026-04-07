"""
apps/research/recall_strategy_translator.py

Converts Recall Network agent performance records into internal StrategyHypothesis
records suitable for backtesting via ablation_runner.py.

Maps Recall's `AgentTradingStyle` enum and performance metrics into the
StrategyHypothesis schema, with parameter grids and regime assumptions
derived from observed agent behavior.

Input: RecallAgentRecord (from recall_client.py)
Output: StrategyHypothesis (for ablation_runner.py)

Architecture constraints:
  - Deterministic — same agent record always produces same hypothesis
  - No network calls, no LLM calls — pure rule-based translation
  - Conservative parameter grids — narrow ranges to avoid overfitting
  - Regime assumptions based on observed Sharpe/drawdown profile
  - All outputs are typed dataclasses with full provenance
"""

from __future__ import annotations

import logging
from dataclasses
