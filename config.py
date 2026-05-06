START = "2015-01-01"

# Liquid large-cap basket (~30). `TICKER` is the default single symbol for backward compatibility.
TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "UNH", "JNJ", "WMT", "PG", "MA", "HD", "DIS", "BAC",
    "XOM", "CVX", "ABBV", "PFE", "KO", "PEP", "COST", "AVGO", "LLY",
    "MRK", "TMO", "MCD",
]

TICKER = TICKERS[0]

# Universe selection (Ubuntu Server deployment)
# - Put a newline-separated list of tickers in `universes/sp500.txt` or your own file.
# - Keep it smaller at first (e.g. 50–200) to avoid Yahoo/StockTwits rate limits.
UNIVERSE_FILE = "universes/sp500.txt"  # set to None to use `TICKERS` below
MAX_TICKERS = 200                      # hard cap per run for stability

# Override for faster iteration: set to a subset list or leave None.
TICKERS_RUN = None  # e.g. ["AAPL","MSFT","GOOGL"]

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
TRADE_PLAN_CSV = "trade_plan.csv"
DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 8765
COMPUTE_INTERVAL_SEC = 900

# User-friendly live plan defaults (compute_worker.py)
PLAN_NUM_NAMES = 30              # show top N names
PLAN_DOLLARS_PER_TRADE = 5.0     # tiny live test (longs)
PLAN_MIN_PROBA = 0.55            # trade filter
PLAN_MIN_PRED_RET = 0.003        # 0.30% predicted 1-day return

# Collector pacing (avoid provider blocks)
INGEST_SLEEP_SEC = 0.25
