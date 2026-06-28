#!/usr/bin/env python3
"""
Can we actually beat SPY? Equity-beta + trend-timing variants, each bootstrapped.

The diversified blend doesn't beat SPY in normal regimes because it lacks equity
upside (PLAN §2I). Here we test ways to add equity beta / a market-timing alpha:

  1. Deployed blend                     — baseline
  2. Trend-timed equity                 — hold SPY while its 12m momentum > 0,
                                          else TLT (the classic "beat buy & hold"
                                          absolute-momentum market-timing rule)
  3. Core-satellite 50% SPY + 50% blend — always-on equity + diversifier
  4. 50% trend-timed-equity + 50% blend — timed equity + diversifier
  5. 3-sleeve (TSMOM + sector + trend-equity, 1/3 each)

Each is scored OOS (2019+) vs SPY with a 1000x block bootstrap: P(Sharpe>0),
P(beats SPY), and the in-sample Sharpe (consistency guard). Run:
    python research/equity_beta.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import SETTINGS, TSMOM_UNIVERSE, SECTOR_UNIVERSE, BENCHMARK
from data.market_data import get_daily_closes
from portfolio.allocator import build_target_weights
from strategies.tsmom import momentum_returns
from backtest.engine import run_backtest, rebalance_dates, buy_and_hold
from backtest.metrics import sharpe, max_drawdown, annual_return

OOS = "2019-01-01"
FREQ = "weekly"
N_BOOT = 1000
BLOCK = 21
TD = 252
SEED = 12345


def ann_sharpe(x):
    sd = x.std(ddof=0)
    return float(x.mean() / sd * np.sqrt(TD)) if sd > 0 else 0.0


def boot_vs_spy(strat_x, spy_x, rng):
    n = len(strat_x); nb = int(np.ceil(n / BLOCK))
    s_sh = np.empty(N_BOOT); beats = 0
    for i in range(N_BOOT):
        idx = (rng.integers(0, n - BLOCK + 1, nb)[:, None] + np.arange(BLOCK)).ravel()[:n]
        s_sh[i] = ann_sharpe(strat_x[idx])
        beats += s_sh[i] > ann_sharpe(spy_x[idx])
    return (s_sh > 0).mean(), beats / N_BOOT


def main() -> None:
    s = SETTINGS
    syms = sorted(set(TSMOM_UNIVERSE) | set(SECTOR_UNIVERSE) | {"SPY", "QQQ", "TLT", "BIL"})
    px = get_daily_closes(syms)
    rf = px["BIL"].pct_change().fillna(0.0)
    rebal = rebalance_dates(px.index, FREQ)
    spy = buy_and_hold(px, BENCHMARK)

    bt = build_target_weights(px[TSMOM_UNIVERSE], px[SECTOR_UNIVERSE], rebal,
                              s.params, s.risk, apply_vol_overlay=False)
    blend, tsmom_w, xsec_w = bt["final"], bt["tsmom"], bt["xsec"]

    # Trend-timed equity: SPY while its 12m momentum > 0, else TLT.
    spy_mom = momentum_returns(px[["SPY"]], 12, 0)["SPY"]
    cols = sorted(set(blend.columns) | {"SPY", "TLT", "QQQ"})

    def empty():
        return pd.DataFrame(0.0, index=rebal, columns=cols)

    trend_eq = empty()
    for d in rebal:
        up = spy_mom.loc[:d]
        trend_eq.loc[d, "SPY" if (len(up) and up.iloc[-1] > 0) else "TLT"] = 1.0

    def al(w):
        return w.reindex(columns=cols, fill_value=0.0)

    spy_w = empty(); spy_w["SPY"] = 1.0
    blend_a, tsmom_a, xsec_a = al(blend), al(tsmom_w), al(xsec_w)

    variants = {
        "Deployed blend (baseline)": blend_a,
        "Trend-timed equity (SPY/TLT)": trend_eq,
        "Core-sat 50% SPY + 50% blend": 0.5 * spy_w + 0.5 * blend_a,
        "50% trend-eq + 50% blend": 0.5 * trend_eq + 0.5 * blend_a,
        "3-sleeve (TSMOM+sector+trendEq)": (tsmom_a + xsec_a + trend_eq) / 3.0,
    }

    spy_oos = spy[spy.index >= OOS]
    print(f"OOS {OOS}+ vs Buy&Hold SPY (Sharpe {sharpe(spy_oos, rf=rf):.3f}, "
          f"CAGR {annual_return(spy_oos):.1%}, maxDD {max_drawdown(spy_oos):.1%})\n")
    print(f"{'Variant':33} {'OOS Sh':>7} {'IS Sh':>6} {'CAGR':>6} {'maxDD':>7} "
          f"{'P(beat SPY)':>11}")
    print("-" * 76)

    rng = np.random.default_rng(SEED)
    for name, w in variants.items():
        ret = run_backtest(px, w, s.costs, rf_returns=rf).returns
        oos, ins = ret[ret.index >= OOS], ret[ret.index < OOS]
        rfo = rf.reindex(oos.index)
        _, pbeat = boot_vs_spy(oos.to_numpy() - rfo.to_numpy(),
                               spy.reindex(oos.index).to_numpy() - rfo.to_numpy(), rng)
        print(f"{name:33} {sharpe(oos, rf=rf):>7.3f} {sharpe(ins, rf=rf):>6.3f} "
              f"{annual_return(oos):>6.1%} {max_drawdown(oos):>6.1%} {pbeat:>11.1%}")


if __name__ == "__main__":
    main()
