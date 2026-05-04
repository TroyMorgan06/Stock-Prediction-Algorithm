"""
Compute PC: periodically retrains XGB (latest window) and writes predictions JSON.

Suggested workloads for this machine (pick any mix):
  - Run this worker on an interval (default 15 min): refresh prices, refit, publish JSON.
  - Run news_ingest.py / reddit_ingest.py on a schedule to grow sentiment CSVs.
  - Nightly: run main.py walk-forward for research (optional; heavy).

Other PC: open http://<THIS_PC_LAN_IP>:8765/ — not localhost on the viewer unless browser runs there.

Usage:
  python compute_worker.py
  python compute_worker.py --once
  python compute_worker.py --interval 600
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone

from config import (
    COMPUTE_INTERVAL_SEC,
    OUTPUT_DIR,
    PREDICTIONS_JSON,
    TICKERS,
    TICKERS_RUN,
)
from inference import rank_universe


def write_predictions(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)


def build_payload(tickers: list[str]) -> dict:
    rows, errors = rank_universe(tickers, horizon=1)
    return {
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "horizon_days": 1,
        "top_pick": rows[0]["ticker"] if rows else None,
        "stocks": rows,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh XGB predictions JSON for dashboard.")
    parser.add_argument("--once", action="store_true", help="Single run then exit.")
    parser.add_argument(
        "--interval",
        type=int,
        default=COMPUTE_INTERVAL_SEC,
        help="Seconds between runs (ignored with --once).",
    )
    parser.add_argument(
        "--out",
        default=os.path.join(OUTPUT_DIR, PREDICTIONS_JSON),
        help="Output JSON path.",
    )
    args = parser.parse_args()

    universe = TICKERS_RUN if TICKERS_RUN is not None else TICKERS

    while True:
        print(f"[{datetime.now(timezone.utc).isoformat()}] Computing {len(universe)} symbols...")
        try:
            payload = build_payload(universe)
            write_predictions(args.out, payload)
            print(f"  wrote {args.out} top={payload['top_pick']}")
        except Exception as exc:
            print(f"  ERROR: {exc}")

        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
