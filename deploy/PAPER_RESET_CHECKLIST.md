# Paper account reset checklist (Linux)

**One command (preferred):** after this commit is on `origin/main`:

```bash
cd /opt/stock_ai && git pull && bash deploy/update_and_deploy.sh
```

Options:

```bash
bash deploy/update_and_deploy.sh --live-run      # also force a paper trade now
bash deploy/update_and_deploy.sh --skip-compute  # skip compute_worker --once
bash deploy/update_and_deploy.sh --skip-pull     # local tree only
```

Manual steps below if you prefer not to use the script.

## 1) Confirm which Alpaca paper account the server uses

```bash
cd /opt/stock_ai
sudo bash -c 'set -a && source /etc/stock-ai/stock-ai.env && set +a && \
  /opt/stock_ai/.venv/bin/python deploy/verify_alpaca.py'
```

Expect `OK — account:` with equity near your paper funding (e.g. ~$6000).  
If equity is ~$0 or cash is weirdly negative with almost no positions, switch keys or reset paper.

## 2) Re-write keys if needed (new / reset paper account)

```bash
sudo /opt/stock_ai/.venv/bin/python deploy/setup_alpaca_env.py
# or:
sudo /opt/stock_ai/.venv/bin/python deploy/setup_alpaca_env.py --from ./alpaca_paper.env
```

Paper keys only — `hybrid_morning.py` / trade unit still use `--paper`.

## 3) Clear stale open orders (optional manual)

In Alpaca Paper UI: **Orders → Open** → cancel leftover `stock_ai_*` buys.  
The morning job also cancels stale entry orders when `--clear-stale-orders` is on.

## 4) Pull code and install units

```bash
cd /opt/stock_ai
git pull
source .venv/bin/activate
pip install -r requirements.txt

sudo cp deploy/systemd/stock-ai-*.service /etc/systemd/system/
sudo cp deploy/systemd/stock-ai-*.timer /etc/systemd/system/
sudo systemctl daemon-reload

sudo timedatectl set-timezone America/New_York   # if not already
sudo systemctl restart stock-ai-compute.service
sudo systemctl enable --now stock-ai-trade.timer
```

## 5) Refresh the trade plan once

```bash
cd /opt/stock_ai
source .venv/bin/activate
python compute_worker.py --once
head -20 out/trade_plan.csv
```

## 6) Dry-run the morning hybrid job

```bash
sudo bash -c 'set -a && source /etc/stock-ai/stock-ai.env && set +a && \
  /opt/stock_ai/.venv/bin/python /opt/stock_ai/hybrid_morning.py --paper \
  --daily-budget 4000 --max-buys 20 --take-profit 0.015 --stop-loss 0.015 --dry-run'
```

Confirm: several affordable names, `approved_basket.csv` written, no flood of `qty=0` skips.

## 7) Force a live paper run (market hours)

```bash
sudo systemctl start stock-ai-trade.service
sudo journalctl -u stock-ai-trade.service -n 80 --no-pager
```

Timer alone fires **Mon–Fri 09:35** America/New_York (once per open).
