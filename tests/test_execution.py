"""
Offline unit tests for the live execution logic that does NOT need Alpaca:
order reconciliation (plan_orders) and the drawdown kill-switch (RiskMonitor).

Run with `pytest` or directly: `python tests/test_execution.py`.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from execution.alpaca_executor import plan_orders, OrderPlan
from execution.risk_monitor import RiskMonitor


def _by_symbol(plans):
    return {p.symbol: p for p in plans}


def test_buy_to_reach_target_from_empty():
    plans = _by_symbol(plan_orders(pd.Series({"SPY": 0.5}), 100_000, {}))
    assert plans["SPY"] == OrderPlan("SPY", "buy", 50_000.0, "rebalance")


def test_full_close_of_dropped_name():
    # Hold XLE but it's no longer in the target → full close for its market value.
    plans = _by_symbol(plan_orders(pd.Series({"SPY": 1.0}), 100_000,
                                   {"SPY": 100_000.0, "XLE": 7_500.0}))
    assert plans["XLE"] == OrderPlan("XLE", "sell", 7_500.0, "close")
    assert "SPY" not in plans  # already at target → no order


def test_min_trade_suppresses_churn():
    # Target wants $50,010 of SPY, we hold $50,000 → $10 delta < $25 min_trade.
    plans = plan_orders(pd.Series({"SPY": 0.5001}), 100_000, {"SPY": 50_000.0},
                        min_trade=25.0)
    assert plans == []


def test_sell_to_reduce_overweight():
    plans = _by_symbol(plan_orders(pd.Series({"SPY": 0.3}), 100_000, {"SPY": 50_000.0}))
    assert plans["SPY"].side == "sell"
    assert plans["SPY"].notional == 20_000.0


def test_killswitch_tracks_hwm_and_trips():
    state = Path(tempfile.mkdtemp()) / "state.json"
    rm = RiskMonitor(max_drawdown=0.20, state_path=state)
    assert not rm.update(100_000).breached
    assert rm.update(110_000).high_water_mark == 110_000      # new peak
    assert not rm.update(95_000).breached                     # -13.6%, ok
    assert rm.update(80_000).breached                         # -27%, trip

    # HWM persists across a fresh monitor instance (restart safety).
    rm2 = RiskMonitor(max_drawdown=0.20, state_path=state)
    assert rm2.update(90_000).high_water_mark == 110_000


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  PASS  {t.__name__}")
    print(f"\n{len(tests)} passed.")


if __name__ == "__main__":
    _run_all()
