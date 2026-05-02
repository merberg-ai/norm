#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/norm_env.sh"

SERVICE_NAME="${NORM_SERVICE_NAME:-norm-beta2.service}"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
RUN_USER="${NORM_SERVICE_USER:-${SUDO_USER:-${USER}}}"
RUN_GROUP="$(id -gn "$RUN_USER")"
APP_DIR="$NORM_ROOT"

if [ ! -x "$NORM_PYTHON" ]; then
  echo "[N.O.R.M.] Missing Python runtime: $NORM_PYTHON"
  echo "Run ./scripts/install_deps.sh first."
  exit 1
fi
if [ ! -x "$APP_DIR/scripts/run_full.sh" ]; then
  echo "[N.O.R.M.] Missing executable run_full.sh. Run ./scripts/fix_permissions.sh"
  exit 1
fi

echo "[N.O.R.M.] Installing ${SERVICE_NAME} for user ${RUN_USER}"
echo "[N.O.R.M.] App directory: ${APP_DIR}"

for group in input video render audio; do
  if getent group "$group" >/dev/null 2>&1; then
    sudo usermod -aG "$group" "$RUN_USER" || true
  fi
done

TMP_SERVICE="$(mktemp)"
cat > "$TMP_SERVICE" <<SERVICE
[Unit]
Description=N.O.R.M. beta2 Runtime
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
ExecStart=/bin/bash ${APP_DIR}/scripts/run_full.sh
Restart=on-failure
RestartSec=3
KillSignal=SIGTERM
TimeoutStopSec=8
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

sudo install -m 0644 "$TMP_SERVICE" "$SERVICE_PATH"
rm -f "$TMP_SERVICE"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

echo "[N.O.R.M.] Service installed and enabled: ${SERVICE_NAME}"
echo "Start now: sudo systemctl start ${SERVICE_NAME}"
echo "Status:    ./scripts/service_status.sh"
echo "Logs:      ./scripts/service_logs.sh"
echo "If ${RUN_USER} was just added to hardware groups, reboot once."
