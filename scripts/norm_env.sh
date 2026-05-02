#!/usr/bin/env bash
# Common runtime helpers for N.O.R.M. beta2 scripts.
# Source this file from scripts/*.sh instead of assuming the caller activated .venv.

set -euo pipefail

NORM_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export NORM_ROOT="${NORM_ROOT:-$(cd "$NORM_SCRIPT_DIR/.." && pwd)}"
cd "$NORM_ROOT"

if [ -x "$NORM_ROOT/.venv/bin/python" ]; then
  export NORM_PYTHON="${NORM_PYTHON:-$NORM_ROOT/.venv/bin/python}"
  # Put venv console scripts first so "piper" resolves to Piper TTS from the venv,
  # not an unrelated system package at /usr/bin/piper. Yes, that happened.
  export PATH="$NORM_ROOT/.venv/bin:$PATH"
else
  export NORM_PYTHON="${NORM_PYTHON:-python3}"
fi

norm_log() {
  printf '[N.O.R.M.] %s\n' "$*"
}

norm_python_info() {
  norm_log "Root: $NORM_ROOT"
  norm_log "Python: $NORM_PYTHON"
  "$NORM_PYTHON" - <<'PY'
import sys
print(f"[N.O.R.M.] Python version: {sys.version.split()[0]}")
PY
}

norm_require_modules() {
  "$NORM_PYTHON" - "$@" <<'PY'
import importlib.util
import sys
missing = [name for name in sys.argv[1:] if importlib.util.find_spec(name) is None]
if missing:
    print("[N.O.R.M.] Missing Python module(s): " + ", ".join(missing), file=sys.stderr)
    print("[N.O.R.M.] Run: ./scripts/install_deps.sh", file=sys.stderr)
    raise SystemExit(1)
PY
}

norm_require_web_deps() {
  norm_require_modules fastapi uvicorn
}

norm_require_screen_deps() {
  norm_require_modules pygame
}

norm_config_value() {
  local dotted_key="$1"
  local default_value="${2:-}"
  "$NORM_PYTHON" - "$dotted_key" "$default_value" <<'PY'
from pathlib import Path
import sys
try:
    from core import yaml_compat as yaml
except Exception:
    import yaml  # type: ignore
key = sys.argv[1]
default = sys.argv[2]
try:
    data = yaml.safe_load(Path('config/norm.yaml').read_text()) or {}
except Exception:
    print(default)
    raise SystemExit(0)
cur = data
for part in key.split('.'):
    if not isinstance(cur, dict) or part not in cur:
        print(default)
        raise SystemExit(0)
    cur = cur[part]
print(cur)
PY
}

norm_wait_url() {
  local url="$1"
  local timeout="${2:-20}"
  "$NORM_PYTHON" - "$url" "$timeout" <<'PY'
import sys, time, urllib.request, urllib.error
url = sys.argv[1]
timeout = float(sys.argv[2])
deadline = time.time() + timeout
last = None
while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as r:
            if 200 <= r.status < 500:
                print(f"[N.O.R.M.] Web responded: {url} ({r.status})")
                raise SystemExit(0)
    except Exception as exc:
        last = exc
    time.sleep(0.5)
print(f"[N.O.R.M.] Timed out waiting for {url}. Last error: {last}", file=sys.stderr)
raise SystemExit(1)
PY
}

norm_web_wait_url_from_config() {
  local port
  port="$(norm_config_value webui.port 8090)"
  printf 'http://127.0.0.1:%s/api/core/health\n' "$port"
}
