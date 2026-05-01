#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export SDL_AUDIODRIVER=${SDL_AUDIODRIVER:-dummy}
export SDL_VIDEODRIVER=${SDL_VIDEODRIVER:-kmsdrm}
export SDL_RENDER_DRIVER=${SDL_RENDER_DRIVER:-software}
python3 app.py --screen-direct "$@"
