"""
Conservative portfolio-level volatility-targeting overlay.

Rather than scaling each sleeve independently (the textbook Moreira-Muir
approach, which has weak out-of-sample results), RHDM applies a single capped
scalar to the *blended* portfolio. The scalar can only ever de-risk:

    scale = min(max_leverage, target_vol / realized_vol)      , max_leverage = 1.0

so in calm markets scale ≈ 1.0 (fully invested) and in vol spikes it shrinks
exposure toward cash. We never gear above 1.0. This sidesteps the documented
out-of-sample failure mode of aggressive vol-management while keeping the
crash-time de-risking. Realized vol is measured on a trailing window strictly
*before* each rebalance, so there is no look-ahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import StrategyParams


def blended_daily_returns(
    weights: pd.DataFrame, asset_returns: pd.DataFrame
) -> pd.Series:
    """Daily returns of a (month-end) weight matrix, forward-filled to daily."""
    daily_w = weights.reindex(asset_returns.index).ffill().fillna(0.0)
    cols = [c for c in daily_w.columns if c in asset_returns.columns]
    return (daily_w[cols] * asset_returns[cols]).sum(axis=1)


def vol_scaled_weights(
    blended_weights: pd.DataFrame,
    asset_returns: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    params: StrategyParams,
) -> pd.DataFrame:
    """
    Apply the conservative vol overlay to month-end `blended_weights`.

    For each rebalance date we estimate annualized realized vol of the blended
    book over the trailing `vol_lookback_days`, compute the capped scale, and
    multiply that date's weights by it. Returns a weight matrix on the same
    rebalance index.
    """
    port_ret = blended_daily_returns(blended_weights, asset_returns)
    ppy = params.trading_days_per_year
    scaled = blended_weights.copy()

    for date in rebalance_dates:
        window = port_ret.loc[:date].iloc[-params.vol_lookback_days:]
        if len(window) < params.vol_lookback_days // 2:
            continue  # not enough history yet — leave unscaled (early period)
        realized = float(window.std(ddof=0) * np.sqrt(ppy))
        if realized <= 0:
            scale = params.max_leverage
        else:
            scale = min(params.max_leverage, params.target_annual_vol / realized)
        scaled.loc[date] = blended_weights.loc[date] * scale

    return scaled
