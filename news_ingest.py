"""
Append Finnhub company-news sentiment rows (one row per poll per ticker).

Requires: pip install requests nltk pandas
Environment: FINNHUB_API_KEY

Usage:
  python news_ingest.py              # one batch for all TICKERS in config
  python news_ingest.py --daemon     # poll forever (interval seconds)
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timedelta, timezone

import nltk
import pandas as pd
import requests
from nltk.sentiment.vader import SentimentIntensityAnalyzer

from config import INGEST_SLEEP_SEC, NEWS_SENTIMENT_CSV
from universe import get_universe

nltk.download("vader_lexicon", quiet=True)

sia = SentimentIntensityAnalyzer()


def fetch_news_headlines(ticker: str, api_key: str, days_back: int = 7) -> list[str]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days_back)
    url = (
        "https://finnhub.io/api/v1/company-news"
        f"?symbol={requests.utils.quote(ticker)}"
        f"&from={start.isoformat()}&to={end.isoformat()}&token={api_key}"
    )
    res = requests.get(url, timeout=45)
    if res.status_code != 200:
        return []
    data = res.json()
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        if isinstance(item, dict) and item.get("headline"):
            out.append(str(item["headline"]))
    return out[:200]


def score(text: str) -> float:
    return sia.polarity_scores(text)["compound"]


def compute_news_row(ticker: str, api_key: str, days_back: int = 7) -> dict | None:
    headlines = fetch_news_headlines(ticker, api_key, days_back=days_back)
    if not headlines:
        return None
    scores = [score(h) for h in headlines]
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker.upper(),
        "news_sentiment_mean": float(sum(scores) / len(scores)),
        "news_sentiment_max": float(max(scores)),
        "news_sentiment_min": float(min(scores)),
        "news_volume": len(scores),
    }


def append_csv(path: str, row: dict) -> None:
    df = pd.DataFrame([row])
    write_header = not os.path.isfile(path) or os.path.getsize(path) == 0
    df.to_csv(path, mode="a", header=write_header, index=False)


def run_batch(tickers: list[str], api_key: str, days_back: int, path: str) -> None:
    for i, t in enumerate(tickers):
        row = compute_news_row(t, api_key, days_back=days_back)
        if row:
            append_csv(path, row)
            print(f"{t}: news_sentiment_mean={row['news_sentiment_mean']:.4f} n={row['news_volume']}")
        else:
            print(f"{t}: no headlines / API empty")
        if i < len(tickers) - 1:
            time.sleep(INGEST_SLEEP_SEC)


def main() -> None:
    parser = argparse.ArgumentParser(description="Finnhub news sentiment → CSV.")
    parser.add_argument("--daemon", action="store_true", help="Poll forever.")
    parser.add_argument("--interval", type=int, default=300, help="Daemon sleep seconds.")
    parser.add_argument("--days", type=int, default=7, help="Lookback days for company-news.")
    parser.add_argument("--output", default=NEWS_SENTIMENT_CSV)
    args = parser.parse_args()

    api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Set FINNHUB_API_KEY in the environment.")

    tickers = get_universe()

    if args.daemon:
        while True:
            try:
                run_batch(tickers, api_key, args.days, args.output)
            except Exception as exc:
                print("Error:", exc)
            time.sleep(args.interval)
    else:
        run_batch(tickers, api_key, args.days, args.output)


if __name__ == "__main__":
    main()
