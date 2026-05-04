"""
Train XGB on historical rows and predict the latest bar (next-period signal).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from config import HORIZONS
from data import load_data
from features import build_dataset
from models import predict, train_models


def train_and_predict_latest(ticker: str, horizon: int = 1) -> dict[str, Any]:
    """
    Fit scaler + XGB on all complete rows except the last feature row; predict for the last row.
    Returns scores plus last close and simple projected prices from reg head.
    """
    if horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of {HORIZONS}")

    df = load_data(ticker)
    raw_close = df["Close"].copy()

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

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_last_s = scaler.transform(X_last)

    models = train_models(X_train_s, y_cls_train, y_reg_train)
    p = predict(models, X_last_s)

    proba = float(p["proba"][0])
    pred_ret = float(p["ret"][0])

    projected_close = last_close * (1.0 + pred_ret)

    edge = proba * pred_ret

    return {
        "ticker": ticker.upper(),
        "as_of": str(last_date),
        "last_close": last_close,
        "horizon_days": horizon,
        "proba_up": proba,
        "pred_return": pred_ret,
        "edge": edge,
        "projected_close": projected_close,
    }


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
