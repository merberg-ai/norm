#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -d .venv ]; then
  source .venv/bin/activate
fi

export NORM_TOUCH_DEVICE="${NORM_TOUCH_DEVICE:-/dev/input/event0}"
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-kmsdrm}"
export SDL_RENDER_DRIVER="${SDL_RENDER_DRIVER:-software}"
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-dummy}"
export PYTHONUNBUFFERED=1

# Pi 5 is the default alpha target.
exec python app.py --config configs/norm-alpha.json
