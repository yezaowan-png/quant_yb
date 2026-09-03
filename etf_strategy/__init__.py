"""ETF strategy research integration.

This package keeps ETF research signals separate from the stock backtesting and
execution pipeline.  Strategies emit signals and report artifacts only; they do
not place orders or modify formal trading state.
"""

from .runner import run_etf_strategy_report

__all__ = ["run_etf_strategy_report"]
