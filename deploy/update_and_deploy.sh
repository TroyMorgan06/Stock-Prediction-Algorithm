#!/usr/bin/env bash
# One-command hybrid deploy + smoke check for the Linux box.
#
# Usage (from /opt/stock_ai or any clone):
#   bash deploy/update_and_deploy.sh
#   bash deploy/update_and_deploy.sh --live-run     # also force a paper trade now
#   bash deploy/update_and_deploy.sh --skip-pull    # use local tree only
#   bash deploy/update_and_deploy.sh --skip-compute # skip compute_worker --once
#
# Expects: repo at REPO_ROOT (default /opt/stock_ai), venv at .venv,
#          Alpaca env at /etc/stock-ai/stock-ai.env

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/opt/stock_ai}"
ENV_FILE="${ENV_FILE:-/etc/stock-ai/stock-ai.env}"
DO_PULL=1
DO_COMPUTE=1
DO_LIVE=0

for arg in "$@"; do
  case "$arg" in
    --skip-pull) DO_PULL=0 ;;
    --skip-compute) DO_COMPUTE=0 ;;
    --live-run) DO_LIVE=1 ;;
    -h|--help)
      sed -n '1,20p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown flag: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

die() { echo "ERROR: $*" >&2; exit 1; }

echo "=== stock_ai update_and_deploy ==="
echo "REPO_ROOT=$REPO_ROOT"

cd "$REPO_ROOT" || die "cannot cd to $REPO_ROOT"

if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
  die "missing $REPO_ROOT/.venv/bin/python — create venv and pip install -r requirements.txt first"
fi

if [[ "$DO_PULL" -eq 1 ]]; then
  echo "--- git pull ---"
  git pull --ff-only
else
  echo "--- skip git pull ---"
fi

echo "--- pip install ---"
# shellcheck disable=SC1091
source "$REPO_ROOT/.venv/bin/activate"
pip install -q -r requirements.txt

echo "--- install systemd units ---"
sudo cp "$REPO_ROOT"/deploy/systemd/stock-ai-*.service /etc/systemd/system/
sudo cp "$REPO_ROOT"/deploy/systemd/stock-ai-*.timer /etc/systemd/system/ 2>/dev/null || true
sudo systemctl daemon-reload

echo "--- timezone America/New_York ---"
sudo timedatectl set-timezone America/New_York || true
timedatectl | head -n 5 || true

echo "--- restart compute + enable trade timer ---"
sudo systemctl restart stock-ai-compute.service
sudo systemctl enable --now stock-ai-trade.timer
systemctl is-active stock-ai-compute.service || true
systemctl list-timers stock-ai-trade.timer --no-pager || true

if [[ ! -f "$ENV_FILE" ]]; then
  die "missing $ENV_FILE — run: sudo $REPO_ROOT/.venv/bin/python $REPO_ROOT/deploy/setup_alpaca_env.py"
fi

echo "--- verify Alpaca paper account ---"
sudo bash -c "set -a && source '$ENV_FILE' && set +a && '$REPO_ROOT/.venv/bin/python' '$REPO_ROOT/deploy/verify_alpaca.py'"

if [[ "$DO_COMPUTE" -eq 1 ]]; then
  echo "--- compute_worker --once (may take a few minutes) ---"
  "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/compute_worker.py" --once
  echo "--- trade_plan head ---"
  head -20 "$REPO_ROOT/out/trade_plan.csv" 2>/dev/null || echo "(no trade_plan.csv yet)"
else
  echo "--- skip compute_worker ---"
fi

echo "--- hybrid morning dry-run ---"
sudo bash -c "set -a && source '$ENV_FILE' && set +a && \
  '$REPO_ROOT/.venv/bin/python' '$REPO_ROOT/hybrid_morning.py' --paper \
  --daily-budget 2000 --max-buys 12 --take-profit 0.015 --stop-loss 0.015 --dry-run"

echo "--- approved_basket head ---"
head -30 "$REPO_ROOT/out/approved_basket.csv" 2>/dev/null || echo "(no approved_basket.csv)"

if [[ "$DO_LIVE" -eq 1 ]]; then
  echo "--- LIVE paper run (systemctl start stock-ai-trade.service) ---"
  sudo systemctl start stock-ai-trade.service
  sudo journalctl -u stock-ai-trade.service -n 80 --no-pager
else
  echo "--- dry-run only (pass --live-run to force a paper trade now) ---"
fi

echo "=== done ==="
echo "Timer: Mon-Fri 09:35 America/New_York → hybrid_morning.py"
echo "Docs: deploy/PAPER_RESET_CHECKLIST.md  deploy/CURSOR_SSH.md"
