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
PLAN_NUM_NAMES = 30              # long candidates in trade_plan.csv
PLAN_DOLLARS_PER_TRADE = 166.0   # display hint; morning job uses MORNING_* / CLI flags
PLAN_MIN_PROBA = 0.52            # trade filter (lower => more names in plan)
PLAN_MIN_PRED_RET = 0.001        # 0.10% predicted 1-day return

# Hybrid morning trade (hybrid_decide.py / hybrid_morning.py / systemd)
APPROVED_BASKET_CSV = "approved_basket.csv"
MORNING_DAILY_BUDGET = 2000.0    # dollars to deploy once at open
MORNING_MAX_BUYS = 12            # max names in approved basket
MORNING_TAKE_PROFIT = 0.015      # +1.5%
MORNING_STOP_LOSS = 0.015        # -1.5%
MORNING_CANDIDATE_POOL = 60      # LONG rows scanned before affordability filter

# Optional OpenAI-compatible LLM for hybrid_decide (env overrides these defaults)
# HYBRID_LLM_API_KEY or OPENAI_API_KEY in /etc/stock-ai/stock-ai.env
HYBRID_LLM_BASE_URL = "https://api.openai.com/v1"
HYBRID_LLM_MODEL = "gpt-4o-mini"

# Collector pacing (avoid provider blocks)
INGEST_SLEEP_SEC = 0.25
