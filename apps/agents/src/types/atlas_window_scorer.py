# atlas_window_scorer.py

WINDOW_K = 5   # number of cycles / days per evaluation window

def compute_window_score(trades, portfolio_series):
    """
    trades: list of FilledTrade objects within window
    portfolio_series: equity curve over window

    Map risk-adjusted performance to [0,100].
    """
    roi = (portfolio_series[-1] / portfolio_series[0]) - 1.0
    max_dd = max_drawdown(portfolio_series)
    sharpe = rolling_sharpe(portfolio_series)

    # Basic ATLAS-style scoring: reward return, penalize drawdown
    raw = roi * 100 - max(0, max_dd - 0.05) * 100 - max(0, 0.5 - sharpe) * 50
    return max(0, min(100, raw + 50))  # clip + shift to [0,100]

def build_window_summary(trades, decisions, metrics) -> str:
    # Short textual summary: used as "summary" for Adaptive-OPRO
    return (
      f"Window ROI {metrics['roi']:.2%}, maxDD {metrics['max_dd']:.2%}, "
      f"Sharpe {metrics['sharpe']:.2f}. "
      f"{len(trades)} trades, mean slippage {metrics['slippage_bps']:.1f} bps."
    )
