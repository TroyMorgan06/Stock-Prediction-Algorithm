"""
Morning oneshot: hybrid_decide → approved_basket.csv → alpaca_executor.

Swing Growth defaults (deploy/STRATEGY.md):
  python hybrid_morning.py --paper --daily-budget 7000 --max-buys 8 \\
      --take-profit 0.05 --stop-loss 0.025 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys

from config import (
    APPROVED_BASKET_CSV,
    MORNING_CANDIDATE_POOL,
    MORNING_DAILY_BUDGET,
    MORNING_MAX_BUYS,
    MORNING_MAX_SHARE_PRICE,
    MORNING_STOP_LOSS,
    MORNING_TAKE_PROFIT,
    OUTPUT_DIR,
    TRADE_PLAN_CSV,
)


def _basket_has_rows(path: str) -> bool:
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return any((r.get("ticker") or "").strip() for r in rows)
    except Exception:
        return False


def main() -> None:
    p = argparse.ArgumentParser(description="Hybrid morning: Swing Growth decide + execute.")
    p.add_argument("--plan-csv", default=os.path.join(OUTPUT_DIR, TRADE_PLAN_CSV))
    p.add_argument("--basket-csv", default=os.path.join(OUTPUT_DIR, APPROVED_BASKET_CSV))
    p.add_argument("--paper", action="store_true")
    p.add_argument("--daily-budget", type=float, default=MORNING_DAILY_BUDGET)
    p.add_argument("--max-buys", type=int, default=MORNING_MAX_BUYS)
    p.add_argument("--candidate-pool", type=int, default=MORNING_CANDIDATE_POOL)
    p.add_argument("--max-share-price", type=float, default=MORNING_MAX_SHARE_PRICE)
    p.add_argument("--take-profit", type=float, default=MORNING_TAKE_PROFIT)
    p.add_argument("--stop-loss", type=float, default=MORNING_STOP_LOSS)
    p.add_argument("--clear-stale-orders", action="store_true", default=True)
    p.add_argument("--no-clear-stale-orders", action="store_false", dest="clear_stale_orders")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--decide-only", action="store_true", help="Write basket; skip executor.")
    args = p.parse_args()

    root = os.path.dirname(os.path.abspath(__file__))
    py = sys.executable

    decide_cmd = [
        py,
        os.path.join(root, "hybrid_decide.py"),
        "--plan-csv",
        args.plan_csv,
        "--basket-csv",
        args.basket_csv,
        "--daily-budget",
        str(args.daily_budget),
        "--max-buys",
        str(args.max_buys),
        "--candidate-pool",
        str(args.candidate_pool),
        "--max-share-price",
        str(args.max_share_price),
        "--stop-loss",
        str(args.stop_loss),
    ]
    if args.paper:
        decide_cmd.append("--paper")
    if args.dry_run:
        decide_cmd.append("--dry-run")

    print("hybrid_morning: running Swing Growth decide…", flush=True)
    r1 = subprocess.run(decide_cmd, cwd=root)
    if r1.returncode != 0:
        raise SystemExit(r1.returncode)

    if args.decide_only:
        print("hybrid_morning: decide-only; skipping execute.", flush=True)
        return

    if not _basket_has_rows(args.basket_csv):
        print("hybrid_morning: empty basket (regime off or no names) — skip execute.", flush=True)
        return

    exec_cmd = [
        py,
        os.path.join(root, "alpaca_executor.py"),
        "--plan-csv",
        args.basket_csv,
        "--daily-budget",
        str(args.daily_budget),
        "--max-buys",
        str(args.max_buys),
        "--take-profit",
        str(args.take_profit),
        "--stop-loss",
        str(args.stop_loss),
    ]
    if args.paper:
        exec_cmd.append("--paper")
    if args.dry_run:
        exec_cmd.append("--dry-run")
    if args.clear_stale_orders:
        exec_cmd.append("--clear-stale-orders")
    else:
        exec_cmd.append("--no-clear-stale-orders")

    print("hybrid_morning: running executor on approved basket…", flush=True)
    r2 = subprocess.run(exec_cmd, cwd=root)
    raise SystemExit(r2.returncode)


if __name__ == "__main__":
    main()
