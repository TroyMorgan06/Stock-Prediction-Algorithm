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
import csv
import json
import os
import time
from datetime import datetime, timezone

from config import (
    COMPUTE_INTERVAL_SEC,
    OUTPUT_DIR,
    PREDICTIONS_JSON,
    TRADE_PLAN_CSV,
    PLAN_DOLLARS_PER_TRADE,
    PLAN_MIN_PRED_RET,
    PLAN_MIN_PROBA,
    PLAN_NUM_NAMES,
)
from inference import PRICE_BASIS_SHORT, rank_universe
from universe import get_universe


def write_predictions(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)


def write_trade_plan_csv(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    headers = [
        "rank",
        "side",
        "ticker",
        "session_date",
        "prior_close",
        "projected_close",
        "p_up",
        "pred_1d_return",
        "suggested_dollars",
        "notes",
    ]
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in headers})
    os.replace(tmp, path)


def _qualifies(r: dict) -> bool:
    try:
        return float(r.get("proba_up", 0.0)) >= PLAN_MIN_PROBA and float(r.get("pred_return", 0.0)) >= PLAN_MIN_PRED_RET
    except Exception:
        return False


def build_trade_plan(stocks: list[dict]) -> dict:
    """
    User-friendly plan:
      - Longs: top qualified names.
      - Shorts: bottom qualified names (paper by default; tiny shorting is hard at Fidelity).
    """
    qualified = [s for s in stocks if _qualifies(s)]
    longs = qualified[:PLAN_NUM_NAMES]
    shorts = list(reversed(qualified[-PLAN_NUM_NAMES:])) if qualified else []

    def to_row(s: dict, rank: int, side: str) -> dict:
        return {
            "rank": rank,
            "side": side,
            "ticker": s.get("ticker"),
            "session_date": s.get("last_bar_date"),
            "prior_close": round(float(s.get("prior_close") or 0.0), 4) if s.get("prior_close") is not None else "",
            "projected_close": round(float(s.get("projected_close") or 0.0), 4) if s.get("projected_close") is not None else "",
            "p_up": round(float(s.get("proba_up") or 0.0), 4) if s.get("proba_up") is not None else "",
            "pred_1d_return": round(float(s.get("pred_return") or 0.0), 6) if s.get("pred_return") is not None else "",
            "suggested_dollars": float(PLAN_DOLLARS_PER_TRADE),
            "notes": (
                "Long: buy fractional shares OK."
                if side == "LONG"
                else "Short: paper-trade first (Fidelity usually can't short fractional/$1)."
            ),
        }

    plan_rows: list[dict] = []
    for i, s in enumerate(longs, start=1):
        plan_rows.append(to_row(s, i, "LONG"))
    for i, s in enumerate(shorts, start=1):
        plan_rows.append(to_row(s, i, "SHORT_PAPER"))

    return {
        "filters": {
            "min_p_up": PLAN_MIN_PROBA,
            "min_pred_1d_return": PLAN_MIN_PRED_RET,
            "names_each_side": PLAN_NUM_NAMES,
            "suggested_dollars_per_trade": PLAN_DOLLARS_PER_TRADE,
        },
        "longs": [to_row(s, i + 1, "LONG") for i, s in enumerate(longs)],
        "shorts": [to_row(s, i + 1, "SHORT_PAPER") for i, s in enumerate(shorts)],
        "rows": plan_rows,
        "qualified_count": len(qualified),
    }


def build_payload(tickers: list[str]) -> dict:
    rows, errors = rank_universe(tickers, horizon=1)
    plan = build_trade_plan(rows)
    return {
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "horizon_days": 1,
        "about_last_close": PRICE_BASIS_SHORT,
        "top_pick": rows[0]["ticker"] if rows else None,
        "stocks": rows,
        "trade_plan": plan,
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
    parser.add_argument(
        "--plan-csv",
        default=os.path.join(OUTPUT_DIR, TRADE_PLAN_CSV),
        help="Output CSV path for a simple trade plan.",
    )
    args = parser.parse_args()

    universe = get_universe()

    while True:
        print(f"[{datetime.now(timezone.utc).isoformat()}] Computing {len(universe)} symbols...")
        try:
            payload = build_payload(universe)
            write_predictions(args.out, payload)
            if payload.get("trade_plan", {}).get("rows"):
                write_trade_plan_csv(args.plan_csv, payload["trade_plan"]["rows"])
            print(f"  wrote {args.out} top={payload['top_pick']}")
        except Exception as exc:
            print(f"  ERROR: {exc}")

        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
