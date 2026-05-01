#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

export SDL_AUDIODRIVER=${SDL_AUDIODRIVER:-dummy}
export SDL_VIDEODRIVER=${SDL_VIDEODRIVER:-kmsdrm}
export SDL_RENDER_DRIVER=${SDL_RENDER_DRIVER:-software}

WEB_LOG="data/logs/norm-web-process.log"
mkdir -p data/logs

echo "[N.O.R.M.] Starting web cockpit in background..."
python3 app.py "$@" >"$WEB_LOG" 2>&1 &
WEB_PID=$!

echo "[N.O.R.M.] Web PID: $WEB_PID"
echo "[N.O.R.M.] Web log: $WEB_LOG"
echo "[N.O.R.M.] Starting direct screen face in foreground..."

cleanup() {
  echo "[N.O.R.M.] Stopping web cockpit PID $WEB_PID..."
  kill "$WEB_PID" >/dev/null 2>&1 || true
  wait "$WEB_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

sleep 1
python3 app.py --screen-direct
