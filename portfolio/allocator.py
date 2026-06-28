"""
Portfolio allocator: combine the sleeves into a single set of monthly target
weights, apply the vol overlay, and enforce risk limits.

Pipeline (all at month-end rebalance dates):

    1. Sleeve A weights (cross-asset absolute momentum)   — strategies.tsmom
    2. Sleeve B weights (sector relative momentum)        — strategies.xsec_momentum
    3. Blend:  w = wA*weight_tsmom + wB*weight_xsec
    4. Vol overlay: scale blended book toward target vol (de-risk only)
    5. Risk caps: clip any single name to max_position_weight
"""
from __future__ import annotations

import pandas as pd

from config import StrategyParams, RiskLimits
from strategies.tsmom import tsmom_weights
from strategies.xsec_momentum import xsec_weights
from strategies.vol_target import vol_scaled_weights


def _blend(
    wa: pd.DataFrame, wb: pd.DataFrame, params: StrategyParams
) -> pd.DataFrame:
    """Union the two sleeve weight matrices on a shared column space and blend."""
    cols = sorted(set(wa.columns) | set(wb.columns))
    wa = wa.reindex(columns=cols, fill_value=0.0)
    wb = wb.reindex(columns=cols, fill_value=0.0)
    return wa * params.weight_tsmom + wb * params.weight_xsec


def build_target_weights(
    tsmom_prices: pd.DataFrame,
    sector_prices: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    params: StrategyParams,
    risk: RiskLimits,
    apply_vol_overlay: bool = True,
) -> dict[str, pd.DataFrame]:
    """
    Produce target-weight matrices for every stage of the pipeline, each indexed
    by `rebalance_dates`. Returns a dict so the backtest can compare sleeves:

        {"tsmom", "xsec", "blended", "final"}

    `final` == `blended` with the vol overlay + risk caps applied (or just the
    caps if apply_vol_overlay is False).
    """
    wa = tsmom_weights(tsmom_prices, params).reindex(rebalance_dates).fillna(0.0)
    wb = xsec_weights(sector_prices, params).reindex(rebalance_dates).fillna(0.0)
    blended = _blend(wa, wb, params)

    # Daily asset returns across the full universe for the vol overlay.
    all_prices = pd.concat([tsmom_prices, sector_prices], axis=1)
    all_prices = all_prices.loc[:, ~all_prices.columns.duplicated()].sort_index()
    asset_returns = all_prices.pct_change().fillna(0.0)

    if apply_vol_overlay:
        final = vol_scaled_weights(blended, asset_returns, rebalance_dates, params)
    else:
        final = blended.copy()

    # Risk cap: bound any single ETF to ±max_position_weight (the lower bound
    # only binds when shorting is enabled; for long-only it's a no-op).
    final = final.clip(lower=-risk.max_position_weight, upper=risk.max_position_weight)

    return {
        "tsmom": wa.reindex(columns=blended.columns, fill_value=0.0),
        "xsec": wb.reindex(columns=blended.columns, fill_value=0.0),
        "blended": blended,
        "final": final,
    }
