#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Web cockpit only. On headless Pi Lite/KMS installs, the physical face screen
# runs through ./scripts/run_screen.sh or ./scripts/run_full.sh.
python3 app.py "$@"
