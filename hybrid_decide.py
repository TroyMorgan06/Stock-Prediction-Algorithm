"""
Hybrid morning decide — Swing Growth strategy.

Local trade plan + SPY uptrend filter + risk/conviction sizing (+ optional LLM)
→ out/approved_basket.csv

See deploy/STRATEGY.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

from alpaca_executor import (
    PlanRow,
    QuoteSnap,
    _cash_available,
    _entry_limit_price,
    _exit_on_alpaca_auth_failure,
    _f,
    _fetch_market_quotes,
    _notional_to_qty,
    iter_long_candidates,
    load_plan_rows,
)
from config import (
    APPROVED_BASKET_CSV,
    HYBRID_LLM_BASE_URL,
    HYBRID_LLM_MODEL,
    MORNING_CANDIDATE_POOL,
    MORNING_DAILY_BUDGET,
    MORNING_DEPLOY_FRACTION,
    MORNING_MAX_BUYS,
    MORNING_MAX_PORTFOLIO_HEAT,
    MORNING_MAX_SHARE_PRICE,
    MORNING_REQUIRE_SPY_UPTREND,
    MORNING_RISK_PER_TRADE,
    MORNING_SPY_SMA_FAST,
    MORNING_SPY_SMA_SLOW,
    MORNING_STOP_LOSS,
    OUTPUT_DIR,
    START,
    TRADE_PLAN_CSV,
)


@dataclass(frozen=True)
class AffordableName:
    ticker: str
    rank: int
    entry: float
    qty: int
    est_cost: float
    budget: float
    prior_close: Optional[float]
    pred_hint: str = ""


# Mild conviction tilt (index 0 = top rank). Normalized later against deploy budget.
_CONVICTION = (1.35, 1.20, 1.10, 1.00, 0.95, 0.85, 0.80, 0.75)


def _llm_api_key() -> str:
    return (os.getenv("HYBRID_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()


def _llm_base_url() -> str:
    return (os.getenv("HYBRID_LLM_BASE_URL") or HYBRID_LLM_BASE_URL).rstrip("/")


def _llm_model() -> str:
    return (os.getenv("HYBRID_LLM_MODEL") or HYBRID_LLM_MODEL).strip()


def _account_equity(acct) -> float:
    for attr in ("equity", "portfolio_value", "last_equity"):
        fv = _f(getattr(acct, attr, None))
        if fv is not None and fv > 0:
            return float(fv)
    return max(_cash_available(acct), 0.0)


def spy_uptrend_ok(
    *,
    fast: int = MORNING_SPY_SMA_FAST,
    slow: int = MORNING_SPY_SMA_SLOW,
) -> Tuple[bool, str]:
    """Long-only when SPY close > SMA_fast and SMA_slow (and fast > slow)."""
    try:
        from data import _fetch_daily

        df = _fetch_daily("SPY", START)
        if df is None or df.empty or "Close" not in df.columns:
            return False, "SPY data unavailable"
        close = df["Close"].astype(float)
        if len(close) < int(slow) + 5:
            return False, f"SPY history too short ({len(close)} bars)"
        sma_f = float(close.rolling(int(fast)).mean().iloc[-1])
        sma_s = float(close.rolling(int(slow)).mean().iloc[-1])
        last = float(close.iloc[-1])
        ok = last > sma_f and last > sma_s and sma_f >= sma_s
        detail = f"SPY={last:.2f} SMA{fast}={sma_f:.2f} SMA{slow}={sma_s:.2f}"
        return ok, detail
    except Exception as exc:
        return False, f"SPY regime check failed: {exc}"


def write_approved_basket(path: str, rows: List[dict]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    headers = ["rank", "side", "ticker", "budget_dollars", "prior_close", "notes"]
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for i, r in enumerate(rows, start=1):
            w.writerow(
                {
                    "rank": r.get("rank", i),
                    "side": r.get("side", "LONG"),
                    "ticker": r.get("ticker"),
                    "budget_dollars": r.get("budget_dollars"),
                    "prior_close": r.get("prior_close", ""),
                    "notes": r.get("notes", ""),
                }
            )
    os.replace(tmp, path)


def build_swing_basket(
    *,
    plan_rows: List[PlanRow],
    quotes: Dict[str, QuoteSnap],
    equity: float,
    deploy_budget: float,
    blocked: Set[str],
    max_buys: int,
    max_share_price: float,
    stop_loss_pct: float,
    risk_per_trade: float,
    max_heat: float,
) -> Tuple[List[AffordableName], Dict[str, int]]:
    """
    Risk-aware whole-share basket:
      - per-name $ cap ≈ min(equal_slot * conviction, risk_dollars / stop_pct)
      - total deploy <= deploy_budget
      - portfolio heat ≈ sum(cost * stop_pct) <= equity * max_heat
    """
    skips = {"blocked": 0, "no_price": 0, "too_expensive": 0, "qty0": 0, "over_cash": 0, "heat": 0}
    out: List[AffordableName] = []
    cash_left = float(deploy_budget)
    heat_left = float(equity) * float(max_heat)
    equal_slot = float(deploy_budget) / max(1, int(max_buys))
    risk_dollars = float(equity) * float(risk_per_trade)
    risk_cap = risk_dollars / max(float(stop_loss_pct), 1e-6)

    candidates: List[Tuple[PlanRow, float]] = []
    for r in plan_rows:
        sym = r.ticker.upper()
        if sym in blocked:
            skips["blocked"] += 1
            continue
        entry = _entry_limit_price(quotes.get(sym, QuoteSnap()), fallback=r.prior_close)
        if entry is None or entry <= 0:
            skips["no_price"] += 1
            continue
        if float(entry) > float(max_share_price) and float(entry) > equal_slot:
            # Still allow if one share fits risk/equal slot path below
            pass
        candidates.append((r, float(entry)))

    for i, (r, entry) in enumerate(candidates):
        if len(out) >= int(max_buys):
            break
        w = _CONVICTION[i] if i < len(_CONVICTION) else 0.7
        target = min(equal_slot * float(w), risk_cap, cash_left)
        if entry > float(max_share_price) and target < entry:
            skips["too_expensive"] += 1
            continue
        qty = _notional_to_qty(budget_dollars=target, price=entry)
        if qty <= 0 and entry <= cash_left and entry <= float(max_share_price):
            qty = 1
            target = entry
        if qty <= 0:
            skips["qty0"] += 1
            continue
        est = qty * entry
        if est > cash_left:
            skips["over_cash"] += 1
            continue
        trade_heat = est * float(stop_loss_pct)
        if trade_heat > heat_left:
            skips["heat"] += 1
            continue
        out.append(
            AffordableName(
                ticker=r.ticker.upper(),
                rank=int(r.rank),
                entry=entry,
                qty=qty,
                est_cost=est,
                budget=float(target),
                prior_close=r.prior_close,
            )
        )
        cash_left -= est
        heat_left -= trade_heat

    return out, skips


def rule_based_pick(affordable: List[AffordableName], max_buys: int) -> List[AffordableName]:
    return affordable[: max(0, int(max_buys))]


def llm_pick(
    affordable: List[AffordableName],
    *,
    max_buys: int,
    cash_available: float,
    run_budget: float,
) -> Optional[List[str]]:
    key = _llm_api_key()
    if not key or not affordable:
        return None

    payload_names = [
        {
            "ticker": a.ticker,
            "rank": a.rank,
            "price": round(a.entry, 2),
            "qty": a.qty,
            "est_cost": round(a.est_cost, 2),
        }
        for a in affordable
    ]
    system = (
        "You are a conservative swing-trading assistant for a small account. "
        "Pick at most max_buys tickers. Prefer higher plan rank (lower number), "
        "liquid names, and skip anything that looks like a low-quality lottery ticket. "
        'Respond with ONLY JSON: {"tickers": ["AAA"], "reason": "..."}.'
    )
    user = json.dumps(
        {
            "cash_available": round(cash_available, 2),
            "run_budget": round(run_budget, 2),
            "max_buys": int(max_buys),
            "candidates": payload_names,
        },
        indent=2,
    )
    body = {
        "model": _llm_model(),
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        f"{_llm_base_url()}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"WARN: LLM request failed ({exc}); using rule-based basket.")
        return None

    try:
        content = raw["choices"][0]["message"]["content"]
        parsed: Dict[str, Any] = json.loads(content) if isinstance(content, str) else content
        tickers = [str(t).upper().strip() for t in (parsed.get("tickers") or []) if t]
        reason = parsed.get("reason") or ""
        if reason:
            print(f"LLM reason: {reason}")
        allowed = {a.ticker for a in affordable}
        filtered = [t for t in tickers if t in allowed][: int(max_buys)]
        return filtered or None
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"WARN: LLM response parse failed ({exc}); using rule-based basket.")
        return None


def decide(
    *,
    plan_csv: str,
    basket_csv: str,
    paper: bool,
    daily_budget: float,
    max_buys: int,
    candidate_pool: int,
    max_share_price: float = MORNING_MAX_SHARE_PRICE,
    stop_loss_pct: float = MORNING_STOP_LOSS,
    risk_per_trade: float = MORNING_RISK_PER_TRADE,
    deploy_fraction: float = MORNING_DEPLOY_FRACTION,
    require_spy_uptrend: bool = MORNING_REQUIRE_SPY_UPTREND,
    dry_run: bool = False,
) -> List[dict]:
    key = (os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY") or "").strip()
    secret = (os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET") or "").strip()
    if not key or not secret:
        raise SystemExit("Missing Alpaca credentials (APCA_API_KEY_ID / APCA_API_SECRET_KEY).")

    if require_spy_uptrend:
        ok, detail = spy_uptrend_ok()
        print(f"hybrid_decide: SPY regime → {'ON' if ok else 'OFF'} ({detail})")
        if not ok:
            write_approved_basket(basket_csv, [])
            print(f"Wrote empty {basket_csv} (no new buys in down/sideways market).")
            return []

    rows = load_plan_rows(plan_csv)
    longs = iter_long_candidates(rows, candidate_pool)
    if not longs:
        write_approved_basket(basket_csv, [])
        print(f"No LONG rows in {plan_csv}; empty basket.")
        return []

    trading = TradingClient(key, secret, paper=bool(paper))
    try:
        acct = trading.get_account()
    except Exception as exc:
        _exit_on_alpaca_auth_failure(exc, paper=bool(paper))
        raise

    equity = _account_equity(acct)
    usable = _cash_available(acct)
    raw_cash = float(_f(getattr(acct, "cash", None)) or 0.0)
    raw_bp = float(_f(getattr(acct, "buying_power", None)) or 0.0)
    run_budget = min(float(daily_budget), float(equity) * float(deploy_fraction), float(usable))
    if run_budget <= 0 or max_buys <= 0:
        raise SystemExit(
            f"Insufficient funds. equity≈${equity:.2f} usable≈${usable:.2f} "
            f"cash≈${raw_cash:.2f} bp≈${raw_bp:.2f}"
        )

    positions = {p.symbol.upper() for p in trading.get_all_positions()}
    open_orders = list(trading.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN)))
    open_syms = {o.symbol.upper() for o in open_orders if getattr(o, "symbol", None)}
    blocked = positions | open_syms

    print(
        f"hybrid_decide: SwingGrowth equity≈${equity:.2f} usable≈${usable:.2f} "
        f"deploy_budget=${run_budget:.2f} max_buys={max_buys} stop={stop_loss_pct:.1%} "
        f"risk/trade={risk_per_trade:.1%} plan_longs={len(longs)} blocked={len(blocked)} "
        f"llm={'yes' if _llm_api_key() else 'no'}"
    )

    quotes = _fetch_market_quotes(key, secret, [r.ticker for r in longs])
    affordable, skips = build_swing_basket(
        plan_rows=longs,
        quotes=quotes,
        equity=equity,
        deploy_budget=run_budget,
        blocked=blocked,
        max_buys=max(int(max_buys) * 2, int(max_buys)),
        max_share_price=float(max_share_price),
        stop_loss_pct=float(stop_loss_pct),
        risk_per_trade=float(risk_per_trade),
        max_heat=float(MORNING_MAX_PORTFOLIO_HEAT),
    )
    print(f"hybrid_decide: {len(affordable)} swing candidates (skips: {skips}).")
    if not affordable:
        print("Affordability detail (first 12 LONGs):")
        equal_slot = run_budget / max(1, int(max_buys))
        for r in longs[:12]:
            px = _entry_limit_price(quotes.get(r.ticker.upper(), QuoteSnap()), fallback=r.prior_close)
            print(
                f"  {r.ticker}: price={px} prior={r.prior_close} "
                f"slot≈{equal_slot:.0f} blocked={r.ticker.upper() in blocked}"
            )
        write_approved_basket(basket_csv, [])
        print(f"Wrote empty {basket_csv} (zero affordable names).")
        return []

    llm_order = llm_pick(
        affordable,
        max_buys=max_buys,
        cash_available=usable,
        run_budget=run_budget,
    )
    by_ticker = {a.ticker: a for a in affordable}
    if llm_order:
        picked = [by_ticker[t] for t in llm_order if t in by_ticker]
        mode = "llm"
    else:
        picked = rule_based_pick(affordable, max_buys)
        mode = "rules"

    # Re-size picked names with conviction order 1..n under remaining budget
    resized: List[AffordableName] = []
    cash_left = float(run_budget)
    heat_left = float(equity) * float(MORNING_MAX_PORTFOLIO_HEAT)
    equal_slot = float(run_budget) / max(1, len(picked))
    risk_cap = (float(equity) * float(risk_per_trade)) / max(float(stop_loss_pct), 1e-6)
    for i, a in enumerate(picked):
        w = _CONVICTION[i] if i < len(_CONVICTION) else 0.7
        target = min(equal_slot * float(w), risk_cap, cash_left)
        qty = _notional_to_qty(budget_dollars=target, price=a.entry)
        if qty <= 0 and a.entry <= cash_left and a.entry <= float(max_share_price):
            qty = 1
            target = a.entry
        if qty <= 0:
            continue
        est = qty * a.entry
        heat = est * float(stop_loss_pct)
        if est > cash_left or heat > heat_left:
            continue
        resized.append(
            AffordableName(
                ticker=a.ticker,
                rank=i + 1,
                entry=a.entry,
                qty=qty,
                est_cost=est,
                budget=float(target),
                prior_close=a.prior_close,
            )
        )
        cash_left -= est
        heat_left -= heat

    if not resized:
        write_approved_basket(basket_csv, [])
        print(f"Wrote empty {basket_csv} (resize produced nothing).")
        return []

    out_rows: List[dict] = []
    for a in resized:
        out_rows.append(
            {
                "rank": a.rank,
                "side": "LONG",
                "ticker": a.ticker,
                "budget_dollars": round(a.budget, 2),
                "prior_close": a.prior_close if a.prior_close is not None else "",
                "notes": (
                    f"swing:{mode}; entry≈{a.entry:.2f}; qty≈{a.qty}; "
                    f"stop={stop_loss_pct:.1%}"
                ),
            }
        )

    if dry_run:
        print(
            f"DRY-RUN basket ({len(out_rows)}, ~${sum(a.est_cost for a in resized):.0f}): "
            + ", ".join(r["ticker"] for r in out_rows)
        )
    write_approved_basket(basket_csv, out_rows)
    print(f"Wrote {basket_csv} ({len(out_rows)} names, mode={mode})")
    return out_rows


def main() -> None:
    p = argparse.ArgumentParser(description="Swing Growth: build approved_basket.csv")
    p.add_argument("--plan-csv", default=os.path.join(OUTPUT_DIR, TRADE_PLAN_CSV))
    p.add_argument("--basket-csv", default=os.path.join(OUTPUT_DIR, APPROVED_BASKET_CSV))
    p.add_argument("--paper", action="store_true")
    p.add_argument("--daily-budget", type=float, default=MORNING_DAILY_BUDGET)
    p.add_argument("--max-buys", type=int, default=MORNING_MAX_BUYS)
    p.add_argument("--candidate-pool", type=int, default=MORNING_CANDIDATE_POOL)
    p.add_argument("--max-share-price", type=float, default=MORNING_MAX_SHARE_PRICE)
    p.add_argument("--stop-loss", type=float, default=MORNING_STOP_LOSS)
    p.add_argument("--risk-per-trade", type=float, default=MORNING_RISK_PER_TRADE)
    p.add_argument("--deploy-fraction", type=float, default=MORNING_DEPLOY_FRACTION)
    p.add_argument(
        "--require-spy-uptrend",
        action="store_true",
        default=MORNING_REQUIRE_SPY_UPTREND,
    )
    p.add_argument(
        "--no-require-spy-uptrend",
        action="store_false",
        dest="require_spy_uptrend",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    decide(
        plan_csv=args.plan_csv,
        basket_csv=args.basket_csv,
        paper=bool(args.paper),
        daily_budget=float(args.daily_budget),
        max_buys=int(args.max_buys),
        candidate_pool=int(args.candidate_pool),
        max_share_price=float(args.max_share_price),
        stop_loss_pct=float(args.stop_loss),
        risk_per_trade=float(args.risk_per_trade),
        deploy_fraction=float(args.deploy_fraction),
        require_spy_uptrend=bool(args.require_spy_uptrend),
        dry_run=bool(args.dry_run),
    )


if __name__ == "__main__":
    main()
