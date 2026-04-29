#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate
export SDL_AUDIODRIVER=dummy
export SDL_VIDEODRIVER=${SDL_VIDEODRIVER:-kmsdrm}
export SDL_RENDER_DRIVER=${SDL_RENDER_DRIVER:-software}
python app.py --config configs/norm-pi5-alpha.json
