#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/norm_env.sh
source "$SCRIPT_DIR/norm_env.sh"

norm_require_web_deps
WEB_PORT="$(norm_config_value webui.port 8090)"
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
norm_log "Starting web cockpit only. Physical screen face is not launched by this script."
norm_log "Open: http://<pi-ip>:${WEB_PORT}/"
exec "$NORM_PYTHON" app.py "$@"
