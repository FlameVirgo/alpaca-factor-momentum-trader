"""
Sleeve B — Cross-Sectional (Relative) Momentum, a.k.a. sector rotation.

At each monthly rebalance we rank the 11 SPDR sectors by 12-1 momentum (12-month
return, skipping the most recent month to dodge short-term reversal) and hold an
equal-weight basket of the top N. This is the *relative* momentum leg of dual
momentum: own whatever is strongest right now.

We add Antonacci's dual-momentum filter: a selected sector is only held if its
own absolute 12-1 momentum is positive. In a broad bear market where even the
"best" sector is falling, those slices go to cash instead. This is what keeps
the concave relative-momentum sleeve from bleeding through a full drawdown.
"""
from __future__ import annotations

import pandas as pd

from config import StrategyParams
from strategies.tsmom import momentum_returns


def xsec_weights(prices: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    """
    Target weights for the sector-rotation sleeve on every row of `prices`.

    Top `xsec_top_n` sectors by 12-1 momentum, equal weight (1/top_n each),
    but only the slices whose own momentum is positive are funded — the rest is
    held in cash (absolute-momentum overlay on the relative-momentum pick).
    """
    mom = momentum_returns(
        prices, params.xsec_lookback_months, params.xsec_skip_months
    )
    top_n = params.xsec_top_n
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)

    for date, row in mom.iterrows():
        ranked = row.dropna().sort_values(ascending=False)
        if ranked.empty:
            continue
        picks = ranked.head(top_n)
        for sym, m in picks.items():
            # Dual-momentum filter: fund the slice only if the sector itself is
            # trending up; otherwise that 1/top_n slice stays in cash.
            weights.loc[date, sym] = (1.0 / top_n) if m > 0.0 else 0.0

    return weights
