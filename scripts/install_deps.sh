#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
printf '\nDone. Start with:\n  source .venv/bin/activate\n  ./scripts/run_once.sh\n'
