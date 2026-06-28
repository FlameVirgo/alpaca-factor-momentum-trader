#!/usr/bin/env python3
"""
Momentum-lookback sweep with the overfitting guard + Sharpe bootstrap.

For each lookback in {1, 3, 6, 9, 12} months we rebuild both sleeves with that
formation window (skip=0 so a 1-month lookback is well-defined), run the deployed
blend (no overlay, weekly), and report:
  - out-of-sample Sharpe (2019+) and in-sample Sharpe (pre-2019) — consistency
  - max drawdown (user accepts more DD for real Sharpe)
  - 1000x block bootstrap of the OOS returns: P(Sharpe>0) and P(beats SPY)

"Reliably best" = high P(beats SPY) AND the same lookback isn't great OOS only
(in-sample must also be decent). The argmax OOS Sharpe alone is overfitting.

Run:  python research/lookback_sweep.py
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import SETTINGS, TSMOM_UNIVERSE, SECTOR_UNIVERSE, BENCHMARK
from data.market_data import get_daily_closes
from portfolio.allocator import build_target_weights
from backtest.engine import run_backtest, rebalance_dates, buy_and_hold
from backtest.metrics import sharpe, max_drawdown

OOS = "2019-01-01"
FREQ = "weekly"
LOOKBACKS = [1, 3, 6, 9, 12]
N_BOOT = 1000
BLOCK = 21
TD = 252
SEED = 12345


def ann_sharpe(x: np.ndarray) -> float:
    sd = x.std(ddof=0)
    return float(x.mean() / sd * np.sqrt(TD)) if sd > 0 else 0.0


def bootstrap(strat_x, spy_x, rng):
    n = len(strat_x); nb = int(np.ceil(n / BLOCK))
    s_sh = np.empty(N_BOOT); beats = 0
    for i in range(N_BOOT):
        idx = (rng.integers(0, n - BLOCK + 1, nb)[:, None] + np.arange(BLOCK)).ravel()[:n]
        s_sh[i] = ann_sharpe(strat_x[idx])
        beats += s_sh[i] > ann_sharpe(spy_x[idx])
    return s_sh, beats / N_BOOT


def main() -> None:
    s = SETTINGS
    syms = sorted(set(TSMOM_UNIVERSE) | set(SECTOR_UNIVERSE) | {BENCHMARK, "BIL"})
    px = get_daily_closes(syms)
    rf = px["BIL"].pct_change().fillna(0.0)
    tpx, spx = px[TSMOM_UNIVERSE], px[SECTOR_UNIVERSE]
    rebal = rebalance_dates(px.index, FREQ)
    spy = buy_and_hold(px, BENCHMARK)
    spy_oos_sh = sharpe(spy[spy.index >= OOS], rf=rf)
    print(f"Deployed blend (no overlay, weekly). SPY OOS Sharpe = {spy_oos_sh:.3f}\n")
    print(f"{'LB(mo)':>6} {'OOS Sh':>7} {'IS Sh':>6} {'OOS DD':>7} {'OOS CAGR':>8} "
          f"{'P(Sh>0)':>8} {'P(beat SPY)':>11} {'OOS Sh 95% CI':>16}")
    print("-" * 78)

    rng = np.random.default_rng(SEED)
    results = []
    for lb in LOOKBACKS:
        # Keep the deployed skip convention (tsmom skip=0, xsec 12-1 style) so
        # lb=12 reproduces the deployed config; skip is 0 at lb=1 (1-1 is invalid).
        xsec_skip = 1 if lb > 1 else 0
        params = dataclasses.replace(s.params, tsmom_lookback_months=lb,
                                     xsec_lookback_months=lb,
                                     tsmom_skip_months=0, xsec_skip_months=xsec_skip)
        w = build_target_weights(tpx, spx, rebal, params, s.risk, apply_vol_overlay=False)
        ret = run_backtest(px, w["final"], s.costs, rf_returns=rf).returns
        oos, ins = ret[ret.index >= OOS], ret[ret.index < OOS]
        rf_o = rf.reindex(oos.index)
        sx = oos.to_numpy() - rf_o.to_numpy()
        spx_o = spy.reindex(oos.index).to_numpy() - rf_o.to_numpy()
        s_sh, p_beat = bootstrap(sx, spx_o, rng)
        from backtest.metrics import annual_return
        r = dict(lb=lb, oos=sharpe(oos, rf=rf), ins=sharpe(ins, rf=rf),
                 dd=max_drawdown(oos), cagr=annual_return(oos),
                 p0=(s_sh > 0).mean(), pbeat=p_beat,
                 lo=np.percentile(s_sh, 2.5), hi=np.percentile(s_sh, 97.5))
        results.append(r)
        print(f"{lb:>6} {r['oos']:>7.3f} {r['ins']:>6.3f} {r['dd']:>6.1%} "
              f"{r['cagr']:>7.1%} {r['p0']:>8.1%} {r['pbeat']:>11.1%} "
              f"   [{r['lo']:.2f}, {r['hi']:.2f}]")

    print("\n── Reliably-best read (not just argmax OOS) ──")
    best_oos = max(results, key=lambda r: r["oos"])
    best_beat = max(results, key=lambda r: r["pbeat"])
    best_consistent = max(results, key=lambda r: min(r["oos"], r["ins"]))
    print(f"  Highest OOS Sharpe : {best_oos['lb']}mo ({best_oos['oos']:.3f}, "
          f"in-sample {best_oos['ins']:.3f})")
    print(f"  Highest P(beats SPY): {best_beat['lb']}mo ({best_beat['pbeat']:.1%})")
    print(f"  Best in BOTH halves : {best_consistent['lb']}mo "
          f"(min(OOS,IS)={min(best_consistent['oos'], best_consistent['ins']):.3f})")


if __name__ == "__main__":
    main()
