import yfinance as yf
import pandas as pd
import numpy as np

from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error

# ----------------------------
# CONFIG
# ----------------------------
TICKER = "AAPL"
START = "2015-01-01"

CROSS_ASSETS = {
    "SPY": "SPY",        # market
    "VIX": "^VIX",       # volatility
    "TNX": "^TNX"        # 10Y yield
}

HORIZONS = [1, 3, 7]


# ----------------------------
# DATA LOADING
# ----------------------------
def load_data():
    df = yf.download(TICKER, start=START)

    # flatten columns
    df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

    for name, ticker in CROSS_ASSETS.items():
        cross = yf.download(ticker, start=START)
        cross.columns = [col[0] if isinstance(col, tuple) else col for col in cross.columns]

        df[name] = cross["Close"]

    return df


# ----------------------------
# FEATURE ENGINEERING
# ----------------------------
def create_features(df):
    df = df.copy()

    # base return
    df["return"] = df["Close"].pct_change()

    # lagged returns
    for lag in range(1, 6):
        df[f"return_lag_{lag}"] = df["return"].shift(lag)

    # rolling features
    df["volatility_5"] = df["return"].rolling(5).std()
    df["volatility_10"] = df["return"].rolling(10).std()

    df["ma_5"] = df["Close"].rolling(5).mean()
    df["ma_10"] = df["Close"].rolling(10).mean()

    # cross-asset returns
    for col in CROSS_ASSETS.keys():
        df[f"{col}_return"] = df[col].pct_change(fill_method=None)
        df[f"{col}_lag1"] = df[f"{col}_return"].shift(1)

    return df


# ----------------------------
# TARGETS (multi-horizon)
# ----------------------------
def create_targets(df):
    df = df.copy()

    for h in HORIZONS:
        df[f"target_{h}d"] = df["Close"].pct_change(h).shift(-h)

    return df


# ----------------------------
# PREP DATASET
# ----------------------------
def prepare_dataset():
    df = load_data()
    df = create_features(df)
    df = create_targets(df)

    df = df.dropna()

    feature_cols = [col for col in df.columns if "lag" in col or "volatility" in col or "ma_" in col or "_return" in col]

    X = df[feature_cols]

    targets = {h: df[f"target_{h}d"] for h in HORIZONS}

    return X, targets



# ----------------------------
# TRAIN MODELS
# ----------------------------
def train_models(X, targets):
    split = int(len(X) * 0.8)

    X_train, X_test = X[:split], X[split:]

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    results = {}

    for h, y in targets.items():
        results[h] = {}
        y_train, y_test = y[:split], y[split:]
        baseline_preds = np.zeros_like(y_test)
        baseline_mse = mean_squared_error(y_test, baseline_preds)
        print(f"Horizon {h}d | Baseline MSE: {baseline_mse:.6f}")

        models = {
            "linear": LinearRegression(),
            "rf": RandomForestRegressor(n_estimators=200, max_depth=6),
            "gboost": GradientBoostingRegressor()
        }

        for name, model in models.items():
            model.fit(X_train_scaled, y_train)

            preds = model.predict(X_test_scaled)
            preds = np.clip(preds, -0.05, 0.05)

            mse = mean_squared_error(y_test, preds)
            direction_acc = np.mean((preds > 0) == (y_test > 0))

            print(f"Horizon {h}d | {name} Direction Accuracy: {direction_acc:.3f}")
            print(f"Horizon {h}d | {name} MSE: {mse:.6f}")

            results[h][name] = {
                "model": model,
                "preds": preds,
                "y_test": y_test.values,
                "mse": mse,
                "direction_acc": direction_acc
            }


    print("\n--- BACKTEST RESULTS ---")

    for h in HORIZONS:
        for name in results[h].keys():

            preds = results[h][name]["preds"]
            y_test = results[h][name]["y_test"]

            stats = backtest_strategy(preds, y_test)

            print(f"\nHorizon {h}d | {name}")
            print(f"Return: {stats['total_return']:.3f}")
            print(f"Sharpe: {stats['sharpe']:.3f}")
            print(f"Max Drawdown: {stats['max_drawdown']:.3f}")


    return results, scaler


# ----------------------------
# ENSEMBLE PREDICTION
# ----------------------------
def ensemble_predict(models, scaler, latest_X):
    X_scaled = scaler.transform(latest_X)

    predictions = {}

    for h in HORIZONS:
        preds = []

        for name, model_info in models[h].items():
            model = model_info["model"]
            pred = model.predict(X_scaled)[0]
            preds.append(pred)

        predictions[h] = np.mean(preds)

    return predictions

import numpy as np

def backtest_strategy(preds, actual_returns):
    preds = np.array(preds)
    actual_returns = np.array(actual_returns)

    # POSITION: long if positive signal, short if negative
    positions = np.sign(preds)

    # strategy returns
    strategy_returns = positions * actual_returns

    # equity curve
    equity = np.cumprod(1 + strategy_returns)

    # metrics
    total_return = equity[-1] - 1

    sharpe = np.mean(strategy_returns) / (np.std(strategy_returns) + 1e-9) * np.sqrt(252)

    drawdown = equity / np.maximum.accumulate(equity) - 1
    max_drawdown = np.min(drawdown)

    return {
        "total_return": total_return,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "equity_curve": equity
    }

# ----------------------------
# MAIN
# ----------------------------
if __name__ == "__main__":
    X, targets = prepare_dataset()
    models, scaler = train_models(X, targets)

    latest = X.iloc[-1:]
    preds = ensemble_predict(models, scaler, latest)

    print("\nFinal multi-horizon prediction:")
    for h, val in preds.items():
        print(f"{h} day return: {val:.4f}")