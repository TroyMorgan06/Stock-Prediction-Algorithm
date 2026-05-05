from __future__ import annotations

import os
import time
from typing import Optional

import pandas as pd
import yfinance as yf

from config import CROSS_ASSETS, NEWS_SENTIMENT_CSV, REDDIT_SENTIMENT_CSV, START


def _drop_yf_noise_cols(df: pd.DataFrame) -> pd.DataFrame:
    noise = ("Repaired?", "Dividends", "Stock Splits", "Capital Gains")
    drop = [c for c in noise if c in df.columns]
    if drop:
        df = df.drop(columns=drop)
    return df


def _strip_tz_index(df: pd.DataFrame) -> pd.DataFrame:
    """Daily OHLC: force naive DatetimeIndex (avoids merge/feature bugs across tz-aware/naive)."""
    if df is None or df.empty:
        return df
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(idx)
        idx = df.index
    if getattr(idx, "tz", None) is not None:
        df = df.copy()
        df.index = pd.to_datetime(idx.strftime("%Y-%m-%d"))
    return df


def _fetch_daily(symbol: str, start: str, retries: int = 3, sleep_s: float = 1.5) -> pd.DataFrame:
    """
    Yahoo data: prefer Ticker.history() — yf.download() often hits
    'No timezone found, symbol may be delisted' when Yahoo's tz metadata fails.
    """
    symbol = symbol.strip()
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        # 1) Primary: history (more reliable for tz)
        try:
            t = yf.Ticker(symbol)
            try:
                df = t.history(
                    start=start,
                    auto_adjust=True,
                    actions=False,
                    repair=True,
                )
            except TypeError:
                df = t.history(
                    start=start,
                    auto_adjust=True,
                    actions=False,
                )
            df = _strip_tz_index(df)
            df = _drop_yf_noise_cols(df)
            if df is not None and not df.empty and "Close" in df.columns:
                return df
        except Exception as e:
            last_err = e

        # 2) Fallback: download
        try:
            df = yf.download(
                symbol,
                start=start,
                progress=False,
                auto_adjust=True,
                threads=False,
            )
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            else:
                df.columns = [str(c) for c in df.columns]
            df = _strip_tz_index(df)
            df = _drop_yf_noise_cols(df)
            if df is not None and not df.empty and "Close" in df.columns:
                return df
        except Exception as e:
            last_err = e

        if attempt < retries - 1:
            time.sleep(sleep_s * (attempt + 1))

    msg = f"{symbol}: failed after {retries} tries"
    if last_err:
        msg += f": {last_err}"
    raise RuntimeError(msg)


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


def load_data(ticker: Optional[str] = None, merge_sentiment: bool = True) -> pd.DataFrame:
    """
    OHLCV for one equity plus cross-asset columns used in features.
    """
    from config import TICKER as DEFAULT_TICKER

    sym = (ticker or DEFAULT_TICKER).strip().upper()
    df = _fetch_daily(sym, START)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    else:
        df.columns = [str(c) for c in df.columns]

    for name, cross_sym in CROSS_ASSETS.items():
        cross = _fetch_daily(cross_sym, START)
        if isinstance(cross.columns, pd.MultiIndex):
            cross.columns = [c[0] if isinstance(c, tuple) else c for c in cross.columns]
        close_col = "Close" if "Close" in cross.columns else cross.columns[0]
        df[name] = cross[close_col]

    df = df.dropna(how="any")

    if merge_sentiment:
        df = merge_sentiment_csvs(df, sym)

    return df
