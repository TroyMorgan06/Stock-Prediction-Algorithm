import numpy as np
import pandas as pd
from config import CROSS_ASSETS, HORIZONS


# ----------------------------
# BASIC INDICATORS
# ----------------------------
def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))


def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def macd(series):
    return ema(series, 12) - ema(series, 26)


# ----------------------------
# FEATURES
# ----------------------------
def create_features(df):
    df = df.copy()

    # returns (core signal base)
    df["ret"] = df["Close"].pct_change()

    # lags (short memory)
    for lag in [1, 2, 3, 5]:
        df[f"lag_{lag}"] = df["ret"].shift(lag)

    # volatility (regime awareness)
    df["vol_5"] = df["ret"].rolling(5).std()
    df["vol_20"] = df["ret"].rolling(20).std()
    df["vol_ratio"] = df["vol_5"] / (df["vol_20"] + 1e-9)

    # trend (simplified on purpose)
    df["ma_10"] = df["Close"].rolling(10).mean()
    df["ma_20"] = df["Close"].rolling(20).mean()
    df["trend"] = df["ma_10"] / (df["ma_20"] + 1e-9) - 1

    # momentum
    df["rsi"] = rsi(df["Close"])
    df["macd"] = macd(df["Close"])

    # cross asset (optional signal flow)
    for col in CROSS_ASSETS.keys():
        df[f"{col}_ret"] = df[col].pct_change(fill_method=None)

    # regime proxy (volatility shift)
    df["high_vol"] = (df["vol_20"] > df["vol_20"].rolling(50).mean()).astype(int)

    return df


# ----------------------------
# SENTIMENT FEATURES (IMPORTANT)
# expects merged dataframe
# ----------------------------
def add_sentiment_features(df):
    df = df.copy()

    reddit = df["reddit_sentiment_mean"] if "reddit_sentiment_mean" in df.columns else pd.Series(0, index=df.index)
    news = df["news_sentiment_mean"] if "news_sentiment_mean" in df.columns else pd.Series(0, index=df.index)
    reddit_mentions = df["reddit_mentions"] if "reddit_mentions" in df.columns else pd.Series(0, index=df.index)
    news_volume = df["news_volume"] if "news_volume" in df.columns else pd.Series(1, index=df.index)

    df["sent_diff"] = reddit - news
    df["sent_agree"] = np.sign(reddit) == np.sign(news)

    df["attention_spike"] = reddit_mentions / (news_volume + 1)

    df["sent_momentum"] = reddit.diff()

    return df


# ----------------------------
# TARGETS
# ----------------------------
def create_targets(df):
    df = df.copy()

    for h in HORIZONS:
        future_ret = df["Close"].pct_change(h).shift(-h)

        df[f"target_ret_{h}d"] = future_ret

        # cleaner classification (less noise than 3-class)
        df[f"target_dir_{h}d"] = (future_ret > 0).astype(int)

    return df


# ----------------------------
# FINAL PIPELINE
# ----------------------------
def build_dataset(df):
    df = create_features(df)
    df = add_sentiment_features(df)
    df = create_targets(df)

    feature_cols = [
        "ret",
        "vol_5", "vol_20", "vol_ratio",
        "ma_10", "ma_20", "trend",
        "rsi", "macd",
        "high_vol",
        "sent_diff",
        "sent_agree",
        "attention_spike",
        "sent_momentum",
    ]

    # cross asset features
    feature_cols += [f"{c}_ret" for c in CROSS_ASSETS.keys()]

    # Do NOT use df.dropna() on the full frame: target_ret_* are NaN on the
    # most recent rows (no future prices yet). That was trimming ~1 week of
    # live bars and made the dashboard look stale vs Yahoo's last session.
    df = df.dropna(subset=feature_cols)

    X = df[feature_cols]

    y_reg = {h: df[f"target_ret_{h}d"] for h in HORIZONS}
    y_cls = {h: df[f"target_dir_{h}d"] for h in HORIZONS}

    return X, y_reg, y_cls