#!/usr/bin/env python3
"""
Long-window backtest + Sharpe-reliability bootstrap (~2005–2026).

The 2011-start backtest never saw a real crisis. Here we extend as far back as
the data honestly allows and re-run the deployed blend + the 1000x bootstrap.

Hard constraint: the cross-asset ETFs didn't exist in 2000. The deployed
independent universe only reaches ~2008 (EMB launched Dec 2007), so for the long
window we use the original 6-ETF cross-asset set (TSMOM_UNIVERSE_CORE6 — also the
more *consistent* universe per PLAN §2F), which reaches GLD's Nov-2004 inception.
Risk-free is the 13-week T-bill yield (^IRX), which has decades of history (BIL,
the usual proxy, only starts 2007).

Run:  python research/long_window.py
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import SETTINGS, TSMOM_UNIVERSE_CORE6, SECTOR_UNIVERSE, BENCHMARK
from data.market_data import _fetch_one          # single-symbol fetch, no cache write
from portfolio.allocator import build_target_weights
from backtest.engine import run_backtest, rebalance_dates, buy_and_hold
from backtest.metrics import sharpe, max_drawdown, annual_return

FREQ = "weekly"
N_BOOT = 1000
BLOCK = 21
TD = 252
SEED = 12345
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_CTX = ssl.create_default_context()


def fetch_irx_rf(index: pd.DatetimeIndex) -> pd.Series:
    """13-week T-bill yield (^IRX) → daily risk-free return, aligned to `index`."""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%5EIRX"
           "?range=25y&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    res = json.loads(urllib.request.urlopen(req, timeout=30, context=_CTX).read())
    r = res["chart"]["result"][0]
    ts = r["timestamp"]
    close = r["indicators"]["quote"][0]["close"]   # yield in percent
    idx = pd.to_datetime([datetime.fromtimestamp(t, tz=timezone.utc) for t in ts])
    yld = pd.Series(close, index=idx.tz_localize(None).normalize()).dropna()
    daily = (yld / 100.0) / TD                      # annual % → daily fraction
    return daily.reindex(index).ffill().fillna(0.0)


def ann_sharpe(excess: np.ndarray) -> float:
    sd = excess.std(ddof=0)
    return float(excess.mean() / sd * np.sqrt(TD)) if sd > 0 else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description="long-window backtest + bootstrap")
    ap.add_argument("--start", default=None,
                    help="evaluation window start (e.g. 2010-01-01); data still "
                         "loads earlier for momentum warmup")
    args = ap.parse_args()
    s = SETTINGS
    syms = sorted(set(TSMOM_UNIVERSE_CORE6) | set(SECTOR_UNIVERSE) | {BENCHMARK})
    print(f"Fetching {len(syms)} symbols, 25y range (this hits the network)...")
    px = pd.DataFrame({sym: _fetch_one(sym, range_="25y") for sym in syms}).sort_index()

    # Start where the whole core-6 sleeve has data (GLD is the binding inception).
    start = px[TSMOM_UNIVERSE_CORE6].dropna().index[0]
    px = px.loc[start:].ffill()
    rf = fetch_irx_rf(px.index)
    rf_ann = (1 + rf).prod() ** (TD / len(rf)) - 1
    print(f"Window: {px.index[0].date()} → {px.index[-1].date()} "
          f"({len(px)} days, ~{len(px)/TD:.1f} yrs).  Risk-free ~{rf_ann:.2%}/yr\n")

    rebal = rebalance_dates(px.index, FREQ)
    wmat = build_target_weights(px[TSMOM_UNIVERSE_CORE6], px[SECTOR_UNIVERSE], rebal,
                                s.params, s.risk, apply_vol_overlay=False)
    strat = run_backtest(px, wmat["final"], s.costs, rf_returns=rf).returns
    spy = buy_and_hold(px, BENCHMARK)

    # Skip the first 12m (momentum warmup); apply --start if given.
    eval_start = px.index[0] + pd.Timedelta(days=400)
    if args.start:
        eval_start = max(eval_start, pd.Timestamp(args.start))
    live = strat.index[strat.index >= eval_start]
    strat, spy_l, rf_l = strat.loc[live], spy.loc[live], rf.loc[live]

    def block(lbl, r):
        print(f"  {lbl:24} Sharpe {sharpe(r, rf=rf_l):>6.3f}   "
              f"CAGR {annual_return(r):>6.1%}   maxDD {max_drawdown(r):>6.1%}")

    print(f"Deployed blend (core-6, no overlay, weekly) vs SPY, {live[0].date()}→{live[-1].date()}:")
    block("STRATEGY (full window)", strat)
    block("Buy & Hold SPY", spy_l)
    print("  per-regime strategy Sharpe:")
    for lbl, a, b in [("2008 crisis 07-09", "2007-01-01", "2009-12-31"),
                      ("2010s 10-18", "2010-01-01", "2018-12-31"),
                      ("recent 19-26", "2019-01-01", "2026-12-31")]:
        seg = strat[(strat.index >= a) & (strat.index <= b)]
        if len(seg) > 60:
            print(f"    {lbl:18} {sharpe(seg, rf=rf_l):>6.3f}   maxDD {max_drawdown(seg):>6.1%}")

    # ── Bootstrap the full long return series ────────────────────────────────
    sx = strat.to_numpy() - rf_l.to_numpy()
    spx = spy_l.reindex(strat.index).to_numpy() - rf_l.to_numpy()
    n = len(sx)
    rng = np.random.default_rng(SEED)
    nb = int(np.ceil(n / BLOCK))
    s_sh = np.empty(N_BOOT); d_sh = np.empty(N_BOOT)
    for i in range(N_BOOT):
        idx = (rng.integers(0, n - BLOCK + 1, nb)[:, None] + np.arange(BLOCK)).ravel()[:n]
        s_sh[i] = ann_sharpe(sx[idx])
        d_sh[i] = s_sh[i] - ann_sharpe(spx[idx])

    p = lambda a, q: float(np.percentile(a, q))
    print(f"\nBlock bootstrap ({N_BOOT}x, block={BLOCK}d) on the {n/TD:.1f}-yr series:")
    print(f"  Strategy Sharpe: mean {s_sh.mean():.3f}  std-err {s_sh.std(ddof=1):.3f}  "
          f"95% CI [{p(s_sh,2.5):.3f}, {p(s_sh,97.5):.3f}]")
    print(f"  P(Sharpe>0)={ (s_sh>0).mean():.1%}  P(>0.5)={ (s_sh>0.5).mean():.1%}")
    print(f"  Strategy − SPY: mean Δ {d_sh.mean():.3f}  95% CI "
          f"[{p(d_sh,2.5):.3f}, {p(d_sh,97.5):.3f}]  P(beats SPY)={ (d_sh>0).mean():.1%}")


if __name__ == "__main__":
    main()
