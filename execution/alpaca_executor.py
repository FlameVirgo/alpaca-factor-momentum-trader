"""
Execution layer: reconcile the live (paper) book to a set of target weights.

The math — turning target weights + current positions into a list of orders — is
a pure function (`plan_orders`) with no Alpaca dependency, so it is fully unit
testable offline (see tests/). `AlpacaExecutor` wraps the alpaca-py TradingClient
and applies that plan against the paper account, using **notional** market orders
(ETFs are fractionable on Alpaca) so we can hit dollar targets precisely.

Safety:
- Paper endpoint is asserted unless `allow_live=True` is explicitly passed.
- A `min_trade` threshold suppresses tiny rebalancing churn.
- Positions no longer in the target are fully closed via `close_position`.
- `dry_run` returns the plan without sending anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from config import AlpacaCredentials
from data.alpaca_data import trading_client


@dataclass(frozen=True)
class OrderPlan:
    """One intended order. `notional` is always a positive dollar amount."""
    symbol: str
    side: str          # "buy" | "sell"
    notional: float
    reason: str        # "rebalance" | "close"


def plan_orders(
    target_weights: pd.Series,
    equity: float,
    positions: Dict[str, float],
    min_trade: float = 25.0,
) -> List[OrderPlan]:
    """
    Pure reconciliation: target weights + current $ positions -> order plan.

    `positions` maps symbol -> current market value in dollars. For each symbol
    in either the target or the book:
      - held but not (meaningfully) targeted  -> full close (sell entire value)
      - otherwise trade the dollar delta if it clears `min_trade`
    """
    plans: List[OrderPlan] = []
    symbols = set(target_weights.index) | set(positions)

    for sym in sorted(symbols):
        tgt_w = float(target_weights.get(sym, 0.0))
        cur = float(positions.get(sym, 0.0))

        # Full exit: we hold it but the strategy no longer wants it.
        if tgt_w <= 1e-9 and cur > 1e-9:
            plans.append(OrderPlan(sym, "sell", round(cur, 2), "close"))
            continue

        delta = equity * tgt_w - cur
        if abs(delta) < min_trade:
            continue
        side = "buy" if delta > 0 else "sell"
        plans.append(OrderPlan(sym, side, round(abs(delta), 2), "rebalance"))

    return plans


class AlpacaExecutor:
    """Thin reconciler around the Alpaca paper TradingClient."""

    def __init__(
        self,
        creds: Optional[AlpacaCredentials] = None,
        dry_run: bool = True,
        min_trade: float = 25.0,
        allow_live: bool = False,
    ):
        self.creds = creds or AlpacaCredentials.from_env()
        if not self.creds.is_paper and not allow_live:
            raise RuntimeError(
                "Refusing to execute against a non-paper endpoint. Pass "
                "allow_live=True only when you really mean it."
            )
        self.dry_run = dry_run
        self.min_trade = min_trade
        self.client = trading_client(self.creds)

    # ── account / market state ────────────────────────────────────────────
    def account_equity(self) -> float:
        return float(self.client.get_account().equity)

    def current_positions(self) -> Dict[str, float]:
        return {p.symbol: float(p.market_value) for p in self.client.get_all_positions()}

    def is_market_open(self) -> bool:
        return bool(self.client.get_clock().is_open)

    # ── reconciliation ────────────────────────────────────────────────────
    def reconcile(self, target_weights: pd.Series) -> List[OrderPlan]:
        """Compute the order plan for the current account vs `target_weights`."""
        equity = self.account_equity()
        positions = self.current_positions()
        return plan_orders(target_weights, equity, positions, self.min_trade)

    def execute(self, target_weights: pd.Series) -> List[OrderPlan]:
        """Reconcile and submit (unless dry_run). Returns the plan acted on."""
        plans = self.reconcile(target_weights)
        if self.dry_run:
            return plans
        for p in plans:
            if p.reason == "close":
                self.client.close_position(p.symbol)
            else:
                self._submit(p)
        return plans

    def flatten(self) -> None:
        """Kill switch: liquidate everything to cash, cancelling open orders."""
        if self.dry_run:
            return
        self.client.close_all_positions(cancel_orders=True)

    # ── order submission ──────────────────────────────────────────────────
    def _submit(self, plan: OrderPlan):
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        side = OrderSide.BUY if plan.side == "buy" else OrderSide.SELL
        request = MarketOrderRequest(
            symbol=plan.symbol,
            notional=plan.notional,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        return self.client.submit_order(request)
