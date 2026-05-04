"""
Scan configured subreddits for posts mentioning each ticker; append sentiment rows to CSV.

Requires: pip install praw nltk pandas
Environment: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET
Optional: REDDIT_USER_AGENT (default below)

Usage:
  python reddit_ingest.py
  python reddit_ingest.py --daemon --interval 300
"""

from __future__ import annotations

import argparse
import os
import re
import time
from datetime import datetime, timezone

import nltk
import pandas as pd
import praw
from nltk.sentiment.vader import SentimentIntensityAnalyzer

from config import REDDIT_SENTIMENT_CSV, TICKERS

nltk.download("vader_lexicon", quiet=True)

sia = SentimentIntensityAnalyzer()

DEFAULT_SUBS = ["stocks", "investing", "wallstreetbets"]


def reddit_client() -> praw.Reddit:
    cid = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    ua = os.environ.get("REDDIT_USER_AGENT", "stock_ai:sentiment:v1 (by /u/local)").strip()
    if not cid or not secret:
        raise ValueError("Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in the environment.")
    return praw.Reddit(client_id=cid, client_secret=secret, user_agent=ua)


def mentions_ticker(text: str, symbol: str) -> bool:
    u = text.upper()
    sym = symbol.upper()
    variants = {sym, sym.replace("-", "."), sym.replace("-", "")}
    for v in variants:
        if len(v) < 2:
            continue
        if re.search(rf"\b{re.escape(v)}\b", u):
            return True
    return False


def fetch_reddit_posts(
    reddit: praw.Reddit,
    symbol: str,
    subreddits: list[str],
    limit_per_sub: int,
) -> list[str]:
    posts: list[str] = []
    for sub in subreddits:
        try:
            for post in reddit.subreddit(sub).hot(limit=limit_per_sub):
                text = (post.title or "") + " " + (getattr(post, "selftext", None) or "")
                if mentions_ticker(text, symbol):
                    posts.append(text)
        except Exception:
            continue
    return posts


def compute_reddit_row(
    reddit: praw.Reddit,
    ticker: str,
    subreddits: list[str],
    limit_per_sub: int,
) -> dict | None:
    posts = fetch_reddit_posts(reddit, ticker, subreddits, limit_per_sub)
    if not posts:
        return None
    scores = [sia.polarity_scores(p)["compound"] for p in posts]
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker.upper(),
        "reddit_sentiment_mean": float(sum(scores) / len(scores)),
        "reddit_sentiment_std": float(pd.Series(scores).std()) if len(scores) > 1 else 0.0,
        "reddit_mentions": len(posts),
    }


def append_csv(path: str, row: dict) -> None:
    df = pd.DataFrame([row])
    write_header = not os.path.isfile(path) or os.path.getsize(path) == 0
    df.to_csv(path, mode="a", header=write_header, index=False)


def run_batch(
    tickers: list[str],
    path: str,
    subreddits: list[str],
    limit_per_sub: int,
) -> None:
    reddit = reddit_client()
    for i, t in enumerate(tickers):
        row = compute_reddit_row(reddit, t, subreddits, limit_per_sub)
        if row:
            append_csv(path, row)
            print(f"{t}: reddit_sentiment_mean={row['reddit_sentiment_mean']:.4f} mentions={row['reddit_mentions']}")
        else:
            print(f"{t}: no matching posts")
        if i < len(tickers) - 1:
            time.sleep(0.15)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reddit sentiment by ticker → CSV.")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--output", default=REDDIT_SENTIMENT_CSV)
    parser.add_argument("--limit-per-sub", type=int, default=50)
    parser.add_argument(
        "--subreddits",
        default=",".join(DEFAULT_SUBS),
        help="Comma-separated subreddit names.",
    )
    args = parser.parse_args()

    subs = [s.strip() for s in args.subreddits.split(",") if s.strip()]

    if args.daemon:
        while True:
            try:
                run_batch(TICKERS, args.output, subs, args.limit_per_sub)
            except Exception as exc:
                print("Error:", exc)
            time.sleep(args.interval)
    else:
        run_batch(TICKERS, args.output, subs, args.limit_per_sub)


if __name__ == "__main__":
    main()
