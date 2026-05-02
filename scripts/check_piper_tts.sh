#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/norm_env.sh"

PIPER="$NORM_ROOT/.venv/bin/piper"
echo "NORM_ROOT: $NORM_ROOT"
echo "NORM_PYTHON: $NORM_PYTHON"
echo "Expected Piper TTS: $PIPER"
if [ ! -x "$PIPER" ]; then
  echo "MISSING: $PIPER"
  echo "Run: ./scripts/install_audio_deps.sh"
  exit 1
fi
"$PIPER" --help | head -80
if "$PIPER" --help 2>&1 | grep -q -- '--model' && "$PIPER" --help 2>&1 | grep -q -- '--output_file'; then
  echo "OK: .venv/bin/piper looks like Piper TTS."
else
  echo "BAD: .venv/bin/piper did not look like Piper TTS."
  exit 1
fi
