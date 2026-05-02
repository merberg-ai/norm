#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/norm_env.sh"

norm_require_web_deps
norm_require_screen_deps

WEB_PORT="$(norm_config_value webui.port 8090)"
# Respect common CLI port overrides passed to run_full.sh.
prev=""
for arg in "$@"; do
  if [ "$prev" = "--port" ]; then
    WEB_PORT="$arg"
  fi
  case "$arg" in
    --port=*) WEB_PORT="${arg#--port=}" ;;
  esac
  prev="$arg"
done

mkdir -p data/logs
WEB_LOG="data/logs/norm-web-process.log"
WEB_WAIT_URL="http://127.0.0.1:${WEB_PORT}/api/core/health"

norm_log "Starting web cockpit in background..."
norm_log "Web log: $WEB_LOG"
(
  unset SDL_VIDEODRIVER SDL_RENDER_DRIVER SDL_FBDEV PYGAME_DISPLAY
  exec "$NORM_PYTHON" app.py "$@"
) >"$WEB_LOG" 2>&1 &
WEB_PID=$!

cleanup() {
  norm_log "Stopping web cockpit PID $WEB_PID..."
  kill "$WEB_PID" >/dev/null 2>&1 || true
  wait "$WEB_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

if ! norm_wait_url "$WEB_WAIT_URL" 25; then
  norm_log "Web cockpit did not become reachable. Last 80 lines of $WEB_LOG:"
  tail -80 "$WEB_LOG" || true
  exit 1
fi

norm_log "Web cockpit is reachable. Open: http://<pi-ip>:${WEB_PORT}/"
norm_log "Starting direct screen face in foreground..."
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-dummy}"
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-kmsdrm}"
export SDL_RENDER_DRIVER="${SDL_RENDER_DRIVER:-software}"
"$NORM_PYTHON" app.py --screen-direct
