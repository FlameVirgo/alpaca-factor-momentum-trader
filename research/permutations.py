#!/usr/bin/env python3
"""
Research harness: test the three TSMOM levers in every permutation.

Levers (see config / strategies.tsmom):
  a = broad universe (TSMOM_UNIVERSE_BROAD)
  b = short leg (tsmom_allow_short)
  c = risk-scaled inverse-vol sizing (tsmom_risk_scaled)

For each of the 2^3 = 8 combinations we rebuild the TSMOM sleeve, blend it with
the (fixed) sector sleeve under the vol overlay, and run the honest weekly
backtest (execution lag + real risk-free + costs + short borrow). We report, for
both the TSMOM sleeve alone and the full RHDM:
  - out-of-sample Sharpe (2019+), the headline
  - in-sample Sharpe (pre-2019)

Why both halves: picking the highest OOS Sharpe across 8 variants is overfitting.
The honest check is whether the OOS winner is ALSO strong in-sample. If the OOS
ranking doesn't match the in-sample ranking, the "winner" is largely noise.

Run:  python research/permutations.py
"""
from __future__ import annotations

import dataclasses
import sys
from itertools import product
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (SETTINGS, TSMOM_UNIVERSE, TSMOM_UNIVERSE_BROAD,
                    SECTOR_UNIVERSE, BENCHMARK)
from data.market_data import get_daily_closes
from portfolio.allocator import build_target_weights
from backtest.engine import run_backtest, rebalance_dates
from backtest.metrics import sharpe, max_drawdown

OOS = "2019-01-01"
FREQ = "weekly"


def _sharpe_split(returns: pd.Series, rf: pd.Series) -> tuple[float, float, float]:
    """(OOS Sharpe, in-sample Sharpe, OOS max drawdown)."""
    oos = returns[returns.index >= OOS]
    ins = returns[returns.index < OOS]
    return sharpe(oos, rf=rf), sharpe(ins, rf=rf), max_drawdown(oos)


def main() -> None:
    base = SETTINGS
    syms = sorted(set(TSMOM_UNIVERSE) | set(TSMOM_UNIVERSE_BROAD)
                  | set(SECTOR_UNIVERSE) | {BENCHMARK, "BIL"})
    px = get_daily_closes(syms)
    rf = px["BIL"].pct_change().fillna(0.0)
    sector_px = px[SECTOR_UNIVERSE]
    rebal = rebalance_dates(px.index, FREQ)

    spy = px[BENCHMARK].pct_change().fillna(0.0)
    spy_oos, spy_is, spy_dd = _sharpe_split(spy, rf)

    print(f"Permutations of (a) broad universe, (b) short leg, (c) risk-scaled — "
          f"{FREQ} rebalance, after costs, excess over T-bills.\n")
    header = (f"{'a':>1} {'b':>1} {'c':>1} | {'TSMOM_OOS':>9} {'TSMOM_IS':>8} | "
              f"{'RHDM_OOS':>8} {'RHDM_IS':>7} {'RHDM_DD':>8}")
    print(header)
    print("-" * len(header))

    results = []
    for a, b, c in product([False, True], repeat=3):
        params = dataclasses.replace(base.params, tsmom_allow_short=b,
                                     tsmom_risk_scaled=c)
        tsmom_px = px[TSMOM_UNIVERSE_BROAD if a else TSMOM_UNIVERSE]
        w = build_target_weights(tsmom_px, sector_px, rebal, params, base.risk,
                                 apply_vol_overlay=True)
        rhdm = run_backtest(px, w["final"], base.costs, rf_returns=rf).returns
        tsmom = run_backtest(px, w["tsmom"], base.costs, rf_returns=rf).returns

        t_oos, t_is, _ = _sharpe_split(tsmom, rf)
        r_oos, r_is, r_dd = _sharpe_split(rhdm, rf)
        tag = "".join(x for x, on in zip("abc", (a, b, c)) if on) or "none"
        results.append(dict(tag=tag, a=a, b=b, c=c, t_oos=t_oos, t_is=t_is,
                            r_oos=r_oos, r_is=r_is, r_dd=r_dd))
        print(f"{int(a):>1} {int(b):>1} {int(c):>1} | {t_oos:>9.3f} {t_is:>8.3f} | "
              f"{r_oos:>8.3f} {r_is:>7.3f} {r_dd:>7.1%}")

    print(f"\nBenchmark — Buy & Hold SPY: OOS Sharpe {spy_oos:.3f}, "
          f"in-sample {spy_is:.3f}, OOS maxDD {spy_dd:.1%}")

    best_rhdm = max(results, key=lambda r: r["r_oos"])
    best_tsmom = max(results, key=lambda r: r["t_oos"])
    print("\n── Highest out-of-sample Sharpe ──")
    print(f"  Full RHDM : combo '{best_rhdm['tag']}'  OOS {best_rhdm['r_oos']:.3f} "
          f"(in-sample {best_rhdm['r_is']:.3f}, maxDD {best_rhdm['r_dd']:.1%})")
    print(f"  TSMOM sleeve : combo '{best_tsmom['tag']}'  OOS {best_tsmom['t_oos']:.3f} "
          f"(in-sample {best_tsmom['t_is']:.3f})")

    # Overfitting check: does the OOS-best combo also lead in-sample?
    is_rank = sorted(results, key=lambda r: r["r_is"], reverse=True)
    best_is_tag = is_rank[0]["tag"]
    print("\n── Overfitting check (does OOS winner generalize?) ──")
    print(f"  Best combo in-sample : '{best_is_tag}'  |  best combo OOS : '{best_rhdm['tag']}'")
    if best_is_tag == best_rhdm["tag"]:
        print("  → same combo wins both halves: more credible (still one dataset).")
    else:
        print("  → DIFFERENT combos win each half: the OOS 'winner' is largely "
              "noise; do not adopt it on this evidence alone.")


if __name__ == "__main__":
    main()
