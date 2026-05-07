"""
Execute the generated trade plan on Alpaca.

This script is intentionally conservative:
  - only executes LONG rows from out/trade_plan.csv
  - will not place new buys if there isn't enough available cash
  - will skip symbols that already have an open position or open order
  - uses BRACKET orders (take profit + stop loss) so exits are automated

Setup:
  - Set environment variables:
      APCA_API_KEY_ID
      APCA_API_SECRET_KEY
  - Run against paper first:
      python alpaca_executor.py --paper --once

Note: This is not financial advice. Start with paper trading.
"""

from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest


@dataclass(frozen=True)
class PlanRow:
    rank: int
    side: str
    ticker: str
    prior_close: Optional[float]
    suggested_dollars: float


def _f(x: object) -> Optional[float]:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def load_plan_rows(path: str) -> List[PlanRow]:
    with open(path, "r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        out: List[PlanRow] = []
        for row in r:
            side = str(row.get("side") or "").strip().upper()
            ticker = str(row.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            out.append(
                PlanRow(
                    rank=int(float(row.get("rank") or 0)),
                    side=side,
                    ticker=ticker,
                    prior_close=_f(row.get("prior_close")),
                    suggested_dollars=float(row.get("suggested_dollars") or 0.0),
                )
            )
    out.sort(key=lambda x: x.rank)
    return out


def _cash_available(account) -> float:
    """
    Alpaca account fields vary by account type.
    Prefer cash-like values; fall back to buying_power.
    """
    for attr in ("cash", "cash_withdrawable", "cash_available_for_trading"):
        v = getattr(account, attr, None)
        fv = _f(v)
        if fv is not None:
            return fv
    bp = _f(getattr(account, "buying_power", None))
    return float(bp or 0.0)


def _round_price(x: float) -> float:
    # US equities are usually 2 decimals; keep it simple and stable.
    return round(float(x) + 1e-12, 2)


def iter_targets(rows: Iterable[PlanRow], max_buys: int) -> List[PlanRow]:
    longs = [r for r in rows if r.side == "LONG"]
    return longs[: max(0, int(max_buys))]


def main() -> None:
    p = argparse.ArgumentParser(description="Execute out/trade_plan.csv on Alpaca using bracket orders.")
    p.add_argument("--plan-csv", default=os.path.join("out", "trade_plan.csv"))
    p.add_argument("--paper", action="store_true", help="Use paper trading endpoint.")
    p.add_argument("--max-buys", type=int, default=2, help="Max number of buys to attempt per run.")
    p.add_argument("--notional", type=float, default=5.0, help="Target dollars per buy (fractional via notional).")
    p.add_argument("--take-profit", type=float, default=0.01, help="Take-profit percent (e.g. 0.01 = +1%).")
    p.add_argument("--stop-loss", type=float, default=0.01, help="Stop-loss percent (e.g. 0.01 = -1%).")
    p.add_argument("--dry-run", action="store_true", help="Print what would be submitted without placing orders.")
    args = p.parse_args()

    key = os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY") or ""
    secret = os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET") or ""
    if not key or not secret:
        raise SystemExit(
            "Missing Alpaca credentials. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY environment variables."
        )

    rows = load_plan_rows(args.plan_csv)
    targets = iter_targets(rows, args.max_buys)
    if not targets:
        print("No LONG targets in plan; nothing to do.")
        return

    trading = TradingClient(key, secret, paper=bool(args.paper))

    acct = trading.get_account()
    cash_avail = _cash_available(acct)
    per_trade = float(args.notional)
    if per_trade <= 0:
        raise SystemExit("--notional must be > 0")

    # Skip duplicates: if we already have a position or an open order for the symbol, do nothing.
    existing_positions = {p.symbol.upper() for p in trading.get_all_positions()}
    open_orders = trading.get_orders(status=QueryOrderStatus.OPEN)
    open_order_symbols = {o.symbol.upper() for o in open_orders if getattr(o, "symbol", None)}

    def blocked(sym: str) -> bool:
        s = sym.upper()
        return (s in existing_positions) or (s in open_order_symbols)

    allowed = [t for t in targets if not blocked(t.ticker)]
    if not allowed:
        print("All targets already have positions/orders; nothing to do.")
        return

    max_affordable = int(cash_avail // per_trade)
    n = min(len(allowed), max_affordable)
    if n <= 0:
        print(f"Insufficient available cash to trade. available=${cash_avail:.2f}, need >= ${per_trade:.2f}")
        return

    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    submit = allowed[:n]

    print(
        f"Account cash_available≈${cash_avail:.2f}. Submitting {len(submit)} bracket buy(s) at ~${per_trade:.2f} notional each."
    )
    print(f"Mode: {'PAPER' if args.paper else 'LIVE'}  Dry-run: {bool(args.dry_run)}")

    for r in submit:
        basis = r.prior_close if r.prior_close and r.prior_close > 0 else None
        if basis is None:
            print(f"SKIP {r.ticker}: missing/invalid prior_close to price brackets.")
            continue

        tp = _round_price(basis * (1.0 + float(args.take_profit)))
        sl = _round_price(basis * (1.0 - float(args.stop_loss)))
        if sl <= 0 or tp <= 0:
            print(f"SKIP {r.ticker}: invalid bracket prices tp={tp} sl={sl} (basis={basis}).")
            continue

        client_order_id = f"stock_ai_{now}_{r.ticker}"
        order = MarketOrderRequest(
            symbol=r.ticker,
            notional=per_trade,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=tp),
            stop_loss=StopLossRequest(stop_price=sl),
            client_order_id=client_order_id,
        )

        print(f"BUY {r.ticker} notional=${per_trade:.2f} bracket(tp={tp}, sl={sl}) id={client_order_id}")
        if args.dry_run:
            continue

        try:
            resp = trading.submit_order(order_data=order)
            oid = getattr(resp, "id", None)
            print(f"  submitted order_id={oid}")
        except Exception as exc:
            print(f"  ERROR submitting {r.ticker}: {exc}")


if __name__ == "__main__":
    main()

