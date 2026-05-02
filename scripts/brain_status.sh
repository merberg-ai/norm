#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/norm_env.sh"
PORT="$(norm_config_value webui.port 8090)"
"$NORM_PYTHON" - "http://127.0.0.1:${PORT}/api/core/brain/status" <<'PY'
import json, sys, urllib.request
url = sys.argv[1]
with urllib.request.urlopen(url, timeout=6) as r:
    print(json.dumps(json.loads(r.read().decode()), indent=2))
PY
