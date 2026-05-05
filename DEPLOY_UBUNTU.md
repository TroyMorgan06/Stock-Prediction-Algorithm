## Ubuntu Server deployment (side PC)

### Recommended folder layout

```bash
sudo mkdir -p /opt/stock_ai
sudo chown -R $USER:$USER /opt/stock_ai
cd /opt/stock_ai
```

Copy your repo contents into `/opt/stock_ai`.

### Python + venv

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### Secrets file

Create `/opt/stock_ai/.env`:

```bash
FINNHUB_API_KEY=your_key_here
```

(`reddit_ingest.py` uses StockTwits now and needs no credentials.)

### Universe (S&P 500 / larger sets)

- Edit `config.py`:
  - `UNIVERSE_FILE` points to a newline-separated list (default `universes/sp500.txt`).
  - `MAX_TICKERS` caps how many tickers you run each cycle.

**Important**: do NOT start with “S&P 500 + all Nasdaq” on day 1.
Yahoo/StockTwits will throttle you and your box will spend all day downloading.
Start with **50–200** liquid names, then expand once stable.

### Start services (dashboard + compute worker)

Copy unit files:

```bash
sudo cp deploy/systemd/stock-ai-*.service /etc/systemd/system/
sudo cp deploy/systemd/stock-ai-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

Enable and start:

```bash
sudo systemctl enable --now stock-ai-compute.service
sudo systemctl enable --now stock-ai-dashboard.service
sudo systemctl enable --now stock-ai-news.timer
sudo systemctl enable --now stock-ai-social.timer
sudo systemctl enable --now stock-ai-backtest.timer
```

Logs:

```bash
sudo journalctl -u stock-ai-compute.service -f
sudo journalctl -u stock-ai-dashboard.service -f
sudo journalctl -u stock-ai-news.service -f
sudo journalctl -u stock-ai-social.service -f
sudo journalctl -u stock-ai-backtest.service -f
```

### Open the dashboard from another PC

On the Ubuntu box:

```bash
hostname -I
```

From the other PC:

`http://<ubuntu_ip>:8765/`

If blocked, allow port 8765 in your firewall (`ufw allow 8765/tcp`).

### Suggested periodic jobs

- **Compute worker**: continuously refreshes `out/predictions.json` and `out/trade_plan.csv`.
- **News ingest**: every 6 hours (timer) to grow `sentiment_news.csv`.
- **Social ingest**: every 6 hours (timer) to grow `sentiment_reddit.csv` (StockTwits).
- **Nightly backtest**: runs `main.py` (research) at 02:30.

### Other strong suggestions

- Keep `MAX_TICKERS` reasonable; you can rotate the universe weekly/monthly.
- Add a “paper ledger” CSV for actual outcomes (entry/exit) before scaling up.
- If you later want real long/short automation, consider a broker with an API (IBKR/Alpaca).

