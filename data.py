from __future__ import annotations

import os
from typing import Optional

import pandas as pd
import yfinance as yf

from config import CROSS_ASSETS, NEWS_SENTIMENT_CSV, REDDIT_SENTIMENT_CSV, START


def _read_daily_sentiment_csv(path: str, ticker: str) -> Optional[pd.DataFrame]:
    if not os.path.isfile(path):
        return None
    try:
        raw = pd.read_csv(path)
    except Exception:
        return None
    if raw.empty or "ticker" not in raw.columns:
        return None
    raw = raw[raw["ticker"].astype(str).str.upper() == ticker.upper()]
    if raw.empty:
        return None
    ts = pd.to_datetime(raw["timestamp"], errors="coerce")
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert(None)
    raw = raw.assign(_d=ts.dt.normalize())
    agg_cols = [c for c in raw.columns if c not in ("timestamp", "ticker", "_d")]
    if not agg_cols:
        return None
    daily = raw.groupby("_d", as_index=True)[agg_cols].mean(numeric_only=True)
    daily.index.name = "date"
    return daily


def merge_sentiment_csvs(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """
    Merge optional Finnhub/Reddit CSV dumps onto `df`'s index (forward-filled daily).
    """
    out = df.copy()
    idx = pd.DatetimeIndex(pd.to_datetime(out.index).normalize())

    def _inject(block: Optional[pd.DataFrame]) -> None:
        if block is None:
            return
        block = block.sort_index()
        for col in block.columns:
            ser = block[col]
            ser.index = pd.DatetimeIndex(pd.to_datetime(ser.index).normalize())
            out[col] = ser.reindex(idx).ffill().values

    _inject(_read_daily_sentiment_csv(NEWS_SENTIMENT_CSV, ticker))
    _inject(_read_daily_sentiment_csv(REDDIT_SENTIMENT_CSV, ticker))

    if "news_sentiment_mean" not in out.columns:
        out["news_sentiment_mean"] = 0.0
    if "news_volume" not in out.columns:
        out["news_volume"] = 1.0
    if "reddit_sentiment_mean" not in out.columns:
        out["reddit_sentiment_mean"] = 0.0
    if "reddit_mentions" not in out.columns:
        out["reddit_mentions"] = 0.0

    return out


def load_data(ticker: str | None = None, merge_sentiment: bool = True) -> pd.DataFrame:
    """
    OHLCV for one equity plus cross-asset columns used in features.
    """
    from config import TICKER as DEFAULT_TICKER

    sym = (ticker or DEFAULT_TICKER).strip().upper()
    df = yf.download(sym, start=START, progress=False, auto_adjust=True)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    else:
        df.columns = [str(c) for c in df.columns]

    for name, cross_sym in CROSS_ASSETS.items():
        cross = yf.download(cross_sym, start=START, progress=False, auto_adjust=True)
        if isinstance(cross.columns, pd.MultiIndex):
            cross.columns = [c[0] if isinstance(c, tuple) else c for c in cross.columns]
        close_col = "Adj Close" if "Adj Close" in cross.columns else "Close"
        df[name] = cross[close_col]

    df = df.dropna(how="any")

    if merge_sentiment:
        df = merge_sentiment_csvs(df, sym)

    return df
