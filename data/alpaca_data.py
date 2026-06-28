"""
Data layer: fetch historical daily bars from Alpaca for backtesting, plus a
trading-client factory for live (paper) execution.

Historical data uses StockHistoricalDataClient (works with paper keys). Bars are
returned as a tidy wide DataFrame of adjusted close prices indexed by date.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

import pandas as pd

from config import AlpacaCredentials

# alpaca-py imports are done lazily inside functions so the module can be
# imported (and unit-tested) without the dependency installed yet.


def _hist_client(creds: AlpacaCredentials):
    from alpaca.data.historical import StockHistoricalDataClient

    return StockHistoricalDataClient(creds.api_key, creds.secret_key)


def get_daily_closes(
    symbols: Iterable[str],
    start: datetime,
    end: Optional[datetime] = None,
    creds: Optional[AlpacaCredentials] = None,
) -> pd.DataFrame:
    """
    Fetch daily adjusted closing prices for `symbols` between `start` and `end`.

    Returns a wide DataFrame: index = date (UTC-naive), columns = symbols,
    values = adjusted close. Missing days are forward-filled per symbol.
    """
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import Adjustment

    creds = creds or AlpacaCredentials.from_env()
    end = end or datetime.now(timezone.utc)
    symbols = list(symbols)

    client = _hist_client(creds)
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        adjustment=Adjustment.ALL,  # split + dividend adjusted
    )
    bars = client.get_stock_bars(request)

    df = bars.df  # MultiIndex (symbol, timestamp)
    if df.empty:
        raise RuntimeError(f"No bars returned for {symbols}. Check symbols / date range / keys.")

    closes = (
        df["close"]
        .unstack(level="symbol")  # -> columns = symbols
        .sort_index()
    )
    # Normalize index to tz-naive dates for clean alignment in the backtester.
    closes.index = pd.to_datetime(closes.index).tz_localize(None).normalize()
    closes = closes.ffill()
    return closes


def trading_client(creds: Optional[AlpacaCredentials] = None):
    """Return an Alpaca TradingClient bound to the configured (paper) endpoint."""
    from alpaca.trading.client import TradingClient

    creds = creds or AlpacaCredentials.from_env()
    return TradingClient(creds.api_key, creds.secret_key, paper=creds.is_paper)
