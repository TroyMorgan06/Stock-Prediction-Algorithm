"""
Train XGB on historical rows and predict the latest bar (next-period signal).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from sklearn.preprocessing import StandardScaler

from config import HORIZONS
from data import load_data
from features import build_dataset
from models import predict, train_models


PRICE_BASIS_SHORT = (
    "Prices are Yahoo Finance adjusted daily closes (splits/dividends backed out). "
    "\"Today's close\" appears only when the latest daily bar is dated today's "
    "calendar date on this machine (session finalized). Ranking uses model edge "
    "(not shown)."
)


def train_and_predict_latest(ticker: str, horizon: int = 1) -> dict[str, Any]:
    """
    Fit scaler + XGB on all complete rows except the last feature row; predict for the last row.
    Returns scores plus last close and simple projected prices from reg head.
    """
    if horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of {HORIZONS}")

    df = load_data(ticker)
    raw_close = df["Close"].copy()
    raw_open = df["Open"].copy() if "Open" in df.columns else None

    X, y_reg, y_cls = build_dataset(df)
    if len(X) < 80:
        raise ValueError(f"{ticker}: not enough rows after cleaning ({len(X)})")

    y_cls_s = y_cls[horizon]
    y_reg_s = y_reg[horizon]

    X_train = X.iloc[:-1]
    y_cls_train = y_cls_s.iloc[:-1]
    y_reg_train = y_reg_s.iloc[:-1]
    X_last = X.iloc[-1:]

    last_date = X.index[-1]
    last_close = float(raw_close.loc[last_date])
    last_open = (
        float(raw_open.loc[last_date]) if raw_open is not None and last_date in raw_open.index else None
    )
    prior_close = (
        float(raw_close.loc[X.index[-2]]) if len(X) >= 2 else None
    )
    sess_cal = pd.Timestamp(last_date).date()
    # When Yahoo's latest daily row is calendar-"today" here, treat as finalized session close.
    today_close_final = float(last_close) if sess_cal == date.today() else None

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_last_s = scaler.transform(X_last)

    models = train_models(X_train_s, y_cls_train, y_reg_train)
    p = predict(models, X_last_s)

    proba = float(p["proba"][0])
    pred_ret = float(p["ret"][0])

    projected_close = last_close * (1.0 + pred_ret)

    edge = proba * pred_ret

    ts = pd.Timestamp(last_date)
    last_bar_date = ts.strftime("%Y-%m-%d")

    row: dict[str, Any] = {
        "ticker": ticker.upper(),
        "as_of": str(last_date),
        "last_bar_date": last_bar_date,
        "price_basis": PRICE_BASIS_SHORT,
        "session_open": last_open,
        "prior_close": prior_close,
        "projected_close": projected_close,
        "today_close_final": today_close_final,
        "last_close": last_close,
        "horizon_days": horizon,
        "proba_up": proba,
        "pred_return": pred_ret,
        "edge": edge,
    }
    return row


def rank_universe(tickers: list[str], horizon: int = 1) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for t in tickers:
        try:
            rows.append(train_and_predict_latest(t, horizon=horizon))
        except Exception as exc:
            errors.append({"ticker": t, "error": str(exc)})
    rows.sort(key=lambda r: r["edge"], reverse=True)
    return rows, errors
