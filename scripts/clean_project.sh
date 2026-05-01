#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
find . -type d -name '__pycache__' -prune -exec rm -rf {} +
find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find data/logs -type f -name '*.log' -delete 2>/dev/null || true
printf 'Cleaned beta2-pre3 project.\n'
