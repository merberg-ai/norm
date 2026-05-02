#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/norm_env.sh"
find . -type d -name '__pycache__' -prune -exec rm -rf {} +
find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find data/logs -type f -name '*.log' -delete 2>/dev/null || true
find data/logs -type f -name 'norm-web-process.log' -delete 2>/dev/null || true
printf '[N.O.R.M.] Cleaned beta2 project cache/log clutter.\n'
