"""
Social sentiment by ticker → CSV (no Reddit/Devvit).

This replaces the old Reddit/PRAW collector with a lightweight provider:
StockTwits public symbol stream API.

Why: Reddit now pushes many users into Devvit/OAuth flows; PRAW script apps may
be hard to obtain. StockTwits lets us fetch recent public messages without
credentials (rate-limited).

Output: keeps the same columns used by the pipeline:
  - reddit_sentiment_mean
  - reddit_sentiment_std
  - reddit_mentions

So you do NOT need to change `features.py` or `data.py`.

Requires: pip install requests nltk pandas

Usage:
  python reddit_ingest.py
  python reddit_ingest.py --daemon --interval 900
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone

import nltk
import pandas as pd
import requests
from nltk.sentiment.vader import SentimentIntensityAnalyzer

from config import INGEST_SLEEP_SEC, REDDIT_SENTIMENT_CSV
from universe import get_universe

nltk.download("vader_lexicon", quiet=True)

sia = SentimentIntensityAnalyzer()

STOCKTWITS_BASE = "https://api.stocktwits.com/api/2/streams/symbol"


def _stocktwits_symbol(ticker: str) -> str:
    # StockTwits tends to use '.' for class shares (BRK.B) rather than BRK-B
    t = ticker.upper().strip()
    return t.replace("-", ".")


def fetch_stocktwits_messages(ticker: str, limit: int = 30) -> list[str]:
    sym = _stocktwits_symbol(ticker)
    url = f"{STOCKTWITS_BASE}/{sym}.json"
    try:
        res = requests.get(url, timeout=30)
        if res.status_code != 200:
            return []
        data = res.json()
    except Exception:
        return []

    msgs = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(msgs, list):
        return []

    out: list[str] = []
    for m in msgs[: max(1, int(limit))]:
        if not isinstance(m, dict):
            continue
        body = m.get("body")
        if body:
            out.append(str(body))
    return out


def compute_reddit_row(ticker: str, limit: int) -> dict | None:
    # Writes into "reddit_*" columns for backwards compatibility.
    posts = fetch_stocktwits_messages(ticker, limit=limit)
    if not posts:
        return None
    scores = [sia.polarity_scores(p)["compound"] for p in posts]
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker.upper(),
        "reddit_sentiment_mean": float(sum(scores) / len(scores)),
        "reddit_sentiment_std": float(pd.Series(scores).std()) if len(scores) > 1 else 0.0,
        "reddit_mentions": int(len(posts)),
    }


def append_csv(path: str, row: dict) -> None:
    df = pd.DataFrame([row])
    write_header = not os.path.isfile(path) or os.path.getsize(path) == 0
    df.to_csv(path, mode="a", header=write_header, index=False)


def run_batch(
    tickers: list[str],
    path: str,
    _unused: list[str],
    limit_per_sub: int,
) -> None:
    for i, t in enumerate(tickers):
        row = compute_reddit_row(t, limit_per_sub)
        if row:
            append_csv(path, row)
            print(f"{t}: reddit_sentiment_mean={row['reddit_sentiment_mean']:.4f} mentions={row['reddit_mentions']}")
        else:
            print(f"{t}: no matching posts")
        if i < len(tickers) - 1:
            time.sleep(INGEST_SLEEP_SEC)


def main() -> None:
    parser = argparse.ArgumentParser(description="Social sentiment by ticker (StockTwits) → CSV.")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--output", default=REDDIT_SENTIMENT_CSV)
    parser.add_argument("--limit-per-sub", type=int, default=30, help="Messages per ticker to score.")
    args = parser.parse_args()

    if args.daemon:
        while True:
            try:
                run_batch(get_universe(), args.output, [], args.limit_per_sub)
            except Exception as exc:
                print("Error:", exc)
            time.sleep(args.interval)
    else:
        run_batch(get_universe(), args.output, [], args.limit_per_sub)


if __name__ == "__main__":
    main()
