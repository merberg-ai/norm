#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/norm_env.sh"
norm_require_screen_deps
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-dummy}"
export SDL_RENDER_DRIVER="${SDL_RENDER_DRIVER:-software}"
exec "$NORM_PYTHON" app.py --screen "$@"
