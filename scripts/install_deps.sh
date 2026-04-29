#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[N.O.R.M.] Installing system packages..."
sudo apt update
sudo apt install -y \
  python3-venv \
  python3-pip \
  python3-pygame \
  python3-numpy \
  python3-evdev \
  v4l-utils \
  fswebcam \
  ffmpeg \
  alsa-utils \
  espeak-ng \
  curl \
  git

echo "[N.O.R.M.] Ensuring current user can read hardware devices..."
for group in input video render audio; do
  if getent group "$group" >/dev/null 2>&1; then
    sudo usermod -aG "$group" "$USER" || true
  fi
done

echo "[N.O.R.M.] Creating venv..."
python3 -m venv .venv --system-site-packages
source .venv/bin/activate

echo "[N.O.R.M.] Installing lightweight Python web/API dependencies..."
python -m pip install --upgrade pip setuptools wheel
python -m pip install --prefer-binary -r requirements.txt

echo
echo "[N.O.R.M.] Install complete."
echo "If this is the first time adding your user to hardware groups, reboot now:"
echo "  sudo reboot"
