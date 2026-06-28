#!/usr/bin/env python3
"""
Live (paper) orchestrator — PLAN.md Phase 2.

Designed to be run once per trading day by a scheduler (cron / GitHub Action).
Each run:

  1. reads account equity from the Alpaca paper endpoint;
  2. updates the drawdown kill-switch — if tripped, flattens to cash and stops;
  3. on the first trading day of a new month, recomputes RHDM target weights and
     reconciles the book toward them; other days it just monitors.

Everything is journaled to logs/. **Dry-run by default** — it prints the planned
orders without sending them. Pass --live to actually submit (paper only).

    python run_live.py                 # monitor + show plan, send nothing
    python run_live.py --rebalance     # force a rebalance now (still dry-run)
    python run_live.py --live          # really trade the paper account

Note: per the backtest (PLAN.md §2D) RHDM is not yet validated; this is the
deployment plumbing, intentionally gated behind --live.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import SETTINGS, TSMOM_UNIVERSE, SECTOR_UNIVERSE, BENCHMARK, AlpacaCredentials
from data.alpaca_data import get_daily_closes
from portfolio.target import latest_target_weights
from execution.alpaca_executor import AlpacaExecutor
from execution.risk_monitor import RiskMonitor
from execution import journal

REBALANCE_STATE = Path(__file__).resolve().parent / "logs" / "last_rebalance.json"


def _last_rebalance_month() -> str | None:
    if REBALANCE_STATE.exists():
        try:
            return json.loads(REBALANCE_STATE.read_text()).get("month")
        except json.JSONDecodeError:
            return None
    return None


def _record_rebalance_month(month: str) -> None:
    REBALANCE_STATE.parent.mkdir(exist_ok=True)
    REBALANCE_STATE.write_text(json.dumps({"month": month}))


def _should_rebalance(today_month: str, force: bool, monitor_only: bool) -> bool:
    if monitor_only:
        return False
    if force:
        return True
    # First run of a new calendar month → rebalance (uses latest month-end data).
    return _last_rebalance_month() != today_month


def run(live: bool, force_rebalance: bool, monitor_only: bool,
        lookback_days: int, apply_vol_overlay: bool) -> None:
    log = journal.get_logger()
    settings = SETTINGS
    creds = AlpacaCredentials.from_env()
    log.info("Endpoint: %s (paper=%s)", creds.base_url, creds.is_paper)

    executor = AlpacaExecutor(creds=creds, dry_run=not live, min_trade=25.0)

    # 1. equity + kill-switch -------------------------------------------------
    equity = executor.account_equity()
    monitor = RiskMonitor(settings.risk.max_drawdown_killswitch)
    status = monitor.update(equity)
    journal.snapshot_equity(equity, status.high_water_mark, status.drawdown)
    log.info("Equity $%.2f  HWM $%.2f  drawdown %.2f%%",
             equity, status.high_water_mark, status.drawdown * 100)

    if status.breached:
        log.critical("KILL SWITCH: drawdown %.2f%% breached limit %.0f%% — flattening to cash",
                     status.drawdown * 100, settings.risk.max_drawdown_killswitch * 100)
        journal.log_event("killswitch", equity=equity, drawdown=status.drawdown,
                          dry_run=not live)
        executor.flatten()
        return

    # 2. decide whether to rebalance -----------------------------------------
    today_month = datetime.now(timezone.utc).strftime("%Y-%m")
    if not _should_rebalance(today_month, force_rebalance, monitor_only):
        log.info("No rebalance today (last rebalanced: %s). Monitoring only.",
                 _last_rebalance_month() or "never")
        return

    # 3. compute target weights ----------------------------------------------
    symbols = sorted(set(TSMOM_UNIVERSE) | set(SECTOR_UNIVERSE) | {BENCHMARK})
    start = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    log.info("Pulling %d-day history for %d symbols...", lookback_days, len(symbols))
    prices = get_daily_closes(symbols, start=start, creds=creds)

    weights = latest_target_weights(prices, settings.params, settings.risk,
                                    apply_vol_overlay=apply_vol_overlay)
    log.info("Target weights (as of %s):\n%s",
             prices.index[-1].date(), weights.round(4).to_string())
    journal.log_event("signal", as_of=str(prices.index[-1].date()),
                      weights={k: round(float(v), 4) for k, v in weights.items()},
                      invested=round(float(weights.sum()), 4))

    # 4. reconcile + (maybe) trade -------------------------------------------
    plans = executor.execute(weights)
    journal.log_orders(plans, dry_run=not live)
    if not plans:
        log.info("Book already at target — no orders.")
    for p in plans:
        log.info("%s %-5s $%.2f (%s)%s", p.side.upper(), p.symbol, p.notional,
                 p.reason, "" if live else "  [DRY-RUN]")

    if live:
        _record_rebalance_month(today_month)
        log.info("Rebalance submitted to paper account.")
    else:
        log.info("Dry-run complete — pass --live to submit. State not advanced.")


def main() -> None:
    ap = argparse.ArgumentParser(description="RHDM live (paper) orchestrator")
    ap.add_argument("--live", action="store_true", help="actually submit orders (paper)")
    ap.add_argument("--rebalance", action="store_true", help="force a rebalance now")
    ap.add_argument("--monitor-only", action="store_true", help="kill-switch check only")
    ap.add_argument("--lookback-days", type=int, default=500, help="history window to pull")
    ap.add_argument("--no-vol-overlay", action="store_true", help="disable vol overlay")
    args = ap.parse_args()
    run(live=args.live, force_rebalance=args.rebalance, monitor_only=args.monitor_only,
        lookback_days=args.lookback_days, apply_vol_overlay=not args.no_vol_overlay)


if __name__ == "__main__":
    main()
