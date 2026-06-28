#!/usr/bin/env python3
"""
Research: sweep the sleeve blend weight (TSMOM vs sector), overfitting-guarded.

Instead of 50/50, try every split from 0/100 to 100/0 and look at the Sharpe.
The honest guard against curve-fitting is NOT to grab the highest out-of-sample
Sharpe — it is to check two things:

  1. Does the OOS-best weight ALSO win in-sample? If the best split out-of-sample
     is a different split than in-sample, the "winner" is regime luck, not edge.
  2. Is the Sharpe-vs-weight curve FLAT or PEAKED? A flat curve means the weight
     barely matters → keep the neutral 50/50 (nothing to overfit). A sharp peak
     at an extreme that only shows up OOS is the fingerprint of overfitting.

Deployed config: weekly, no vol overlay, current universe. Run:
    python research/sleeve_weights.py
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
from backtest.engine import run_backtest, rebalance_dates
from backtest.metrics import sharpe, max_drawdown

OOS = "2019-01-01"
FREQ = "weekly"


def main() -> None:
    s = SETTINGS
    syms = sorted(set(TSMOM_UNIVERSE) | set(SECTOR_UNIVERSE) | {BENCHMARK, "BIL"})
    px = get_daily_closes(syms)
    rf = px["BIL"].pct_change().fillna(0.0)
    tpx, spx = px[TSMOM_UNIVERSE], px[SECTOR_UNIVERSE]
    rebal = rebalance_dates(px.index, FREQ)
    spy = px[BENCHMARK].pct_change().fillna(0.0)
    spy_oos = sharpe(spy[spy.index >= OOS], rf=rf)

    print(f"Sleeve blend sweep — weekly, no overlay, after costs. "
          f"SPY OOS Sharpe = {spy_oos:.3f}\n")
    print(f"{'wTSMOM':>7} {'wSector':>8} | {'OOS Sharpe':>10} {'IS Sharpe':>9} "
          f"{'OOS maxDD':>9}")
    print("-" * 50)

    rows = []
    for w in np.round(np.arange(0.0, 1.0001, 0.1), 2):
        params = dataclasses.replace(s.params, weight_tsmom=float(w),
                                     weight_xsec=float(round(1.0 - w, 2)))
        wmat = build_target_weights(tpx, spx, rebal, params, s.risk,
                                    apply_vol_overlay=False)
        ret = run_backtest(px, wmat["final"], s.costs, rf_returns=rf).returns
        oos, ins = ret[ret.index >= OOS], ret[ret.index < OOS]
        r = dict(w=float(w), oos=sharpe(oos, rf=rf), ins=sharpe(ins, rf=rf),
                 dd=max_drawdown(oos))
        rows.append(r)
        mark = "  <- 50/50 (deployed)" if abs(w - 0.5) < 1e-9 else ""
        print(f"{w:>7.1f} {1.0 - w:>8.1f} | {r['oos']:>10.3f} {r['ins']:>9.3f} "
              f"{r['dd']:>8.1%}{mark}")

    best_oos = max(rows, key=lambda r: r["oos"])
    best_ins = max(rows, key=lambda r: r["ins"])
    spread = max(r["oos"] for r in rows) - min(r["oos"] for r in rows)

    print("\n── Overfitting-guarded read ──")
    print(f"  Best weight OUT-OF-SAMPLE : wTSMOM={best_oos['w']:.1f} "
          f"(OOS {best_oos['oos']:.3f}, in-sample {best_oos['ins']:.3f})")
    print(f"  Best weight IN-SAMPLE     : wTSMOM={best_ins['w']:.1f} "
          f"(in-sample {best_ins['ins']:.3f}, OOS {best_ins['oos']:.3f})")
    print(f"  OOS Sharpe spread across all weights: {spread:.3f}")
    if best_oos["w"] != best_ins["w"]:
        print("  → OOS-best and in-sample-best DISAGREE: tilting away from 50/50 "
              "is overfitting. Keep 50/50.")
    elif spread < 0.10:
        print("  → Curve is essentially FLAT (spread < 0.10 Sharpe): the weight "
              "barely matters. Keep the neutral 50/50.")
    else:
        print("  → Same weight wins both halves AND the curve is peaked: a modest "
              "tilt may be defensible (still one dataset — validate on a 2nd window).")


if __name__ == "__main__":
    main()
