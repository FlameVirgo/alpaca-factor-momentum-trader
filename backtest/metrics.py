"""
Performance metrics for evaluating a backtest equity curve / return series.
All functions take a pandas Series of *periodic* (daily) returns unless noted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def annual_return(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    """Geometric (CAGR-style) annualized return."""
    if len(returns) == 0:
        return 0.0
    growth = (1.0 + returns).prod()
    years = len(returns) / periods_per_year
    if years <= 0 or growth <= 0:
        return 0.0
    return growth ** (1.0 / years) - 1.0


def annual_vol(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    return float(returns.std(ddof=0) * np.sqrt(periods_per_year))


def sharpe(returns: pd.Series, rf: float = 0.0, periods_per_year: int = TRADING_DAYS) -> float:
    """Annualized Sharpe ratio. `rf` is the annual risk-free rate."""
    if returns.std(ddof=0) == 0 or len(returns) == 0:
        return 0.0
    excess = returns - rf / periods_per_year
    return float(excess.mean() / returns.std(ddof=0) * np.sqrt(periods_per_year))


def sortino(returns: pd.Series, rf: float = 0.0, periods_per_year: int = TRADING_DAYS) -> float:
    """Annualized Sortino ratio (downside-deviation denominator)."""
    if len(returns) == 0:
        return 0.0
    excess = returns - rf / periods_per_year
    downside = excess[excess < 0]
    dd = downside.std(ddof=0)
    if dd == 0:
        return 0.0
    return float(excess.mean() / dd * np.sqrt(periods_per_year))


def max_drawdown(returns: pd.Series) -> float:
    """Maximum peak-to-trough drawdown of the cumulative equity curve (negative)."""
    if len(returns) == 0:
        return 0.0
    equity = (1.0 + returns).cumprod()
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(drawdown.min())


def calmar(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    mdd = abs(max_drawdown(returns))
    if mdd == 0:
        return 0.0
    return annual_return(returns, periods_per_year) / mdd


def summary(returns: pd.Series, name: str = "strategy", rf: float = 0.0) -> dict:
    """Return a dict of headline metrics for a return series."""
    returns = returns.dropna()
    return {
        "name": name,
        "ann_return": annual_return(returns),
        "ann_vol": annual_vol(returns),
        "sharpe": sharpe(returns, rf=rf),
        "sortino": sortino(returns, rf=rf),
        "max_drawdown": max_drawdown(returns),
        "calmar": calmar(returns),
        "n_periods": int(len(returns)),
    }


def format_summary(stats: dict) -> str:
    """Human-readable one-block summary."""
    return (
        f"── {stats['name']} ──\n"
        f"  Ann. Return : {stats['ann_return']:>8.2%}\n"
        f"  Ann. Vol    : {stats['ann_vol']:>8.2%}\n"
        f"  Sharpe      : {stats['sharpe']:>8.2f}\n"
        f"  Sortino     : {stats['sortino']:>8.2f}\n"
        f"  Max DD      : {stats['max_drawdown']:>8.2%}\n"
        f"  Calmar      : {stats['calmar']:>8.2f}\n"
        f"  Periods     : {stats['n_periods']:>8d}"
    )
