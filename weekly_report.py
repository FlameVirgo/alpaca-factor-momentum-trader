#!/usr/bin/env python3
"""
Weekly results email — reads the Alpaca paper account and sends a clean HTML
summary: equity & weekly P&L, current positions, the week's fills, and how the
account did vs buy-and-hold SPY over the same week.

Subject: "Alpaca API: Week DD/MM/YYYY to DD/MM/YYYY Results"

Sends to REPORT_TO (your real inbox) — falls back to SMTP_USER. Designed to be
run by a weekly GitHub Action (Saturday). Read-only: places no orders.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from config import AlpacaCredentials, BENCHMARK
from data.alpaca_data import trading_client, get_daily_closes
from execution import notify


def _portfolio_week(tc, equity_now: float):
    """(start-of-week equity, P&L $, P&L %) via Alpaca portfolio history."""
    try:
        from alpaca.trading.requests import GetPortfolioHistoryRequest
        ph = tc.get_portfolio_history(
            GetPortfolioHistoryRequest(period="1W", timeframe="1D"))
        eq = [e for e in (ph.equity or []) if e]
        if len(eq) >= 2:
            start = eq[0]
            return start, equity_now - start, (equity_now / start - 1.0) if start else 0.0
    except Exception:
        pass
    return None, None, None


def _week_orders(tc, after: datetime):
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    orders = tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED,
                                            after=after, limit=500))
    return [o for o in orders if str(o.status).endswith("FILLED")]


def _spy_week_return(creds, start: datetime) -> float | None:
    try:
        px = get_daily_closes([BENCHMARK], start=start - timedelta(days=10), creds=creds)
        s = px[BENCHMARK].dropna()
        wk = s[s.index >= start.replace(tzinfo=None)]
        ref = wk.iloc[0] if len(wk) else s.iloc[0]
        return float(s.iloc[-1] / ref - 1.0)
    except Exception:
        return None


def _fmt_pct(x):
    return "n/a" if x is None else f"{x:+.2%}"


def _fmt_usd(x):
    return "n/a" if x is None else f"${x:,.2f}"


def build_report():
    creds = AlpacaCredentials.from_env()
    tc = trading_client(creds)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)

    acct = tc.get_account()
    equity = float(acct.equity)
    cash = float(acct.cash)
    wk_start_eq, wk_pl, wk_pl_pct = _portfolio_week(tc, equity)
    positions = tc.get_all_positions()
    orders = _week_orders(tc, start)
    spy_ret = _spy_week_return(creds, start)

    period = f"{start:%d/%m/%Y} to {end:%d/%m/%Y}"
    subject = f"Alpaca API: Week {period} Results"

    # ── HTML ────────────────────────────────────────────────────────────────
    green, red, gray = "#0a7d28", "#b00020", "#555"
    pl_color = green if (wk_pl or 0) >= 0 else red

    pos_rows = "".join(
        f"<tr><td>{p.symbol}</td><td align='right'>{float(p.qty):,.4f}</td>"
        f"<td align='right'>{_fmt_usd(float(p.market_value))}</td>"
        f"<td align='right' style='color:{green if float(p.unrealized_pl)>=0 else red}'>"
        f"{_fmt_usd(float(p.unrealized_pl))} ({float(p.unrealized_plpc):+.2%})</td></tr>"
        for p in sorted(positions, key=lambda x: -float(x.market_value))
    ) or "<tr><td colspan='4' style='color:#888'>No open positions.</td></tr>"

    ord_rows = "".join(
        f"<tr><td>{o.symbol}</td><td>{o.side.value.upper()}</td>"
        f"<td align='right'>{_fmt_usd(float(o.filled_avg_price)) if o.filled_avg_price else '—'}</td>"
        f"<td align='right'>{float(o.filled_qty):,.4f}</td>"
        f"<td style='color:{gray}'>{o.filled_at:%d/%m %H:%M}</td></tr>"
        for o in sorted(orders, key=lambda x: x.filled_at or end)
    ) or "<tr><td colspan='5' style='color:#888'>No trades this week.</td></tr>"

    vs_spy = ""
    if wk_pl_pct is not None and spy_ret is not None:
        diff = wk_pl_pct - spy_ret
        vs_spy = (f"<p>Vs buy-and-hold SPY this week: portfolio {_fmt_pct(wk_pl_pct)} "
                  f"vs SPY {_fmt_pct(spy_ret)} → <b style='color:{green if diff>=0 else red}'>"
                  f"{diff:+.2%}</b></p>")

    html = f"""\
<html><body style="font-family:-apple-system,Segoe UI,Arial,sans-serif;color:#222;max-width:620px">
  <h2 style="margin-bottom:0">Alpaca Paper Trading — Weekly Results</h2>
  <p style="color:{gray};margin-top:4px">Week {period} · core-satellite strategy</p>

  <table style="border-collapse:collapse;width:100%;margin:8px 0">
    <tr><td>Account equity</td><td align="right"><b>{_fmt_usd(equity)}</b></td></tr>
    <tr><td>Cash</td><td align="right">{_fmt_usd(cash)}</td></tr>
    <tr><td>Start-of-week equity</td><td align="right">{_fmt_usd(wk_start_eq)}</td></tr>
    <tr><td>Weekly P&amp;L</td><td align="right" style="color:{pl_color}"><b>{_fmt_usd(wk_pl)} ({_fmt_pct(wk_pl_pct)})</b></td></tr>
  </table>
  {vs_spy}

  <h3>Positions ({len(positions)})</h3>
  <table style="border-collapse:collapse;width:100%" border="0" cellpadding="6">
    <tr style="background:#f2f2f2"><th align="left">Symbol</th><th align="right">Qty</th>
        <th align="right">Mkt Value</th><th align="right">Unrealized P&amp;L</th></tr>
    {pos_rows}
  </table>

  <h3>Trades this week ({len(orders)})</h3>
  <table style="border-collapse:collapse;width:100%" border="0" cellpadding="6">
    <tr style="background:#f2f2f2"><th align="left">Symbol</th><th align="left">Side</th>
        <th align="right">Fill Px</th><th align="right">Qty</th><th align="left">When</th></tr>
    {ord_rows}
  </table>

  <p style="color:{gray};font-size:12px;margin-top:18px">Paper trading (simulated). Automated report from your Alpaca trading bot.</p>
</body></html>"""

    text = (f"Alpaca weekly results, {period}\n"
            f"Equity {_fmt_usd(equity)}, weekly P&L {_fmt_usd(wk_pl)} ({_fmt_pct(wk_pl_pct)})\n"
            f"Positions: {len(positions)}, trades this week: {len(orders)}\n"
            f"(HTML email for the full breakdown.)")
    return subject, text, html


def main() -> None:
    subject, text, html = build_report()
    to = os.getenv("REPORT_TO") or os.getenv("SMTP_USER")
    sent = notify.send(subject, text, to=to, html=html)
    print(f"Weekly report {'sent to ' + (to or '?') if sent else 'NOT sent (SMTP unconfigured)'}")


if __name__ == "__main__":
    main()
