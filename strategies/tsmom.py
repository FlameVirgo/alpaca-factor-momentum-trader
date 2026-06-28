"""
Sleeve A — Time-Series (Absolute) Momentum.

For each asset in the cross-asset universe we ask one question at each monthly
rebalance: "is this asset in an uptrend over the last ~12 months?" If yes, we
hold an equal slice of it; if no, that slice goes to cash. This is the
*absolute* momentum leg of dual momentum (Antonacci) and the engine of the
2008-style crash hedge: when equities are falling but TLT/GLD are trending up,
the sleeve rotates into the safe-havens that still pass the trend filter.

Long/flat only (no shorting) in v1 — see PLAN.md. The natural de-risking is the
cash buffer that appears automatically when fewer assets are trending.
"""
from __future__ import annotations

import pandas as pd

from config import StrategyParams

MONTH = 21  # trading days per month (approx)


def momentum_returns(
    prices: pd.DataFrame, lookback_months: int, skip_months: int = 0
) -> pd.DataFrame:
    """
    Total return over [t - lookback, t - skip] for every (date, symbol).

    `skip_months` excludes the most recent N months (the classic 12-1 skip that
    sidesteps short-term reversal). Returns NaN until enough history exists.
    """
    lb = lookback_months * MONTH
    sk = skip_months * MONTH
    past = prices.shift(lb)
    recent = prices.shift(sk) if sk > 0 else prices
    return recent / past - 1.0


def tsmom_weights(prices: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    """
    Target weights for the absolute-momentum sleeve, evaluated on every row of
    `prices` (caller slices to rebalance dates).

    Each asset receives weight 1/N if its absolute momentum is positive, else 0,
    where N is the universe size. The sleeve is therefore at most 100% invested
    and de-risks to cash as assets roll over.
    """
    mom = momentum_returns(
        prices, params.tsmom_lookback_months, params.tsmom_skip_months
    )
    n = prices.shape[1]
    signal = (mom > 0.0).astype(float)
    return signal / n
