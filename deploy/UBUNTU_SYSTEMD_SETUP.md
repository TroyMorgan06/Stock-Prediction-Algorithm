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

If bash later says **`'\r': command not found`**, the file was saved with **Windows CRLF** line endings. Fix on the server:

```bash
sudo apt-get update && sudo apt-get install -y dos2unix
sudo dos2unix /etc/stock-ai/stock-ai.env
```

(or `sudo sed -i 's/\r$//' /etc/stock-ai/stock-ai.env`)

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

### Troubleshooting: `401 Unauthorized` / `APIError`

Alpaca returns **401** when the **Key ID + Secret** do not match the **endpoint** you are calling.

- **`stock-ai-trade.service` uses `--paper`**, so the client talks to **paper-api.alpaca.markets**. You must use **Paper Trading** API keys from the Alpaca dashboard (toggle to Paper, then API Keys). **Live keys will not work** with `--paper`, and **paper keys will not work** if you remove `--paper` for live trading.
- In `/etc/stock-ai/stock-ai.env`, use exactly:

  ```bash
  APCA_API_KEY_ID=PKJJ2WPD7YK2WPJUTZ3OMFKYOR
  APCA_API_SECRET_KEY=4LXYG33xUN4BDzzVyANR5Md8zGAzNMCEWw7P1PRGEBhT
  ```

  No `export`, no quotes around values, no spaces around `=`. If you paste from the web UI, watch for accidental line breaks.
- After fixing keys:

  ```bash
  sudo systemctl daemon-reload
  sudo systemctl restart stock-ai-trade.service
  ```

- Quick manual test (same venv as systemd). Prefer the helper script (avoids `sudo` + nested `python -c` quoting issues):

  ```bash
  sudo cp /opt/stock_ai/deploy/verify_alpaca.py /opt/stock_ai/verify_alpaca.py
  sudo chmod +x /opt/stock_ai/verify_alpaca.py
  sudo bash -c 'set -a && source /etc/stock-ai/stock-ai.env && set +a && /opt/stock_ai/.venv/bin/python /opt/stock_ai/verify_alpaca.py'
  ```

  You should see `verify_alpaca: starting` immediately, then key lengths, then `OK — account:` or a traceback.

- If **Python prints nothing** (even `print("hello")`):

  - Confirm you are calling the interpreter you think you are:

    ```bash
    type python3
    python3 -V
    /opt/stock_ai/.venv/bin/python -V
    ```

  - Force unbuffered output:

    ```bash
    python3 -u -c "print('hello', flush=True)"
    ```

  - If still silent, write to a file (proves Python ran):

    ```bash
    python3 -c "open('/tmp/py_ok.txt','w').write('ok\n')" && cat /tmp/py_ok.txt
    ```

### Notes
- `stock-ai-compute.service` keeps refreshing `out/predictions.json` + `out/trade_plan.csv`
- `stock-ai-trade.timer` runs the executor once per weekday; it will **skip** if cash is insufficient or positions/orders already exist.
- The trade unit currently runs **paper trading** (`--paper`) and is configured to deploy **$1000/day split across 10 buys**. When ready for live, remove `--paper` in `stock-ai-trade.service`.

