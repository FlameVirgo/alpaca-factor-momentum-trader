#!/usr/bin/env python3
"""
Research: TSMOM on the MAXIMALLY-INDEPENDENT ETF universe.

Lesson from PLAN §2E: broadening to 18 ETFs *hurt* because most were correlated
(six bond/credit funds that move together) — more tickers ≠ more independent
bets, and time-series-momentum Sharpe is driven by the number of *independent*
bets. So here we instead pick the largest set of *predominantly independent*
liquid ETFs and run the sleeve on that.

Method (look-ahead-safe):
  1. Candidate pool of ~20 liquid ETFs spanning every asset class.
  2. Compute pairwise correlations on the **in-sample** half only (pre-2019).
  3. Greedy selection: order candidates most-independent-first (lowest average
     |corr|), add each only if its |corr| to everything already chosen stays
     below a threshold. That yields the "n independent ETFs".
  4. Run the sleeve / blend on that universe, weekly, after costs, OOS 2019+.

Run:  python research/independent_universe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import SETTINGS, SECTOR_UNIVERSE, BENCHMARK, TSMOM_UNIVERSE
from data.market_data import get_daily_closes
from portfolio.allocator import build_target_weights
from backtest.engine import run_backtest, rebalance_dates
from backtest.metrics import sharpe, max_drawdown, annual_return, annual_vol
from strategies.tsmom import tsmom_weights

OOS = "2019-01-01"
FREQ = "weekly"

# Broad candidate pool across every liquid asset class with ≥2010 history.
CANDIDATES = [
    "SPY", "QQQ", "IWM",                  # US equity
    "EFA", "VEA", "EEM",                  # intl developed / EM equity
    "TLT", "IEF", "SHY",                  # govt bond curve
    "LQD", "HYG", "TIP", "EMB",           # IG / HY / TIPS / EM bonds
    "GLD", "SLV", "DBC", "USO", "DBA",    # commodities
    "VNQ",                                # real estate
    "UUP",                                # US dollar
]


def select_independent(returns: pd.DataFrame, threshold: float) -> list[str]:
    """Greedy: most-independent-first, add while |corr| to chosen < threshold."""
    corr = returns.corr()
    order = corr.abs().mean().sort_values().index  # most independent on average first
    chosen: list[str] = []
    for sym in order:
        if all(abs(corr.loc[sym, s]) < threshold for s in chosen):
            chosen.append(sym)
    return chosen


def _stats(returns: pd.Series, rf: pd.Series, label: str) -> dict:
    oos = returns[returns.index >= OOS]
    ins = returns[returns.index < OOS]
    return dict(label=label, oos_sharpe=sharpe(oos, rf=rf), is_sharpe=sharpe(ins, rf=rf),
                oos_ret=annual_return(oos), oos_vol=annual_vol(oos), oos_dd=max_drawdown(oos))


def main() -> None:
    s = SETTINGS
    syms = sorted(set(CANDIDATES) | set(SECTOR_UNIVERSE) | {BENCHMARK, "BIL"})
    px = get_daily_closes(syms)
    rf = px["BIL"].pct_change().fillna(0.0)
    rets = px[CANDIDATES].pct_change().fillna(0.0)
    in_sample = rets[rets.index < OOS]

    for thr in (0.60, 0.70, 0.80):
        chosen = select_independent(in_sample, thr)
        print(f"|corr| < {thr:.2f}  →  n={len(chosen)}:  {chosen}")
    print()

    THRESH = 0.70
    universe = select_independent(in_sample, THRESH)
    print(f"Using independent universe (|corr|<{THRESH}, n={len(universe)}): {universe}\n")

    sector_px = px[SECTOR_UNIVERSE]
    rebal = rebalance_dates(px.index, FREQ)

    def run_for(tsmom_universe: list[str], tag: str) -> list[dict]:
        tpx = px[tsmom_universe]
        w = build_target_weights(tpx, sector_px, rebal, s.params, s.risk, apply_vol_overlay=True)
        w0 = build_target_weights(tpx, sector_px, rebal, s.params, s.risk, apply_vol_overlay=False)
        tsmom = run_backtest(px, w["tsmom"], s.costs, rf_returns=rf).returns
        rhdm = run_backtest(px, w["final"], s.costs, rf_returns=rf).returns
        blend0 = run_backtest(px, w0["final"], s.costs, rf_returns=rf).returns
        return [
            _stats(tsmom, rf, f"TSMOM sleeve [{tag}]"),
            _stats(rhdm, rf, f"RHDM full (overlay) [{tag}]"),
            _stats(blend0, rf, f"Blended NO overlay [{tag}]"),
        ]

    rows = run_for(universe, f"indep n={len(universe)}")
    rows += run_for(TSMOM_UNIVERSE, "orig 6")
    spy = px[BENCHMARK].pct_change().fillna(0.0)
    rows.append(_stats(spy, rf, "Buy & Hold SPY"))

    print(f"{'Strategy':36} {'OOS Sharpe':>10} {'IS Sharpe':>9} {'OOS Ret':>8} "
          f"{'OOS Vol':>8} {'OOS DD':>8}")
    print("-" * 84)
    for r in rows:
        print(f"{r['label']:36} {r['oos_sharpe']:>10.3f} {r['is_sharpe']:>9.3f} "
              f"{r['oos_ret']:>7.1%} {r['oos_vol']:>8.1%} {r['oos_dd']:>7.1%}")


if __name__ == "__main__":
    main()
