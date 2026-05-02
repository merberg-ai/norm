#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/norm_env.sh"

PORT="$(norm_config_value webui.port 8090)"
URL="http://127.0.0.1:${PORT}/api/core/audio/status"

norm_log "Fetching audio status from $URL"
"$NORM_PYTHON" - "$URL" <<'PY'
import json
import sys
import urllib.request
url = sys.argv[1]
with urllib.request.urlopen(url, timeout=5) as response:
    print(json.dumps(json.load(response), indent=2, sort_keys=True))
PY
