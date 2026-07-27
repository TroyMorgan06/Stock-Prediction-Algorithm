from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import yfinance as yf

from config import CROSS_ASSETS, NEWS_SENTIMENT_CSV, REDDIT_SENTIMENT_CSV, START

# Do not pass requests.Session to yfinance >= 0.2.40+ / 1.x: the library uses
# curl_cffi internally and will error: "requires curl_cffi session not ... Session".


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


def _flatten_download(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """
    Normalize yfinance column layouts:
      - classic MultiIndex (Ticker, Price) or (Price, Ticker) in 1.x
      - single-level columns
    """
    if df is None or df.empty:
        return df
    sym = symbol.strip()
    if isinstance(df.columns, pd.MultiIndex):
        names = [str(n).lower() if n is not None else "" for n in (df.columns.names or [])]
        # Prefer selecting by ticker level when present.
        if "ticker" in names:
            t_i = names.index("ticker")
            try:
                df = df.xs(sym, axis=1, level=t_i, drop_level=True)
            except Exception:
                # Sometimes ticker level uses the only ticker without matching string
                try:
                    df = df.droplevel(t_i, axis=1)
                except Exception:
                    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        elif sym in df.columns.get_level_values(0):
            df = df[sym]
        elif df.columns.nlevels >= 2 and sym in df.columns.get_level_values(-1):
            df = df.xs(sym, axis=1, level=-1, drop_level=True)
        else:
            # Fall back: take first element of each tuple (usually Price name)
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    else:
        df.columns = [str(c) for c in df.columns]

    # Collapse leftover MultiIndex
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    df.columns = [str(c) for c in df.columns]
    # Title-case common OHLCV names if needed
    rename = {}
    for c in list(df.columns):
        cl = str(c).lower().strip()
        if cl == "open":
            rename[c] = "Open"
        elif cl == "high":
            rename[c] = "High"
        elif cl == "low":
            rename[c] = "Low"
        elif cl == "close":
            rename[c] = "Close"
        elif cl == "volume":
            rename[c] = "Volume"
        elif cl in ("adj close", "adjclose"):
            rename[c] = "Adj Close"
    if rename:
        df = df.rename(columns=rename)
    return df


def _yahoo_session():
    """Browser-like session so Yahoo is less likely to bot-block the Linux box."""
    try:
        from curl_cffi import requests as cffi_requests

        return cffi_requests.Session(impersonate="chrome")
    except Exception:
        return None


def _yf_download(symbol: str, extra: dict, session=None) -> pd.DataFrame:
    kwargs = {
        "tickers": symbol,
        "progress": False,
        "auto_adjust": True,
        "threads": False,
        "timeout": 45,
        **extra,
    }
    if session is not None:
        kwargs["session"] = session
    try:
        return yf.download(ignore_tz=True, **kwargs)
    except TypeError:
        # Older yfinance: no ignore_tz / no session kw
        kwargs.pop("ignore_tz", None)
        try:
            return yf.download(**kwargs)
        except TypeError:
            kwargs.pop("session", None)
            return yf.download(**kwargs)


def _to_alpaca_symbol(symbol: str) -> Optional[str]:
    """Map Yahoo-style tickers to Alpaca where possible. Indices usually unsupported."""
    s = symbol.strip().upper()
    if not s or s.startswith("^"):
        return None
    # Yahoo uses BRK-B; Alpaca uses BRK.B
    return s.replace("-", ".")


def _fetch_daily_alpaca(symbol: str, start: str) -> Optional[pd.DataFrame]:
    """
    Fallback daily bars via Alpaca market data (uses APCA_* from env).
    Returns None if keys missing, symbol unsupported, or request fails.
    """
    key = (os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY") or "").strip()
    secret = (os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET") or "").strip()
    if not key or not secret:
        return None
    apca_sym = _to_alpaca_symbol(symbol)
    if not apca_sym:
        return None
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed
    except ImportError:
        return None

    try:
        start_dt = pd.Timestamp(start).tz_localize("America/New_York")
    except Exception:
        start_dt = pd.Timestamp(start, tz="America/New_York")

    client = StockHistoricalDataClient(key, secret)
    # Prefer free IEX feed; fall back without feed if account has SIP.
    for feed in (DataFeed.IEX, None):
        try:
            kwargs = dict(
                symbol_or_symbols=apca_sym,
                timeframe=TimeFrame.Day,
                start=start_dt,
                end=datetime.now(timezone.utc),
            )
            if feed is not None:
                kwargs["feed"] = feed
            bars = client.get_stock_bars(StockBarsRequest(**kwargs))
            df = bars.df if hasattr(bars, "df") else None
            if df is None or df.empty:
                continue
            if isinstance(df.index, pd.MultiIndex):
                # (symbol, timestamp)
                try:
                    df = df.xs(apca_sym, level=0)
                except Exception:
                    df = df.reset_index(level=0, drop=True)
            out = pd.DataFrame(
                {
                    "Open": df["open"] if "open" in df.columns else df.get("Open"),
                    "High": df["high"] if "high" in df.columns else df.get("High"),
                    "Low": df["low"] if "low" in df.columns else df.get("Low"),
                    "Close": df["close"] if "close" in df.columns else df.get("Close"),
                    "Volume": df["volume"] if "volume" in df.columns else df.get("Volume"),
                }
            )
            out = _strip_tz_index(out)
            out = out.dropna(how="all")
            if not out.empty and "Close" in out.columns:
                return out
        except Exception:
            continue
    return None


def _fetch_daily(symbol: str, start: str, retries: int = 4, sleep_s: float = 2.0) -> pd.DataFrame:
    """
    Daily bars: Yahoo first (with browser impersonation), then Alpaca fallback.

    Prefer ``yf.download(..., ignore_tz=True)`` — avoids both the old
    "No timezone found" path and many builds that throw **failed to get ticker**
    when using ``Ticker()`` metadata before ``history()`` runs.
    """
    symbol = symbol.strip()
    last_err: Optional[Exception] = None
    session = _yahoo_session()

    variants = (
        {"start": start},
        {"period": "10y"},
        {"period": "max"},
    )

    for attempt in range(retries):
        for extra in variants:
            try:
                df = _yf_download(symbol, extra, session=session)
                df = _flatten_download(df, symbol)
                df = _strip_tz_index(df)
                df = _drop_yf_noise_cols(df)
                if df is not None and not df.empty and "Close" in df.columns:
                    return df
            except Exception as e:
                last_err = e

        try:
            t_kwargs = {}
            if session is not None:
                t_kwargs["session"] = session
            try:
                t = yf.Ticker(symbol, **t_kwargs)
            except TypeError:
                t = yf.Ticker(symbol)
            try:
                df = t.history(
                    start=start,
                    auto_adjust=True,
                    actions=False,
                    timeout=45,
                    repair=True,
                )
            except TypeError:
                try:
                    df = t.history(
                        start=start,
                        auto_adjust=True,
                        actions=False,
                        repair=True,
                    )
                except TypeError:
                    df = t.history(start=start, auto_adjust=True, actions=False)
            df = _flatten_download(df, symbol)
            df = _strip_tz_index(df)
            df = _drop_yf_noise_cols(df)
            if df is not None and not df.empty and "Close" in df.columns:
                return df
        except Exception as e:
            last_err = e

        # Mid-retry Alpaca attempt (equities only)
        try:
            alpaca_df = _fetch_daily_alpaca(symbol, start)
            if alpaca_df is not None and not alpaca_df.empty:
                print(f"{symbol}: using Alpaca bars (Yahoo empty/blocked)")
                return alpaca_df
        except Exception as e:
            last_err = e

        if attempt < retries - 1:
            time.sleep(sleep_s * (attempt + 1))

    # Final Alpaca attempt
    alpaca_df = _fetch_daily_alpaca(symbol, start)
    if alpaca_df is not None and not alpaca_df.empty:
        print(f"{symbol}: using Alpaca bars (Yahoo failed)")
        return alpaca_df

    msg = f"{symbol}: failed after {retries} rounds (Yahoo blocked or empty"
    if last_err:
        msg += f": {last_err}"
    msg += "). Try: pip install -U 'yfinance>=0.2.54' curl_cffi"
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
            # Forward-fill known sentiment; if the first sentiment point is recent,
            # earlier history remains NaN and will be default-filled below.
            out[col] = ser.reindex(idx).ffill().values

    _inject(_read_daily_sentiment_csv(NEWS_SENTIMENT_CSV, ticker))
    _inject(_read_daily_sentiment_csv(REDDIT_SENTIMENT_CSV, ticker))

    # IMPORTANT: when CSVs exist but only contain recent rows, earlier history is NaN.
    # Features expect these columns to be numeric and non-null across the full backtest span.
    if "news_sentiment_mean" not in out.columns:
        out["news_sentiment_mean"] = 0.0
    if "news_volume" not in out.columns:
        out["news_volume"] = 1.0
    if "reddit_sentiment_mean" not in out.columns:
        out["reddit_sentiment_mean"] = 0.0
    if "reddit_mentions" not in out.columns:
        out["reddit_mentions"] = 0.0

    out["news_sentiment_mean"] = pd.to_numeric(out["news_sentiment_mean"], errors="coerce").fillna(0.0)
    out["news_volume"] = pd.to_numeric(out["news_volume"], errors="coerce").fillna(1.0)
    out["reddit_sentiment_mean"] = pd.to_numeric(out["reddit_sentiment_mean"], errors="coerce").fillna(0.0)
    out["reddit_mentions"] = pd.to_numeric(out["reddit_mentions"], errors="coerce").fillna(0.0)

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

    eq_idx = df.index
    for name, cross_sym in CROSS_ASSETS.items():
        try:
            cross = _fetch_daily(cross_sym, START)
        except RuntimeError as exc:
            print(f"WARN: cross-asset {cross_sym} unavailable ({exc}); filling NaN then ffill")
            df[name] = float("nan")
            continue
        if isinstance(cross.columns, pd.MultiIndex):
            cross.columns = [c[0] if isinstance(c, tuple) else c for c in cross.columns]
        close_col = "Close" if "Close" in cross.columns else cross.columns[0]
        ser = cross[close_col].copy()
        ser.index = pd.DatetimeIndex(ser.index).sort_values()
        # Align to equity calendar: Yahoo calendars differ (holiday FX vs EQ).
        # NaN tail rows used to force dropna() to discard fresh equity bars — ffill fixes that.
        aligned = ser.reindex(eq_idx).ffill().bfill(limit=40)
        df[name] = aligned.values

    ohlcv = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
    df = df.dropna(subset=ohlcv, how="any")

    if merge_sentiment:
        df = merge_sentiment_csvs(df, sym)

    return df
