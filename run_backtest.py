#!/usr/bin/env python3
"""
RHDM backtest driver — pulls historical ETF data, builds monthly target weights
for every sleeve and the full portfolio, runs the cost-aware backtester, and
prints a full performance summary with an in-sample / out-of-sample split.

Usage:
    python run_backtest.py                 # 15y, default OOS split at 2019-01-01
    python run_backtest.py --refresh       # re-pull data from source
    python run_backtest.py --oos 2020-01-01

Data comes from the free Yahoo loader (data/market_data.py) so it runs with no
Alpaca keys. This is research/validation; live trading uses Alpaca data + the
paper endpoint (see PLAN.md Phase 2).
"""
from __future__ import annotations

import argparse

import pandas as pd

from config import SETTINGS, TSMOM_UNIVERSE, SECTOR_UNIVERSE, BENCHMARK
from data.market_data import get_daily_closes
from portfolio.allocator import build_target_weights
from backtest.engine import run_backtest, buy_and_hold, rebalance_dates
from backtest.metrics import summary, format_summary


RF_SYMBOL = "BIL"  # SPDR 1-3 month T-bill ETF: the tradeable cash proxy


def _bh_sixty_forty(prices: pd.DataFrame) -> pd.Series:
    """Classic 60/40 SPY/TLT daily returns, monthly rebalanced (benchmark #2)."""
    rets = prices[["SPY", "TLT"]].pct_change().fillna(0.0)
    return 0.6 * rets["SPY"] + 0.4 * rets["TLT"]


def run(refresh: bool, oos_start: str, freq: str = "weekly") -> None:
    params, risk, costs = SETTINGS.params, SETTINGS.risk, SETTINGS.costs
    symbols = sorted(set(TSMOM_UNIVERSE) | set(SECTOR_UNIVERSE) | {BENCHMARK, RF_SYMBOL})

    print(f"Loading {len(symbols)} symbols (cached unless --refresh)...")
    prices = get_daily_closes(symbols, range_="15y", refresh=refresh)
    print(f"  {prices.index[0].date()} → {prices.index[-1].date()}  "
          f"({len(prices)} trading days)")
    print(f"  Rebalance frequency: {freq}")

    # Real, time-varying risk-free: the daily total return of holding BIL. Cash
    # in the strategies earns this, and Sharpe/Sortino measure excess over it.
    rf = prices[RF_SYMBOL].pct_change().fillna(0.0)
    rf_ann = (1.0 + rf).prod() ** (252.0 / len(rf)) - 1.0
    print(f"  Risk-free proxy: {RF_SYMBOL}, ~{rf_ann:.2%}/yr avg over the sample\n")

    tsmom_prices = prices[TSMOM_UNIVERSE]
    sector_prices = prices[SECTOR_UNIVERSE]
    rebal = rebalance_dates(prices.index, freq)

    weights = build_target_weights(
        tsmom_prices, sector_prices, rebal, params, risk, apply_vol_overlay=True
    )
    blended_only = build_target_weights(
        tsmom_prices, sector_prices, rebal, params, risk, apply_vol_overlay=False
    )

    # Run the strategies through the engine (execution lag + cash earns rf);
    # keep the full results so we can report turnover (the cost story).
    results = {
        "RHDM (full: blend + vol overlay)": run_backtest(prices, weights["final"], costs, rf_returns=rf),
        "Blended (no vol overlay)": run_backtest(prices, blended_only["final"], costs, rf_returns=rf),
        "Sleeve A — TSMOM only": run_backtest(prices, weights["tsmom"], costs, rf_returns=rf),
        "Sleeve B — Sector rotation only": run_backtest(prices, weights["xsec"], costs, rf_returns=rf),
    }
    years = len(prices) / 252.0
    print("Annualized one-way turnover (drives cost; rises with frequency):")
    for name, r in results.items():
        print(f"  {name:34} {r.turnover.sum() / years:6.1f}x/yr")
    print()

    # Benchmarks are fully invested → no cash leg, computed directly.
    series: dict[str, pd.Series] = {name: r.returns for name, r in results.items()}
    series["Benchmark — Buy & Hold SPY"] = buy_and_hold(prices, BENCHMARK)
    series["Benchmark — 60/40 SPY/TLT"] = _bh_sixty_forty(prices)

    def report(label: str, window: tuple[str, str] | None) -> None:
        print("=" * 60)
        print(label)
        print("=" * 60)
        rows = []
        for name, ret in series.items():
            r = ret
            if window:
                r = r.loc[(r.index >= window[0]) & (r.index <= window[1])]
            s = summary(r, name=name, rf=rf)
            rows.append(s)
            print(format_summary(s))
            print()
        # Compact comparison table.
        table = pd.DataFrame(rows).set_index("name")[
            ["ann_return", "ann_vol", "sharpe", "sortino", "max_drawdown", "calmar"]
        ]
        with pd.option_context("display.float_format", lambda x: f"{x:0.3f}"):
            print(table.to_string())
        print()

    full_start = str(prices.index[0].date())
    full_end = str(prices.index[-1].date())
    report(f"FULL SAMPLE  {full_start} → {full_end}", None)
    report(f"IN-SAMPLE   {full_start} → {oos_start}", (full_start, oos_start))
    report(f"OUT-OF-SAMPLE  {oos_start} → {full_end}", (oos_start, full_end))

    # Hypothesis checks (PLAN.md §2A) on the out-of-sample window.
    oos = lambda n: summary(
        series[n].loc[series[n].index >= oos_start], name=n, rf=rf
    )
    rhdm = oos("RHDM (full: blend + vol overlay)")
    tsmom = oos("Sleeve A — TSMOM only")
    sector = oos("Sleeve B — Sector rotation only")
    spy = oos("Benchmark — Buy & Hold SPY")
    print("=" * 60)
    print(f"FALSIFIABLE HYPOTHESES (out-of-sample {oos_start}+)")
    print("=" * 60)
    h1 = rhdm["sharpe"] > max(tsmom["sharpe"], sector["sharpe"])
    h2 = abs(rhdm["max_drawdown"]) < abs(spy["max_drawdown"])
    h3 = rhdm["sharpe"] > spy["sharpe"]
    print(f"  H1  RHDM Sharpe > best single sleeve   : "
          f"{rhdm['sharpe']:.2f} vs {max(tsmom['sharpe'], sector['sharpe']):.2f}"
          f"   {'PASS' if h1 else 'FAIL'}")
    print(f"  H2  RHDM maxDD < SPY maxDD              : "
          f"{rhdm['max_drawdown']:.1%} vs {spy['max_drawdown']:.1%}"
          f"   {'PASS' if h2 else 'FAIL'}")
    print(f"  H3  RHDM Sharpe > Buy&Hold SPY Sharpe   : "
          f"{rhdm['sharpe']:.2f} vs {spy['sharpe']:.2f}"
          f"   {'PASS' if h3 else 'FAIL'}")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description="RHDM backtest")
    ap.add_argument("--refresh", action="store_true", help="re-pull data from source")
    ap.add_argument("--oos", default="2019-01-01", help="out-of-sample start date")
    ap.add_argument("--rebalance", default="weekly",
                    choices=["monthly", "weekly", "daily"],
                    help="rebalance frequency (default weekly, matches run_live.py)")
    args = ap.parse_args()
    run(refresh=args.refresh, oos_start=args.oos, freq=args.rebalance)


if __name__ == "__main__":
    main()
