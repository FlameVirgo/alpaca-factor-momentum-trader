"""
Free, no-API-key historical data loader for *backtesting only*.

Alpaca's historical bars (see alpaca_data.py) require keys and are the source of
record for live/paper trading. For the research backtest we want to iterate
before any keys exist, so this module pulls split/dividend-adjusted daily closes
from the public Yahoo Finance chart endpoint and caches them to CSV under
data/cache/. Subsequent runs are fully offline.

Live trading never touches this module — it is a research convenience only.
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

CACHE_DIR = Path(__file__).parent / "cache"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_CTX = ssl.create_default_context()


def _fetch_one(symbol: str, range_: str = "15y") -> pd.Series:
    """Pull adjusted daily closes for one symbol from Yahoo's chart endpoint."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?range={range_}&interval=1d&events=div%2Csplit"
    )
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    raw = urllib.request.urlopen(req, timeout=30, context=_CTX).read()
    result = json.loads(raw)["chart"]["result"][0]
    ts = result["timestamp"]
    adj = result["indicators"]["adjclose"][0]["adjclose"]
    idx = pd.to_datetime([datetime.fromtimestamp(t, tz=timezone.utc) for t in ts])
    idx = idx.tz_localize(None).normalize()
    return pd.Series(adj, index=idx, name=symbol).dropna()


def get_daily_closes(
    symbols: Iterable[str],
    start: Optional[str] = None,
    end: Optional[str] = None,
    range_: str = "15y",
    use_cache: bool = True,
    refresh: bool = False,
) -> pd.DataFrame:
    """
    Wide DataFrame of adjusted daily closes (index=date, cols=symbols).

    Caches each symbol to data/cache/<symbol>.csv. Pass refresh=True to re-pull.
    `start`/`end` are optional 'YYYY-MM-DD' slices applied after loading.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    series = {}
    for sym in symbols:
        cache = CACHE_DIR / f"{sym}.csv"
        if use_cache and not refresh and cache.exists():
            s = pd.read_csv(cache, index_col=0, parse_dates=True).iloc[:, 0]
            s.name = sym
        else:
            s = _fetch_one(sym, range_=range_)
            s.to_frame().to_csv(cache)
            time.sleep(0.4)  # be polite to the public endpoint
        series[sym] = s

    df = pd.DataFrame(series).sort_index().ffill()
    if start:
        df = df.loc[df.index >= pd.Timestamp(start)]
    if end:
        df = df.loc[df.index <= pd.Timestamp(end)]
    return df.dropna(how="all")
