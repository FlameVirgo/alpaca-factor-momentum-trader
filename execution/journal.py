"""
Structured journaling for the live system.

Everything the live loop does — signals, planned orders, equity snapshots,
kill-switch events — is appended to durable files under logs/ so that paper
performance can later be reconciled against the backtest (PLAN.md Phase 2:
"divergence = bug or overfit, caught with fake money"). Pure stdlib; no deps.

Files:
  logs/journal.jsonl  — one JSON object per event (signals, orders, alerts)
  logs/equity.csv     — daily equity / drawdown snapshots
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
JOURNAL = LOG_DIR / "journal.jsonl"
EQUITY_CSV = LOG_DIR / "equity.csv"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_logger(name: str = "rhdm") -> logging.Logger:
    """Console logger with a consistent format (configured once)."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s",
                                         datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
    return logger


def log_event(kind: str, **fields) -> None:
    """Append a structured event to logs/journal.jsonl."""
    LOG_DIR.mkdir(exist_ok=True)
    record = {"ts": _now(), "kind": kind, **fields}
    with JOURNAL.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def log_orders(plans: Iterable, *, dry_run: bool) -> None:
    """Journal an order plan (list of OrderPlan)."""
    orders = [
        {"symbol": p.symbol, "side": p.side, "notional": p.notional, "reason": p.reason}
        for p in plans
    ]
    log_event("orders", dry_run=dry_run, count=len(orders), orders=orders)


def snapshot_equity(equity: float, high_water_mark: float, drawdown: float) -> None:
    """Append a daily equity snapshot to logs/equity.csv (creating header once)."""
    LOG_DIR.mkdir(exist_ok=True)
    new = not EQUITY_CSV.exists()
    with EQUITY_CSV.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "equity", "high_water_mark", "drawdown"])
        w.writerow([_now(), f"{equity:.2f}", f"{high_water_mark:.2f}", f"{drawdown:.4f}"])
