#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  echo "No .venv found. Run ./scripts/install_deps.sh or ./scripts/repair_pygame_display.sh first." >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

export SDL_AUDIODRIVER=${SDL_AUDIODRIVER:-dummy}
export SDL_RENDER_DRIVER=${SDL_RENDER_DRIVER:-software}

cat <<'MSG'
[N.O.R.M.] Checking Pygame/SDL display backends.
This checks whether SDL can initialize the named driver from this shell.
MSG

python - <<'PY'
import os
import sys
print(f"python: {sys.executable}")
try:
    import pygame
except Exception as exc:
    print(f"pygame import failed: {exc}")
    raise SystemExit(1)
print(f"pygame: {pygame.version.ver}")
print(f"pygame file: {getattr(pygame, '__file__', 'unknown')}")
PY

for driver in kmsdrm fbcon dummy; do
  echo
  echo "--- SDL_VIDEODRIVER=$driver ---"
  SDL_VIDEODRIVER="$driver" python - <<'PY'
try:
    import pygame
    pygame.display.quit()
    pygame.display.init()
    print("display init: OK")
    print("chosen driver:", pygame.display.get_driver())
    pygame.display.quit()
except Exception as exc:
    print("display init: FAILED")
    print("error:", exc)
PY
done

cat <<'MSG'

If kmsdrm says OK, ./scripts/run_screen.sh should be able to render.
If kmsdrm still says "not available", the venv is still importing the pip wheel or SDL was built without kmsdrm support.
MSG
