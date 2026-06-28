"""
Event-driven-ish vectorized backtester for monthly-rebalanced weight portfolios.

Inputs:
  - prices:  wide DataFrame of daily adjusted closes (index=date, cols=symbols)
  - weights: wide DataFrame of TARGET weights, indexed by rebalance dates
             (a subset of the price dates), cols=symbols. Weights may sum to
             <= 1.0; the remainder is held in cash (0% return).

The engine forward-fills the target weights between rebalances, computes daily
portfolio returns, and deducts transaction costs proportional to turnover at
each rebalance. This is the realistic-cost discipline that separates surviving
strategies from the ones that die after fees (see PLAN.md).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import CostModel


@dataclass
class BacktestResult:
    returns: pd.Series          # daily net portfolio returns
    gross_returns: pd.Series    # daily returns before costs
    equity: pd.Series           # equity curve (starts at 1.0)
    weights: pd.DataFrame       # daily (ffilled) weights actually held
    turnover: pd.Series         # per-day turnover (sum of |weight changes|)
    total_costs: float          # total cost drag (fraction of capital)


def _cost_rate(costs: CostModel) -> float:
    """One-way cost as a fraction of traded notional (slippage + half-spread)."""
    return (costs.slippage_bps + costs.spread_bps) / 10_000.0


def run_backtest(
    prices: pd.DataFrame,
    target_weights: pd.DataFrame,
    costs: CostModel,
) -> BacktestResult:
    """Run the weighted-portfolio backtest and return a BacktestResult."""
    prices = prices.sort_index()
    daily_returns = prices.pct_change().fillna(0.0)

    # Align target weights onto the full daily calendar, forward-filling between
    # rebalances. Columns restricted to those present in prices.
    cols = [c for c in target_weights.columns if c in prices.columns]
    tw = target_weights[cols].reindex(prices.index).ffill().fillna(0.0)

    cost_rate = _cost_rate(costs)

    gross = []
    net = []
    turnover_series = []
    held_weights = []

    prev_w = pd.Series(0.0, index=cols)

    for date in prices.index:
        target = tw.loc[date]

        # Turnover = sum of absolute weight changes vs. what we held yesterday.
        turn = float((target - prev_w).abs().sum())
        cost = turn * cost_rate

        # Day's gross return from the weights held INTO this day (target set at
        # prior close / this open). Using same-day weights * same-day returns is
        # a standard simplification for daily monthly-rebalanced ETF backtests.
        day_ret = float((target * daily_returns.loc[date]).sum())

        gross.append(day_ret)
        net.append(day_ret - cost)
        turnover_series.append(turn)
        held_weights.append(target)

        # Drift weights with the day's returns for next-day turnover accuracy.
        grown = target * (1.0 + daily_returns.loc[date])
        total = grown.sum()
        prev_w = grown / total if total != 0 else target

    idx = prices.index
    gross_s = pd.Series(gross, index=idx, name="gross")
    net_s = pd.Series(net, index=idx, name="net")
    turn_s = pd.Series(turnover_series, index=idx, name="turnover")
    equity = (1.0 + net_s).cumprod()

    return BacktestResult(
        returns=net_s,
        gross_returns=gross_s,
        equity=equity,
        weights=pd.DataFrame(held_weights, index=idx),
        turnover=turn_s,
        total_costs=float((gross_s - net_s).sum()),
    )


def buy_and_hold(prices: pd.DataFrame, symbol: str) -> pd.Series:
    """Benchmark: daily returns of a single buy-and-hold position."""
    return prices[symbol].pct_change().fillna(0.0).rename(f"B&H {symbol}")


def month_end_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Return the last available trading date of each month in `index`."""
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby([index.year, index.month]).last().values)
