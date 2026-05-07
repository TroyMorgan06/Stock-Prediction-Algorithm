## Ubuntu (systemd) setup

This keeps the server running continuously while trading **once per weekday**.

### 1) Put the repo on the server

Example target path used by the unit files: `/opt/stock_ai`

### 2) Create a venv and install deps

```bash
cd /opt/stock_ai
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

### 3) Create the env file (Alpaca keys)

```bash
sudo mkdir -p /etc/stock-ai
sudo cp /opt/stock_ai/deploy/systemd/stock-ai.env.example /etc/stock-ai/stock-ai.env
sudo nano /etc/stock-ai/stock-ai.env
sudo chmod 600 /etc/stock-ai/stock-ai.env
```

### 4) Install the systemd unit files

```bash
sudo cp /opt/stock_ai/deploy/systemd/stock-ai-compute.service /etc/systemd/system/
sudo cp /opt/stock_ai/deploy/systemd/stock-ai-trade.service /etc/systemd/system/
sudo cp /opt/stock_ai/deploy/systemd/stock-ai-trade.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

### 5) Make sure the server timezone matches the timer

The timer is set to `Mon..Fri 09:35` (intended as **America/New_York** market time).

Check timezone:

```bash
timedatectl
```

If needed:

```bash
sudo timedatectl set-timezone America/New_York
```

### 6) Enable + start

```bash
sudo systemctl enable --now stock-ai-compute.service
sudo systemctl enable --now stock-ai-trade.timer
```

### 7) Inspect logs / status

```bash
systemctl status stock-ai-compute.service
systemctl status stock-ai-trade.timer
journalctl -u stock-ai-compute.service -f
journalctl -u stock-ai-trade.service -f
```

### Notes
- `stock-ai-compute.service` keeps refreshing `out/predictions.json` + `out/trade_plan.csv`
- `stock-ai-trade.timer` runs the executor once per weekday; it will **skip** if cash is insufficient or positions/orders already exist.
- The trade unit currently runs **paper trading** (`--paper`) and is configured to deploy **$1000/day split across 10 buys**. When ready for live, remove `--paper` in `stock-ai-trade.service`.

