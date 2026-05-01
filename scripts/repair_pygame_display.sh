#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[N.O.R.M.] Repairing Pygame display backend for Raspberry Pi Lite/headless rendering..."
echo "[N.O.R.M.] The old working alpha used apt's python3-pygame + a venv with --system-site-packages."
echo "[N.O.R.M.] This script restores that setup and removes the pip pygame wheel if present."

if ! command -v sudo >/dev/null 2>&1; then
  echo "ERROR: sudo is required to install Raspberry Pi OS packages." >&2
  exit 1
fi

echo "[N.O.R.M.] Installing system SDL/Pygame packages..."
sudo apt update
sudo apt install -y \
  python3-pygame \
  python3-numpy \
  libsdl2-2.0-0 \
  libsdl2-ttf-2.0-0 \
  libsdl2-image-2.0-0 \
  libsdl2-mixer-2.0-0

if [ ! -d .venv ]; then
  echo "[N.O.R.M.] Creating .venv with system site packages enabled..."
  python3 -m venv --system-site-packages .venv
fi

if [ ! -f .venv/pyvenv.cfg ]; then
  echo "ERROR: .venv/pyvenv.cfg not found. Is .venv a valid Python virtual environment?" >&2
  exit 1
fi

echo "[N.O.R.M.] Enabling system site packages inside .venv..."
if grep -q '^include-system-site-packages' .venv/pyvenv.cfg; then
  sed -i 's/^include-system-site-packages *= *.*/include-system-site-packages = true/' .venv/pyvenv.cfg
else
  printf '\ninclude-system-site-packages = true\n' >> .venv/pyvenv.cfg
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[N.O.R.M.] Removing pip-installed pygame wheel from the venv, if present..."
python -m pip uninstall -y pygame >/dev/null 2>&1 || true

echo "[N.O.R.M.] Python/Pygame import check:"
python - <<'PY'
import os
import sys
try:
    import pygame
except Exception as exc:
    print(f"ERROR: pygame import failed: {exc}")
    raise SystemExit(1)
print(f"python: {sys.executable}")
print(f"pygame: {pygame.version.ver}")
print(f"pygame file: {getattr(pygame, '__file__', 'unknown')}")
print(f"SDL_VIDEODRIVER currently: {os.environ.get('SDL_VIDEODRIVER', '')}")
PY

cat <<'MSG'

[N.O.R.M.] Repair complete.

Now try:
  ./scripts/check_pygame_backend.sh
  ./scripts/run_screen.sh

If this is the first time adding/changing hardware groups or system packages, rebooting once is still a good idea:
  sudo reboot
MSG
