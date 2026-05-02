#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[N.O.R.M.] Installing beta2 base system packages..."
sudo apt update
sudo apt install -y \
  python3-venv \
  python3-pip \
  python3-pygame \
  python3-numpy \
  curl \
  git

if [ ! -d .venv ]; then
  echo "[N.O.R.M.] Creating .venv with system site packages enabled..."
  python3 -m venv --system-site-packages .venv
else
  echo "[N.O.R.M.] Existing .venv found; enabling system site packages..."
  if grep -q '^include-system-site-packages' .venv/pyvenv.cfg; then
    sed -i 's/^include-system-site-packages *= *.*/include-system-site-packages = true/' .venv/pyvenv.cfg
  else
    printf '\ninclude-system-site-packages = true\n' >> .venv/pyvenv.cfg
  fi
fi

".venv/bin/python" -m pip install --upgrade pip setuptools wheel
".venv/bin/python" -m pip install -r requirements.txt

# Keep script permissions sane after ZIP uploads/overlays.
chmod +x scripts/*.sh

printf '\n[N.O.R.M.] Dependencies installed. Try:\n  ./scripts/run_once.sh\n  ./scripts/run_web.sh\n\nFor audio/TTS extras:
  ./scripts/install_audio_deps.sh

For web + physical screen together:\n  ./scripts/repair_pygame_display.sh\n  ./scripts/run_full.sh\n\n'
