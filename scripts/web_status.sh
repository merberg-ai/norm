#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/norm_env.sh"
URL="$(norm_web_wait_url_from_config)"
norm_log "Checking $URL"
"$NORM_PYTHON" - "$URL" <<'PY'
import json, sys, urllib.request
url = sys.argv[1]
with urllib.request.urlopen(url, timeout=5) as r:
    print(json.dumps(json.load(r), indent=2, sort_keys=True))
PY
