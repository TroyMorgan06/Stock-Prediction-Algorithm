START = "2015-01-01"

# Liquid large-cap basket (~30). `TICKER` is the default single symbol for backward compatibility.
TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "UNH", "JNJ", "WMT", "PG", "MA", "HD", "DIS", "BAC",
    "XOM", "CVX", "ABBV", "PFE", "KO", "PEP", "COST", "AVGO", "LLY",
    "MRK", "TMO", "MCD",
]

TICKER = TICKERS[0]

# Override for faster iteration: set to a subset or leave None for full basket.
TICKERS_RUN = None  # e.g. TICKERS[:5]

HORIZONS = [1, 3, 7]

CROSS_ASSETS = {
    "SPY": "SPY",
    "VIX": "^VIX",
    "TNX": "^TNX",
}

# Optional: CSV files produced by news_ingest / reddit_ingest (merged in load_data if present)
NEWS_SENTIMENT_CSV = "sentiment_news.csv"
REDDIT_SENTIMENT_CSV = "sentiment_reddit.csv"

# Live inference / dashboard (compute_worker.py, serve_dashboard.py)
OUTPUT_DIR = "out"
PREDICTIONS_JSON = "predictions.json"
DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 8765
COMPUTE_INTERVAL_SEC = 900
