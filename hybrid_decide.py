"""
Hybrid morning decide: local trade plan + affordability rules (+ optional LLM) → approved basket.

Writes out/approved_basket.csv for alpaca_executor / hybrid_morning.

  python hybrid_decide.py --paper --daily-budget 2000 --max-buys 12
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

from alpaca_executor import (
    PlanRow,
    QuoteSnap,
    _cash_available,
    _entry_limit_price,
    _exit_on_alpaca_auth_failure,
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
    MORNING_MAX_BUYS,
    OUTPUT_DIR,
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


def _llm_api_key() -> str:
    return (
        os.getenv("HYBRID_LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip()


def _llm_base_url() -> str:
    return (os.getenv("HYBRID_LLM_BASE_URL") or HYBRID_LLM_BASE_URL).rstrip("/")


def _llm_model() -> str:
    return (os.getenv("HYBRID_LLM_MODEL") or HYBRID_LLM_MODEL).strip()


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


def build_affordable(
    *,
    plan_rows: List[PlanRow],
    quotes: Dict[str, QuoteSnap],
    slot_budget: float,
    cash_cap: float,
    blocked: Set[str],
    max_buys: int,
) -> List[AffordableName]:
    out: List[AffordableName] = []
    cash_left = float(cash_cap)
    for r in plan_rows:
        if len(out) >= max_buys:
            break
        sym = r.ticker.upper()
        if sym in blocked:
            continue
        entry = _entry_limit_price(quotes.get(sym, QuoteSnap()))
        if entry is None or entry <= 0:
            continue
        qty = _notional_to_qty(budget_dollars=slot_budget, price=float(entry))
        if qty <= 0:
            continue
        est = qty * float(entry)
        if est > cash_left:
            continue
        out.append(
            AffordableName(
                ticker=sym,
                rank=int(r.rank),
                entry=float(entry),
                qty=qty,
                est_cost=est,
                budget=float(slot_budget),
                prior_close=r.prior_close,
            )
        )
        cash_left -= est
    return out


def rule_based_pick(affordable: List[AffordableName], max_buys: int) -> List[AffordableName]:
    """Keep plan rank order (already sorted); take first max_buys."""
    return affordable[: max(0, int(max_buys))]


def llm_pick(
    affordable: List[AffordableName],
    *,
    max_buys: int,
    cash_available: float,
    run_budget: float,
) -> Optional[List[str]]:
    """
    Ask an OpenAI-compatible chat API to reorder/subset tickers.
    Returns ticker list or None on failure (caller falls back to rules).
    """
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
        "You are a conservative paper-trading assistant. "
        "Pick at most max_buys tickers from the candidate list. "
        "Prefer higher plan rank (lower rank number) and affordable whole-share names. "
        "Respond with ONLY JSON: {\"tickers\": [\"AAA\", \"BBB\"], \"reason\": \"...\"}."
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
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
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
        if not filtered:
            print("WARN: LLM returned no valid tickers; using rule-based basket.")
            return None
        return filtered
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
    dry_run: bool = False,
) -> List[dict]:
    key = (os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY") or "").strip()
    secret = (os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET") or "").strip()
    if not key or not secret:
        raise SystemExit("Missing Alpaca credentials (APCA_API_KEY_ID / APCA_API_SECRET_KEY).")

    rows = load_plan_rows(plan_csv)
    longs = iter_long_candidates(rows, candidate_pool)
    if not longs:
        raise SystemExit(f"No LONG rows in {plan_csv}")

    trading = TradingClient(key, secret, paper=bool(paper))
    try:
        acct = trading.get_account()
    except Exception as exc:
        _exit_on_alpaca_auth_failure(exc, paper=bool(paper))
        raise

    cash = _cash_available(acct)
    run_budget = min(float(daily_budget), float(cash))
    if run_budget <= 0 or max_buys <= 0:
        raise SystemExit(f"Insufficient cash or max_buys. cash≈${cash:.2f}")

    slot = run_budget / float(max_buys)
    positions = {p.symbol.upper() for p in trading.get_all_positions()}
    open_orders = list(trading.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN)))
    open_syms = {o.symbol.upper() for o in open_orders if getattr(o, "symbol", None)}
    blocked = positions | open_syms

    print(
        f"hybrid_decide: cash≈${cash:.2f} run_budget=${run_budget:.2f} "
        f"slot≈${slot:.2f} max_buys={max_buys} plan_longs={len(longs)} "
        f"blocked={len(blocked)} llm={'yes' if _llm_api_key() else 'no'}"
    )

    quotes = _fetch_market_quotes(key, secret, [r.ticker for r in longs])
    affordable = build_affordable(
        plan_rows=longs,
        quotes=quotes,
        slot_budget=slot,
        cash_cap=run_budget,
        blocked=blocked,
        max_buys=max(max_buys * 3, max_buys),  # over-fetch for LLM to choose from
    )
    print(f"hybrid_decide: {len(affordable)} affordable whole-share candidates after filters.")
    if not affordable:
        raise SystemExit(
            "Zero affordable names (raise --daily-budget, lower --max-buys, or refresh trade plan)."
        )

    llm_order = llm_pick(
        affordable,
        max_buys=max_buys,
        cash_available=cash,
        run_budget=run_budget,
    )
    by_ticker = {a.ticker: a for a in affordable}
    if llm_order:
        picked = [by_ticker[t] for t in llm_order if t in by_ticker]
        mode = "llm"
    else:
        picked = rule_based_pick(affordable, max_buys)
        mode = "rules"

    if not picked:
        raise SystemExit("Decide produced an empty basket.")

    out_rows: List[dict] = []
    for i, a in enumerate(picked, start=1):
        out_rows.append(
            {
                "rank": i,
                "side": "LONG",
                "ticker": a.ticker,
                "budget_dollars": round(a.budget, 2),
                "prior_close": a.prior_close if a.prior_close is not None else "",
                "notes": f"hybrid:{mode}; entry≈{a.entry:.2f}; qty≈{a.qty}",
            }
        )

    if dry_run:
        print(f"DRY-RUN basket ({len(out_rows)}): " + ", ".join(r["ticker"] for r in out_rows))
    write_approved_basket(basket_csv, out_rows)
    print(f"Wrote {basket_csv} ({len(out_rows)} names, mode={mode})")
    return out_rows


def main() -> None:
    p = argparse.ArgumentParser(description="Build out/approved_basket.csv from trade plan + hybrid rules/LLM.")
    p.add_argument("--plan-csv", default=os.path.join(OUTPUT_DIR, TRADE_PLAN_CSV))
    p.add_argument("--basket-csv", default=os.path.join(OUTPUT_DIR, APPROVED_BASKET_CSV))
    p.add_argument("--paper", action="store_true")
    p.add_argument("--daily-budget", type=float, default=MORNING_DAILY_BUDGET)
    p.add_argument("--max-buys", type=int, default=MORNING_MAX_BUYS)
    p.add_argument("--candidate-pool", type=int, default=MORNING_CANDIDATE_POOL)
    p.add_argument("--dry-run", action="store_true", help="Still write basket; label as dry-run in logs.")
    args = p.parse_args()

    decide(
        plan_csv=args.plan_csv,
        basket_csv=args.basket_csv,
        paper=bool(args.paper),
        daily_budget=float(args.daily_budget),
        max_buys=int(args.max_buys),
        candidate_pool=int(args.candidate_pool),
        dry_run=bool(args.dry_run),
    )


if __name__ == "__main__":
    main()
