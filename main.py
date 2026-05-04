from __future__ import annotations

import pandas as pd

from sklearn.preprocessing import StandardScaler
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from data import load_data
from features import build_dataset
from models import train_models, predict
from config import HORIZONS, TICKERS, TICKERS_RUN

# Risk / sizing knobs (tune without changing model code)
MAX_GROSS_LEVERAGE = 0.35
PRED_RET_CAP = 0.03
VOL_FLOOR = 5e-4
MIN_CONFIDENCE = 0.03
POSITION_EWM_SPAN = 5


# ----------------------------
# POSITION SIZING
# ----------------------------
def position_size(proba_up, pred_ret, vol):
    """
    Vol-targeted sizing with confidence centered at 50% probability.
    `vol` is per-bar (e.g. rolling std of returns), same length as predictions.
    """
    vol = np.asarray(vol, dtype=float) + 1e-9
    proba_up = np.asarray(proba_up, dtype=float)
    pred_ret = np.asarray(pred_ret, dtype=float)

    confidence = (proba_up - 0.5) * 2.0
    small = np.abs(confidence) < MIN_CONFIDENCE
    confidence = np.where(small, 0.0, confidence)

    edge = confidence * np.clip(pred_ret, -PRED_RET_CAP, PRED_RET_CAP)
    pos = edge / np.maximum(vol, VOL_FLOOR)
    pos = np.clip(pos, -MAX_GROSS_LEVERAGE, MAX_GROSS_LEVERAGE)
    return pos


# ----------------------------
# WALK-FORWARD (single instrument panel)
# ----------------------------
def run_walk_forward(X_df: pd.DataFrame, y_reg: pd.Series, y_cls: pd.Series) -> dict:
    train_size = int(len(X_df) * 0.6)
    test_size = int(len(X_df) * 0.2)
    step = test_size
    gap = max(HORIZONS)

    min_need = train_size + test_size + gap + 5
    if len(X_df) < min_need:
        return {
            "final_equity": np.array([]),
            "final_dates": np.array([], dtype="datetime64[ns]"),
            "final_return": 0.0,
            "folds": 0,
        }

    equity_curves = []
    equity_dates = []
    running_equity = 1.0
    folds = 0

    for start in range(0, len(X_df) - train_size - test_size, step):
        end_train = start + train_size
        end_test = end_train + test_size

        X_train = X_df.iloc[start : end_train - gap]
        X_test = X_df.iloc[end_train:end_test]

        y_train_reg = y_reg.iloc[start : end_train - gap]
        y_test_reg = y_reg.iloc[end_train:end_test]

        y_train_cls = y_cls.iloc[start : end_train - gap]

        vol_test = X_test["vol_20"].to_numpy(dtype=float)

        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)

        models = train_models(X_train_s, y_train_cls, y_train_reg)
        preds = predict(models, X_test_s)

        proba_up = preds["proba"]
        pred_ret = preds["ret"]

        position = position_size(proba_up, pred_ret, vol_test)
        position = (
            pd.Series(position, index=y_test_reg.index)
            .ewm(span=POSITION_EWM_SPAN, adjust=False)
            .mean()
            .to_numpy()
        )

        strategy_returns = position * y_test_reg.to_numpy(dtype=float)
        fold_growth = np.cumprod(1.0 + strategy_returns)
        equity_segment = running_equity * fold_growth / fold_growth[0]
        running_equity = float(equity_segment[-1])
        equity_curves.append(equity_segment)
        equity_dates.append(y_test_reg.index.to_numpy())
        folds += 1

        print(f"  fold start={start}: seg_return={equity_segment[-1] / equity_segment[0] - 1:.3f}")

        acc = np.mean((proba_up > 0.5) == (y_test_reg > 0))
        print(f"  fold start={start}: accuracy={acc:.3f}")

    final_equity = np.concatenate(equity_curves) if equity_curves else np.array([])
    final_dates = np.concatenate(equity_dates) if equity_dates else np.array([], dtype="datetime64[ns]")
    final_return = float(final_equity[-1] - 1) if len(final_equity) else 0.0

    return {
        "final_equity": final_equity,
        "final_dates": final_dates,
        "final_return": final_return,
        "folds": folds,
    }


# ----------------------------
# MULTI-TICKER RUN
# ----------------------------
summary = []
universe = TICKERS_RUN if TICKERS_RUN is not None else TICKERS

for ticker in universe:
    print(f"\n=== {ticker} ===")
    try:
        df = load_data(ticker)
        X, y_reg_h, y_cls_h = build_dataset(df)
        X_df = X.copy()
        y_reg = y_reg_h[1]
        y_cls = y_cls_h[1]

        out = run_walk_forward(X_df, y_reg, y_cls)
        out["ticker"] = ticker
        summary.append(out)
        print(f"  final_return={out['final_return']:.4f} folds={out['folds']}")
    except Exception as exc:
        print(f"  skipped: {exc}")
        summary.append({"ticker": ticker, "final_return": None, "folds": 0, "error": str(exc)})


def _first_plottable(results: list[dict]) -> dict | None:
    for r in results:
        fe = r.get("final_equity")
        if fe is not None and len(fe) > 0:
            return r
    return None


plot_src = _first_plottable(summary)
fig, ax = plt.subplots(figsize=(12, 5))
if plot_src is not None:
    fe = plot_src["final_equity"]
    fd = plot_src["final_dates"]
    sym = plot_src.get("ticker", "?")
    if len(fd) > 0:
        ax.plot(fd, fe, label=f"{sym} (first available)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate()
        ax.set_xlabel("Date")
    else:
        ax.plot(fe, label=sym)
    ax.set_ylabel("Equity")
    ax.set_title("Walk-Forward Strategy — sample equity (one ticker)")
    ax.legend()
else:
    ax.text(0.5, 0.5, "No equity curve to plot", ha="center", va="center", transform=ax.transAxes)
ax.grid()
plt.tight_layout()
plt.show()

ok = [s for s in summary if s.get("final_return") is not None]
if ok:
    rets = [s["final_return"] for s in ok]
    print("\n--- Summary (all tickers) ---")
    for s in ok:
        print(f"  {s['ticker']}: final_return={s['final_return']:.4f} folds={s.get('folds', 0)}")
    print(f"Mean final_return: {float(np.mean(rets)):.4f}")
