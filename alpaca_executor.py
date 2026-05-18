"""
Execute the generated trade plan on Alpaca.

This script is intentionally conservative:
  - only executes LONG rows from out/trade_plan.csv
  - will not place new buys if there isn't enough available cash
  - will skip symbols that already have an open position or open order
  - uses BRACKET orders (take profit + stop loss) so exits are automated
  - bracket entry uses whole-share qty (Alpaca does not allow notional/fractional brackets)

Setup:
  - Set environment variables:
      APCA_API_KEY_ID
      APCA_API_SECRET_KEY
  - Run against paper first:
      python alpaca_executor.py --paper --dry-run

Note: This is not financial advice. Start with paper trading.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)

# Bump when debugging deploy mismatches (printed at startup).
EXECUTOR_VERSION = "2026-05-18-limit-bracket-v3"


@dataclass(frozen=True)
class PlanRow:
    rank: int
    side: str
    ticker: str
    prior_close: Optional[float]
    suggested_dollars: float


@dataclass(frozen=True)
class QuoteSnap:
    ask: Optional[float] = None
    bid: Optional[float] = None
    last: Optional[float] = None


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
    return round(float(x) + 1e-12, 2)


def _round_price_up(x: float) -> float:
    return math.ceil(float(x) * 100 - 1e-9) / 100.0


def _round_price_down(x: float) -> float:
    return math.floor(float(x) * 100 + 1e-9) / 100.0


# Alpaca validates bracket legs against entry limit price (limit entry) or live market (market entry).
ALPACA_BRACKET_MIN_OFFSET = 0.01


def _entry_limit_price(snap: QuoteSnap) -> Optional[float]:
    """Buy limit at ask (rounded up) so bracket base_price matches our entry limit."""
    if snap.ask and snap.ask > 0:
        return _round_price_up(snap.ask)
    if snap.last and snap.last > 0:
        return _round_price_up(snap.last)
    if snap.bid and snap.bid > 0:
        return _round_price_up(snap.bid)
    return None


def _qty_for_bracket(*, target_dollars: float, price: float, cash_cap: float) -> int:
    """Whole shares only — bracket orders cannot use notional/fractional entry."""
    if price <= 0 or cash_cap <= 0:
        return 0
    qty = int(float(target_dollars) // float(price))
    if qty >= 1:
        return qty
    if cash_cap >= price:
        return 1
    return 0


def _bracket_prices(
    entry: float,
    *,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> Optional[Tuple[float, float]]:
    """
    Return (take_profit_limit, stop_loss_stop) for a buy bracket.

    Legs are priced from entry limit; TP/SL are rounded away from entry to satisfy
    take_profit >= entry + $0.01 and stop_loss <= entry - $0.01.
    """
    if entry <= 0:
        return None
    offset = ALPACA_BRACKET_MIN_OFFSET
    tp = max(entry * (1.0 + float(take_profit_pct)), entry + offset)
    sl = min(entry * (1.0 - float(stop_loss_pct)), entry - offset)
    tp = _round_price_up(tp)
    sl = _round_price_down(sl)
    min_tp = _round_price_up(entry + offset)
    max_sl = _round_price_down(entry - offset)
    if tp < min_tp:
        tp = min_tp
    if sl > max_sl:
        sl = max_sl
    if sl <= 0 or tp <= sl:
        return None
    return tp, sl


def _fetch_market_quotes(key: str, secret: str, symbols: List[str]) -> Dict[str, QuoteSnap]:
    if not symbols:
        return {}
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestQuoteRequest, StockLatestTradeRequest
    except ImportError:
        return {}

    client = StockHistoricalDataClient(key, secret)
    uniq = sorted({s.upper() for s in symbols if s})
    out: Dict[str, QuoteSnap] = {sym: QuoteSnap() for sym in uniq}

    try:
        quotes = client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=uniq))
    except Exception:
        quotes = None

    if quotes is not None:
        for sym in uniq:
            q = quotes.get(sym) if hasattr(quotes, "get") else None
            if q is None:
                continue
            out[sym] = QuoteSnap(
                ask=_f(getattr(q, "ask_price", None)),
                bid=_f(getattr(q, "bid_price", None)),
                last=out[sym].last,
            )

    try:
        trades = client.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=uniq))
    except Exception:
        return out

    if trades is not None:
        for sym in uniq:
            t = trades.get(sym) if hasattr(trades, "get") else None
            last = _f(getattr(t, "price", None)) if t is not None else None
            snap = out[sym]
            out[sym] = QuoteSnap(ask=snap.ask, bid=snap.bid, last=last if last and last > 0 else snap.last)
    return out


def iter_targets(rows: Iterable[PlanRow], max_buys: int) -> List[PlanRow]:
    longs = [r for r in rows if r.side == "LONG"]
    return longs[: max(0, int(max_buys))]


def _exit_on_alpaca_auth_failure(exc: BaseException, *, paper: bool) -> None:
    """Raise SystemExit with actionable hints when Alpaca returns 401."""
    text = str(exc).lower()
    code = getattr(exc, "status_code", None)
    resp = getattr(exc, "response", None)
    resp_code = getattr(resp, "status_code", None) if resp is not None else None
    if code != 401 and resp_code != 401 and "401" not in str(exc) and "unauthorized" not in text:
        return
    env = "paper (paper-api.alpaca.markets)" if paper else "live (api.alpaca.markets)"
    raise SystemExit(
        "Alpaca API rejected your credentials (401 Unauthorized).\n\n"
        f"You are using the {env} endpoint. Keys must match that environment:\n"
        "  - In the Alpaca dashboard, open Paper Trading and copy the Paper API Key ID + Secret, OR\n"
        "    open Live and copy the Live keys — they are not interchangeable.\n"
        "  - systemd: check /etc/stock-ai/stock-ai.env has APCA_API_KEY_ID and APCA_API_SECRET_KEY\n"
        "    (no quotes, no spaces around '=', one line per variable).\n"
        "  - After editing the env file: sudo systemctl daemon-reload && "
        "sudo systemctl restart stock-ai-trade.service\n\n"
        f"Original error: {exc}"
    ) from exc


def _calc_per_trade(
    *,
    cash_available: float,
    max_buys: int,
    notional: Optional[float],
    daily_budget: Optional[float],
) -> tuple[int, float]:
    """
    Returns (n_trades, per_trade_notional) respecting cash constraints.
    """
    max_buys = max(0, int(max_buys))
    if max_buys <= 0:
        return 0, 0.0

    if daily_budget is not None:
        budget = float(daily_budget)
        if budget <= 0:
            raise SystemExit("--daily-budget must be > 0")
        budget = min(budget, float(cash_available))
        per_trade = budget / float(max_buys)
        if per_trade <= 0:
            return 0, 0.0
        max_affordable = int(float(cash_available) // per_trade)
        n = min(max_buys, max_affordable)
        return n, float(per_trade)

    if notional is None:
        raise SystemExit("Either --notional or --daily-budget must be provided")
    per_trade = float(notional)
    if per_trade <= 0:
        raise SystemExit("--notional must be > 0")
    max_affordable = int(float(cash_available) // per_trade)
    n = min(max_buys, max_affordable)
    return n, float(per_trade)


def main() -> None:
    p = argparse.ArgumentParser(description="Execute out/trade_plan.csv on Alpaca using bracket orders.")
    p.add_argument("--plan-csv", default=os.path.join("out", "trade_plan.csv"))
    p.add_argument("--paper", action="store_true", help="Use paper trading endpoint.")
    p.add_argument("--max-buys", type=int, default=2, help="Max number of buys to attempt per run.")
    p.add_argument(
        "--notional",
        type=float,
        default=5.0,
        help="Target dollars per buy (converted to whole shares; bracket orders are not fractional).",
    )
    p.add_argument(
        "--daily-budget",
        type=float,
        default=None,
        help="Total dollars to deploy per run (split across --max-buys). Overrides --notional.",
    )
    p.add_argument("--take-profit", type=float, default=0.01, help="Take-profit percent (e.g. 0.01 = +1%).")
    p.add_argument("--stop-loss", type=float, default=0.01, help="Stop-loss percent (e.g. 0.01 = -1%).")
    p.add_argument("--dry-run", action="store_true", help="Print what would be submitted without placing orders.")
    args = p.parse_args()

    key = (os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY") or "").strip()
    secret = (os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET") or "").strip()
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

    try:
        acct = trading.get_account()
    except Exception as exc:
        _exit_on_alpaca_auth_failure(exc, paper=bool(args.paper))
        raise
    cash_avail = _cash_available(acct)

    # Skip duplicates: if we already have a position or an open order for the symbol, do nothing.
    existing_positions = {p.symbol.upper() for p in trading.get_all_positions()}
    open_orders = trading.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))
    open_order_symbols = {o.symbol.upper() for o in open_orders if getattr(o, "symbol", None)}

    def blocked(sym: str) -> bool:
        s = sym.upper()
        return (s in existing_positions) or (s in open_order_symbols)

    allowed = [t for t in targets if not blocked(t.ticker)]
    if not allowed:
        print("All targets already have positions/orders; nothing to do.")
        return

    n_budget, per_trade = _calc_per_trade(
        cash_available=cash_avail,
        max_buys=args.max_buys,
        notional=None if args.daily_budget is not None else float(args.notional),
        daily_budget=args.daily_budget,
    )
    n = min(len(allowed), n_budget)
    if n <= 0:
        if args.daily_budget is not None:
            print(f"Insufficient available cash to trade. available=${cash_avail:.2f}")
        else:
            print(f"Insufficient available cash to trade. available=${cash_avail:.2f}, need >= ${per_trade:.2f}")
        return

    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    submit = allowed[:n]

    if args.daily_budget is not None:
        print(
            f"Account cash_available≈${cash_avail:.2f}. Submitting {len(submit)} bracket buy(s) "
            f"at ~${per_trade:.2f} each (daily_budget=${float(args.daily_budget):.2f}, max_buys={int(args.max_buys)})."
        )
    else:
        print(
            f"Account cash_available≈${cash_avail:.2f}. Submitting {len(submit)} bracket buy(s) "
            f"at ~${per_trade:.2f} target each (whole shares)."
        )
    print(f"Executor: {EXECUTOR_VERSION}")
    print(f"Mode: {'PAPER' if args.paper else 'LIVE'}  Dry-run: {bool(args.dry_run)}")

    cash_remaining = float(cash_avail)
    for r in submit:
        sym = r.ticker.upper()
        quotes = _fetch_market_quotes(key, secret, [sym])
        snap = quotes.get(sym, QuoteSnap())
        entry = _entry_limit_price(snap)
        if entry is None or entry <= 0:
            print(f"SKIP {r.ticker}: no live quote for limit entry and bracket legs.")
            continue

        qty = _qty_for_bracket(target_dollars=per_trade, price=float(entry), cash_cap=cash_remaining)
        if qty <= 0:
            print(
                f"SKIP {r.ticker}: cannot afford 1 share at limit ${entry:.2f} "
                f"(target ${per_trade:.2f}/slot, cash_remaining ${cash_remaining:.2f})."
            )
            continue

        est_cost = qty * float(entry)
        if est_cost > cash_remaining:
            print(f"SKIP {r.ticker}: need ~${est_cost:.2f} for {qty} sh but cash_remaining≈${cash_remaining:.2f}.")
            continue

        brackets = _bracket_prices(
            float(entry),
            take_profit_pct=float(args.take_profit),
            stop_loss_pct=float(args.stop_loss),
        )
        if brackets is None:
            print(f"SKIP {r.ticker}: invalid bracket prices (entry=${entry:.2f}).")
            continue
        tp, sl = brackets

        if r.prior_close and r.prior_close > 0:
            drift = abs(float(entry) - float(r.prior_close)) / float(r.prior_close)
            if drift >= 0.005:
                print(
                    f"  {r.ticker}: entry ${entry:.2f} vs plan prior_close ${r.prior_close:.2f} "
                    f"({drift * 100:.1f}% drift)"
                )

        client_order_id = f"stock_ai_{now}_{r.ticker}"
        order = LimitOrderRequest(
            symbol=r.ticker,
            qty=float(qty),
            limit_price=float(entry),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=tp),
            stop_loss=StopLossRequest(stop_price=sl),
            client_order_id=client_order_id,
        )

        print(
            f"BUY {r.ticker} qty={qty} limit=${entry:.2f} (~${est_cost:.2f}) "
            f"bracket(tp={tp}, sl={sl}) id={client_order_id}"
        )
        if args.dry_run:
            cash_remaining -= est_cost
            continue

        try:
            resp = trading.submit_order(order_data=order)
            oid = getattr(resp, "id", None)
            print(f"  submitted order_id={oid}")
            cash_remaining -= est_cost
        except Exception as exc:
            print(f"  ERROR submitting {r.ticker}: {exc}")


if __name__ == "__main__":
    main()

