#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/norm_env.sh"
norm_require_web_deps
exec "$NORM_PYTHON" app.py --host 0.0.0.0 --port 8090 "$@"
