from __future__ import annotations

import os
from typing import List, Optional

from config import MAX_TICKERS, TICKERS, TICKERS_RUN, UNIVERSE_FILE


def _read_ticker_file(path: str) -> List[str]:
    out: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            out.append(s.upper())
    # de-dupe preserve order
    seen = set()
    deduped: List[str] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def get_universe() -> List[str]:
    """
    Returns the tickers to run for compute/backtest/ingest.

    Priority:
      1) explicit `TICKERS_RUN` list (if set)
      2) `UNIVERSE_FILE` (if present)
      3) fallback `TICKERS`
    """
    if TICKERS_RUN is not None:
        base = [str(t).upper() for t in TICKERS_RUN]
    elif UNIVERSE_FILE:
        p = UNIVERSE_FILE
        if not os.path.isabs(p):
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), p)
        if os.path.isfile(p):
            base = _read_ticker_file(p)
        else:
            base = [str(t).upper() for t in TICKERS]
    else:
        base = [str(t).upper() for t in TICKERS]

    return base[: int(MAX_TICKERS)]

