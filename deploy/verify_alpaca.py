#!/usr/bin/env python3
"""Minimal Alpaca auth check. Run as root so it can read /etc/stock-ai/stock-ai.env if needed."""

from __future__ import annotations

import os
import sys


def main() -> None:
    print("verify_alpaca: starting", flush=True)

    key = (os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY") or "").strip()
    secret = (os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_API_SECRET") or "").strip()
    print(f"verify_alpaca: key_id len={len(key)} secret len={len(secret)}", flush=True)
    if not key or not secret:
        print(
            "ERROR: Missing APCA_API_KEY_ID / APCA_API_SECRET_KEY in environment.\n"
            "Run: sudo bash -c 'set -a && source /etc/stock-ai/stock-ai.env && set +a && "
            f"{sys.executable} {__file__}'",
            flush=True,
        )
        sys.exit(2)

    try:
        from alpaca.trading.client import TradingClient
    except ImportError as exc:
        print(f"ERROR: alpaca-py not installed in this Python: {exc}", flush=True)
        print(f"Using interpreter: {sys.executable}", flush=True)
        sys.exit(3)

    paper = "--live" not in sys.argv
    print(f"verify_alpaca: calling get_account() paper={paper} ...", flush=True)
    client = TradingClient(key, secret, paper=paper)
    acct = client.get_account()
    print("OK — account:", acct, flush=True)


if __name__ == "__main__":
    main()
