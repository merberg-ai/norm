#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/norm_env.sh"

norm_log "Installing audio/TTS system packages..."
sudo apt update
sudo apt install -y \
  alsa-utils \
  espeak-ng \
  curl \
  ca-certificates

norm_log "Installing Piper TTS into the project venv..."
if "$NORM_PYTHON" -m pip install --upgrade piper-tts; then
  norm_log "piper-tts installed/updated in .venv."
else
  norm_log "WARNING: piper-tts install failed. N.O.R.M. will fall back to eSpeak."
fi

if [ -x "$NORM_ROOT/.venv/bin/piper" ]; then
  norm_log "Checking .venv/bin/piper..."
  if "$NORM_ROOT/.venv/bin/piper" --help >/tmp/norm-piper-help.txt 2>&1; then
    if grep -q -- '--model' /tmp/norm-piper-help.txt && grep -q -- '--output_file' /tmp/norm-piper-help.txt; then
      norm_log "Piper TTS executable OK: $NORM_ROOT/.venv/bin/piper"
    else
      norm_log "WARNING: .venv/bin/piper exists but did not look like Piper TTS."
    fi
  else
    norm_log "WARNING: .venv/bin/piper exists but --help failed. See /tmp/norm-piper-help.txt"
  fi
else
  norm_log "WARNING: .venv/bin/piper not found yet. eSpeak fallback will still work."
fi

if command -v piper >/dev/null 2>&1 && [ "$(command -v piper)" != "$NORM_ROOT/.venv/bin/piper" ]; then
  norm_log "NOTE: system PATH also has: $(command -v piper)"
  norm_log "N.O.R.M. ignores that by default and uses .venv/bin/piper."
fi

chmod +x scripts/*.sh
norm_log "Audio dependencies checked. Open /audio in the Web UI."
