#!/usr/bin/env python3
"""
Sharpe reliability via block bootstrap (the deployed 50/50 blend).

The backtest is deterministic, so re-running it gives the same number. To judge
how *reliable* the out-of-sample Sharpe (~0.81) is, we resample the strategy's
realized daily return series 1000× with a **moving-block bootstrap** (block
length ≈ 1 month, which preserves the momentum autocorrelation that an IID
bootstrap would destroy), recompute the annualized Sharpe each time, and study
the distribution.

The same resampled time-blocks are applied to SPY (paired), so we can also get
the distribution of (strategy Sharpe − SPY Sharpe) and the probability the
strategy actually beats buy-and-hold out-of-sample.

Run:  python research/bootstrap_sharpe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import SETTINGS, TSMOM_UNIVERSE, SECTOR_UNIVERSE, BENCHMARK
from data.market_data import get_daily_closes
from portfolio.allocator import build_target_weights
from backtest.engine import run_backtest, rebalance_dates, buy_and_hold

OOS = "2019-01-01"
FREQ = "weekly"
N_BOOT = 1000
BLOCK = 21          # ~1 trading month per block
TD = 252
SEED = 12345


def ann_sharpe(excess: np.ndarray) -> float:
    sd = excess.std(ddof=0)
    return float(excess.mean() / sd * np.sqrt(TD)) if sd > 0 else 0.0


def main() -> None:
    s = SETTINGS
    syms = sorted(set(TSMOM_UNIVERSE) | set(SECTOR_UNIVERSE) | {BENCHMARK, "BIL"})
    px = get_daily_closes(syms)
    rf = px["BIL"].pct_change().fillna(0.0)
    rebal = rebalance_dates(px.index, FREQ)

    wmat = build_target_weights(px[TSMOM_UNIVERSE], px[SECTOR_UNIVERSE], rebal,
                                s.params, s.risk, apply_vol_overlay=False)
    strat = run_backtest(px, wmat["final"], s.costs, rf_returns=rf).returns
    spy = buy_and_hold(px, BENCHMARK)

    # Out-of-sample excess returns over the risk-free, aligned.
    mask = strat.index >= OOS
    rf_o = rf[mask].to_numpy()
    strat_x = strat[mask].to_numpy() - rf_o
    spy_x = spy[mask].reindex(strat[mask].index).to_numpy() - rf_o
    n = len(strat_x)

    pt_strat, pt_spy = ann_sharpe(strat_x), ann_sharpe(spy_x)
    print(f"Out-of-sample window: {strat[mask].index[0].date()} → "
          f"{strat[mask].index[-1].date()}  ({n} days, ~{n/TD:.1f} yrs)")
    print(f"Point estimates — strategy Sharpe {pt_strat:.3f}, SPY Sharpe {pt_spy:.3f}\n")

    rng = np.random.default_rng(SEED)
    n_blocks = int(np.ceil(n / BLOCK))
    s_sharpes = np.empty(N_BOOT)
    d_sharpes = np.empty(N_BOOT)
    for i in range(N_BOOT):
        starts = rng.integers(0, n - BLOCK + 1, size=n_blocks)
        idx = (starts[:, None] + np.arange(BLOCK)).ravel()[:n]
        s_sharpes[i] = ann_sharpe(strat_x[idx])
        d_sharpes[i] = s_sharpes[i] - ann_sharpe(spy_x[idx])

    def pct(a, p):
        return float(np.percentile(a, p))

    print(f"Block bootstrap: {N_BOOT} resamples, block={BLOCK} days "
          f"(preserves autocorrelation)\n")
    print("Strategy annualized Sharpe distribution:")
    print(f"  mean {s_sharpes.mean():.3f}   median {np.median(s_sharpes):.3f}   "
          f"std (std error) {s_sharpes.std(ddof=1):.3f}")
    print(f"  95% CI  [{pct(s_sharpes,2.5):.3f}, {pct(s_sharpes,97.5):.3f}]")
    print(f"  P(Sharpe > 0)    = {(s_sharpes > 0).mean():.1%}")
    print(f"  P(Sharpe > 0.5)  = {(s_sharpes > 0.5).mean():.1%}")
    print(f"  P(Sharpe > {pt_spy:.2f}) = {(s_sharpes > pt_spy).mean():.1%}   "
          f"(> SPY point estimate)")

    print("\nStrategy minus SPY (paired, same resampled blocks):")
    print(f"  mean Δ Sharpe {d_sharpes.mean():.3f}   "
          f"95% CI [{pct(d_sharpes,2.5):.3f}, {pct(d_sharpes,97.5):.3f}]")
    print(f"  P(strategy beats SPY) = {(d_sharpes > 0).mean():.1%}")


if __name__ == "__main__":
    main()
