"""
Live target-weight snapshot.

The backtester evaluates the allocator across a whole calendar of monthly
rebalance dates. For live trading we only need the *current* target: given the
latest price history, what weights should the book hold as of the most recent
(month-end) rebalance? This module reuses the exact same allocator pipeline as
the backtest — so live and backtest are guaranteed identical — and returns a
single weight vector for today.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from config import (StrategyParams, RiskLimits, TSMOM_UNIVERSE, SECTOR_UNIVERSE,
                    CORE_EQUITY_SYMBOL, CORE_EQUITY_WEIGHT)
from portfolio.allocator import build_target_weights


def latest_target_weights(
    prices: pd.DataFrame,
    params: StrategyParams,
    risk: RiskLimits,
    as_of: Optional[pd.Timestamp] = None,
    apply_vol_overlay: bool = False,  # deployed strategy is the 50/50 blend, no overlay
) -> pd.Series:
    """
    Target weights for the most recent rebalance (default: last row of `prices`).

    `prices` is a wide DataFrame of adjusted closes covering the full universe.
    Returns a Series indexed by symbol (zero-weight names dropped), summing to
    <= 1.0 with the remainder implicitly in cash.
    """
    prices = prices.sort_index()
    as_of = pd.Timestamp(as_of) if as_of is not None else prices.index[-1]
    if as_of not in prices.index:
        # snap to the most recent available trading day on/before as_of
        as_of = prices.index[prices.index <= as_of][-1]

    tsmom_cols = [c for c in TSMOM_UNIVERSE if c in prices.columns]
    sector_cols = [c for c in SECTOR_UNIVERSE if c in prices.columns]
    missing = (set(TSMOM_UNIVERSE) - set(tsmom_cols)) | (set(SECTOR_UNIVERSE) - set(sector_cols))
    if missing:
        raise ValueError(f"Price history missing universe symbols: {sorted(missing)}")

    rebal = pd.DatetimeIndex([as_of])
    weights = build_target_weights(
        prices[tsmom_cols],
        prices[sector_cols],
        rebal,
        params,
        risk,
        apply_vol_overlay=apply_vol_overlay,
    )
    final = weights["final"].loc[as_of]

    # Core-satellite (deployed strategy): scale the diversifying blend down to
    # (1 - core) and add the always-on SPY equity core (exempt from the cap).
    cw = CORE_EQUITY_WEIGHT
    if cw > 0:
        final = final * (1.0 - cw)
        final[CORE_EQUITY_SYMBOL] = final.get(CORE_EQUITY_SYMBOL, 0.0) + cw

    return final[final.abs() > 1e-9].sort_values(ascending=False)
