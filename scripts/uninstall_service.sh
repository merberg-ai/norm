#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="norm-face.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"

echo "[N.O.R.M.] Stopping and disabling ${SERVICE_NAME}..."
sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true

if [ -f "$SERVICE_PATH" ]; then
  sudo rm -f "$SERVICE_PATH"
fi

sudo systemctl daemon-reload

echo "[N.O.R.M.] Service removed."
