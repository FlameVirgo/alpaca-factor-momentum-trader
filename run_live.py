#!/usr/bin/env python3
"""
Live (paper) orchestrator — PLAN.md Phase 2.

Designed to be run once per trading day by a scheduler (cron / GitHub Action).
Each run:

  1. reads account equity from the Alpaca paper endpoint;
  2. updates the drawdown kill-switch — if tripped, flattens to cash and stops;
  3. on the chosen cadence (default **every 2 days**), recomputes the deployed
     core-satellite target weights and reconciles the book; other days it just
     monitors the kill-switch.

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
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from config import SETTINGS, TSMOM_UNIVERSE, SECTOR_UNIVERSE, BENCHMARK, AlpacaCredentials
from data.alpaca_data import get_daily_closes
from portfolio.target import latest_target_weights
from execution.alpaca_executor import AlpacaExecutor
from execution.risk_monitor import RiskMonitor
from execution import journal, notify

REBALANCE_STATE = Path(__file__).resolve().parent / "logs" / "last_rebalance.json"
REPO_ROOT = Path(__file__).resolve().parent

# GitHub pauses a scheduled workflow after 60 days of zero repo activity. Warn ~1
# week before that so the bot doesn't silently stop — a single push resets it.
INACTIVITY_WARN_DAYS = 53
INACTIVITY_PAUSE_DAYS = 60


def _days_since_last_commit() -> "int | None":
    """Days since the last commit (proxy for GitHub repo activity)."""
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cI"], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=10)
        if out.returncode != 0 or not out.stdout.strip():
            return None
        committed = datetime.fromisoformat(out.stdout.strip())
        return (datetime.now(timezone.utc) - committed).days
    except Exception:
        return None


def _check_inactivity_warning(live: bool, log) -> None:
    """Text a heads-up ~1 week before GitHub would pause the scheduled workflow."""
    days = _days_since_last_commit()
    if days is None:
        return
    if INACTIVITY_WARN_DAYS <= days < INACTIVITY_PAUSE_DAYS:
        left = INACTIVITY_PAUSE_DAYS - days
        log.warning("Repo inactive %d days — GitHub pauses the schedule in %d.", days, left)
        if live:
            notify.send(
                "Trading bot: action needed soon",
                f"Heads up: GitHub will PAUSE your trading bot's schedule in ~{left} "
                f"day(s) (repo inactive {days}d). Push any commit to the repo to keep "
                "it running.")


def _last_rebalance_date() -> "date | None":
    if REBALANCE_STATE.exists():
        try:
            return date.fromisoformat(json.loads(REBALANCE_STATE.read_text())["date"])
        except (json.JSONDecodeError, KeyError, ValueError):
            return None
    return None


def _record_rebalance_date(d: "date") -> None:
    REBALANCE_STATE.parent.mkdir(exist_ok=True)
    REBALANCE_STATE.write_text(json.dumps({"date": d.isoformat()}))


def _should_rebalance(freq: str, force: bool, monitor_only: bool) -> bool:
    """
    Rebalance cadence. `freq` is "monthly", "weekly", "daily", or an N-day spec
    like "2d". Tracks the last rebalance date so a daily-scheduled run only
    rebalances on the chosen cadence.
    """
    if monitor_only:
        return False
    if force:
        return True
    last = _last_rebalance_date()
    if last is None:
        return True
    today = datetime.now(timezone.utc).date()
    if freq == "monthly":
        return (today.year, today.month) != (last.year, last.month)
    if freq == "weekly":
        return today.isocalendar()[:2] != last.isocalendar()[:2]
    n = 1 if freq == "daily" else int(freq.rstrip("d"))   # "2d" → every 2 days
    return (today - last).days >= n


def run(live: bool, force_rebalance: bool, monitor_only: bool,
        lookback_days: int, apply_vol_overlay: bool, freq: str = "2d") -> None:
    log = journal.get_logger()
    settings = SETTINGS
    creds = AlpacaCredentials.from_env()
    log.info("Endpoint: %s (paper=%s)  rebalance=%s", creds.base_url, creds.is_paper, freq)

    executor = AlpacaExecutor(creds=creds, dry_run=not live, min_trade=25.0)

    # 0. maintenance: warn before GitHub pauses the schedule ------------------
    _check_inactivity_warning(live, log)

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
        if live:
            notify.notify_killswitch(equity, status.drawdown)
        return

    # 2. decide whether to rebalance -----------------------------------------
    if not _should_rebalance(freq, force_rebalance, monitor_only):
        log.info("No rebalance due (cadence=%s, last rebalanced: %s). Monitoring only.",
                 freq, _last_rebalance_date() or "never")
        return

    # 3. compute target weights ----------------------------------------------
    # SPY (the core-satellite equity core) is pulled via BENCHMARK.
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
        _record_rebalance_date(datetime.now(timezone.utc).date())
        if plans:
            notify.notify_trades(plans, equity)
        log.info("Rebalance submitted to paper account.")
    else:
        log.info("Dry-run complete — pass --live to submit. State not advanced.")


def main() -> None:
    ap = argparse.ArgumentParser(description="RHDM live (paper) orchestrator")
    ap.add_argument("--live", action="store_true", help="actually submit orders (paper)")
    ap.add_argument("--rebalance", action="store_true", help="force a rebalance now")
    ap.add_argument("--monitor-only", action="store_true", help="kill-switch check only")
    ap.add_argument("--lookback-days", type=int, default=500, help="history window to pull")
    ap.add_argument("--vol-overlay", action="store_true",
                    help="enable the vol overlay (off by default — it hurt OOS, PLAN §2D)")
    ap.add_argument("--frequency", default="2d",
                    help="rebalance cadence: monthly|weekly|daily or N-day (e.g. 2d); default 2d")
    args = ap.parse_args()
    run(live=args.live, force_rebalance=args.rebalance, monitor_only=args.monitor_only,
        lookback_days=args.lookback_days, apply_vol_overlay=args.vol_overlay,
        freq=args.frequency)


if __name__ == "__main__":
    main()
