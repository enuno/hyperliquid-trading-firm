# apps/agents/src/strategies/base_strategy.py

class BaseStrategy:
    """
    OpenTrader-style strategy interface.
    The LLM agents / TraderAgent configure and drive instances of this.
    """

    # Metadata for UI / orchestrator
    name: str = "BaseStrategy"
    description: str = ""
    parameters_schema: dict = {}   # JSON-schema-like shape for UI/autogen

    def __init__(self, symbol: str, parameters: dict):
        self.symbol = symbol
        self.params = parameters

    def on_start(self, ctx) -> None:
        """Called when strategy is (re)started."""

    def on_stop(self, ctx) -> None:
        """Called when strategy is stopped."""

    def on_bar(self, bar, ctx) -> None:
        """
        Called on each new bar / tick batch.
        'bar' is OHLCV, 'ctx' gives access to portfolio, open orders, etc.
        """

    def generate_signals(self, ctx) -> list[dict]:
        """
        Return a list of desired actions, e.g.:
        [{ "action": "buy", "size": 0.1, "type": "market" }, ...]
        SAE/Execution layer will validate and transform to orders.
        """
        return []
