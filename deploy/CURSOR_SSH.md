# Cursor ↔ Linux server (hybrid morning trades)

Fully auto weekday trades run on the box via **systemd** (`stock-ai-trade.timer` → `hybrid_morning.py` at **09:35 America/New_York**). Cursor is optional: use it to inspect, dry-run, or force a run.

## 1) Reach the server

**Option A — LAN SSH**

```bash
ssh YOUR_USER@LINUX_LAN_IP
```

**Option B — Tailscale (recommended off-home)**

1. Install Tailscale on Ubuntu and on the Windows/Cursor machine.
2. SSH via the Tailscale hostname/IP:

```bash
ssh YOUR_USER@stock-ai-box
```

Ensure your SSH key is authorized on the server (`~/.ssh/authorized_keys`).

## 2) From Cursor (Agent / terminal) — one-command deploy

On the Linux box (or over SSH):

```bash
cd /opt/stock_ai && git pull && bash deploy/update_and_deploy.sh
```

Force a paper trade in the same pass:

```bash
cd /opt/stock_ai && git pull && bash deploy/update_and_deploy.sh --live-run
```

## 3) From Cursor — dry-run only

```bash
ssh YOUR_USER@LINUX_HOST 'cd /opt/stock_ai && sudo bash -c "
set -a && source /etc/stock-ai/stock-ai.env && set +a &&
/opt/stock_ai/.venv/bin/python hybrid_morning.py --paper \
  --daily-budget 2000 --max-buys 12 --take-profit 0.015 --stop-loss 0.015 --dry-run
"'
```

Inspect basket:

```bash
ssh YOUR_USER@LINUX_HOST 'head -30 /opt/stock_ai/out/approved_basket.csv; head -20 /opt/stock_ai/out/trade_plan.csv'
```

## 4) Force a live paper morning run

```bash
ssh YOUR_USER@LINUX_HOST 'sudo systemctl start stock-ai-trade.service && sudo journalctl -u stock-ai-trade.service -n 80 --no-pager'
```

Or run the script directly (same flags as the unit):

```bash
ssh YOUR_USER@LINUX_HOST 'cd /opt/stock_ai && sudo bash -c "
set -a && source /etc/stock-ai/stock-ai.env && set +a &&
/opt/stock_ai/.venv/bin/python hybrid_morning.py --paper \
  --daily-budget 2000 --max-buys 12 --take-profit 0.015 --stop-loss 0.015 --clear-stale-orders
"'
```

## 5) Optional LLM hybrid brain

Add to `/etc/stock-ai/stock-ai.env` (then next decide run can use it):

```bash
OPENAI_API_KEY=sk-...
# optional overrides:
# HYBRID_LLM_BASE_URL=https://api.openai.com/v1
# HYBRID_LLM_MODEL=gpt-4o-mini
```

Without a key, `hybrid_decide.py` uses **rule-based** picks (plan rank + affordability). Fully auto still works.

## 6) What Cursor should look at when debugging

| Check | Command / file |
|--------|----------------|
| Timer | `systemctl list-timers stock-ai-trade.timer` |
| Last run | `journalctl -u stock-ai-trade.service -n 100 --no-pager` |
| Plan | `/opt/stock_ai/out/trade_plan.csv` |
| Basket | `/opt/stock_ai/out/approved_basket.csv` |
| Account | `deploy/verify_alpaca.py` with env sourced |

## 7) Autonomy note

Do **not** rely on Cursor being open at 09:35. systemd is the primary path. Use Cursor for analysis, sizing tweaks, and manual overrides.
