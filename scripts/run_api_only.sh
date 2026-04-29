#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -d .venv ]; then source .venv/bin/activate; fi
exec python app.py --config configs/norm-alpha.json --no-display --no-touch
