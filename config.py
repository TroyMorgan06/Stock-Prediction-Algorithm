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
PLAN_NUM_NAMES = 40              # candidates in trade_plan.csv (decide picks top affordable)
PLAN_DOLLARS_PER_TRADE = 800.0   # display hint only
PLAN_MIN_PROBA = 0.55            # higher quality longs
PLAN_MIN_PRED_RET = 0.002        # 0.20% predicted return filter

# Hybrid morning — Swing Growth (see deploy/STRATEGY.md)
APPROVED_BASKET_CSV = "approved_basket.csv"
# Deploy up to this fraction of account equity when regime is ON.
MORNING_DEPLOY_FRACTION = 0.70
# Hard cap on dollars (safety); equity*fraction is used when smaller.
MORNING_DAILY_BUDGET = 7000.0
MORNING_MAX_BUYS = 8             # fewer, higher-conviction names
MORNING_TAKE_PROFIT = 0.05       # +5%  (~2:1 vs stop)
MORNING_STOP_LOSS = 0.025        # -2.5%
MORNING_CANDIDATE_POOL = 80
MORNING_MAX_SHARE_PRICE = 500.0  # allow 1-share fills on mid/large names
# Risk ~1% of equity per name at the stop (position ≈ risk / stop_pct).
MORNING_RISK_PER_TRADE = 0.01
# Max total risk if every name stopped out (soft portfolio heat).
MORNING_MAX_PORTFOLIO_HEAT = 0.08
# Long-only only when SPY close > SMA50 and SMA200.
MORNING_REQUIRE_SPY_UPTREND = True
MORNING_SPY_SMA_FAST = 50
MORNING_SPY_SMA_SLOW = 200


# Optional OpenAI-compatible LLM for hybrid_decide (env overrides these defaults)
# HYBRID_LLM_API_KEY or OPENAI_API_KEY in /etc/stock-ai/stock-ai.env
HYBRID_LLM_BASE_URL = "https://api.openai.com/v1"
HYBRID_LLM_MODEL = "gpt-4o-mini"

# Collector pacing (avoid provider blocks)
INGEST_SLEEP_SEC = 0.25
