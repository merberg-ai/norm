#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="norm-face.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
RUN_USER="${NORM_SERVICE_USER:-${USER}}"
RUN_GROUP="$(id -gn "$RUN_USER")"
PYTHON_BIN="${APP_DIR}/.venv/bin/python"
CONFIG_PATH="${APP_DIR}/configs/norm-alpha.json"
TOUCH_DEVICE="${NORM_TOUCH_DEVICE:-/dev/input/event0}"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "[N.O.R.M.] Missing virtualenv Python: $PYTHON_BIN"
  echo "Run ./scripts/install_deps.sh first."
  exit 1
fi

if [ ! -f "$CONFIG_PATH" ]; then
  echo "[N.O.R.M.] Missing config: $CONFIG_PATH"
  exit 1
fi

echo "[N.O.R.M.] Installing service for user: $RUN_USER"
echo "[N.O.R.M.] App directory: $APP_DIR"

# Add the service user to hardware-related groups when those groups exist.
# Some images do not have every group, so this is intentionally tolerant.
for group in input video render audio; do
  if getent group "$group" >/dev/null 2>&1; then
    sudo usermod -aG "$group" "$RUN_USER" || true
  fi
done

TMP_SERVICE="$(mktemp)"
cat > "$TMP_SERVICE" <<SERVICE
[Unit]
Description=N.O.R.M. Face Core
Wants=network-online.target
After=network-online.target sound.target local-fs.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=SDL_VIDEODRIVER=kmsdrm
Environment=SDL_RENDER_DRIVER=software
Environment=SDL_AUDIODRIVER=dummy
Environment=NORM_TOUCH_DEVICE=${TOUCH_DEVICE}
ExecStart=${PYTHON_BIN} ${APP_DIR}/app.py --config ${CONFIG_PATH}
Restart=on-failure
RestartSec=3
KillSignal=SIGTERM
TimeoutStopSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

sudo install -m 0644 "$TMP_SERVICE" "$SERVICE_PATH"
rm -f "$TMP_SERVICE"

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

echo
echo "[N.O.R.M.] Service installed and enabled."
echo
echo "Start now:"
echo "  sudo systemctl start $SERVICE_NAME"
echo
echo "Check status:"
echo "  ./scripts/service_status.sh"
echo
echo "Follow logs:"
echo "  ./scripts/service_logs.sh"
echo
echo "If this user was just added to input/video/render/audio groups, reboot once:"
echo "  sudo reboot"
