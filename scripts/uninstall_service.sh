#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/norm_env.sh"
SERVICE_NAME="${NORM_SERVICE_NAME:-norm-beta2.service}"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"

echo "[N.O.R.M.] Stopping/disabling ${SERVICE_NAME}..."
sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true
if [ -f "$SERVICE_PATH" ]; then
  sudo rm -f "$SERVICE_PATH"
fi
sudo systemctl daemon-reload
echo "[N.O.R.M.] Service removed: ${SERVICE_NAME}"
