# N.O.R.M. beta2-pre4.6 Script Cleanup / Web Launch Fix

This patch keeps the current sane pre4.5 face/display code and fixes the run/install script layer.

## Why

The project could display the face because the screen path only needed the system Pygame setup, but the Web UI could fail when scripts were run from a shell where `.venv` was not active. The old scripts called `python3` directly, so FastAPI/Uvicorn installed inside `.venv` were easy to miss.

## Changes

- Added `scripts/norm_env.sh` shared runtime helper.
- All run scripts now prefer `.venv/bin/python` automatically.
- `run_web.sh` checks for FastAPI/Uvicorn before starting.
- `run_full.sh` starts web in the background, waits for `/api/core/health`, then starts the direct KMS face.
- `run_full.sh` shows the web log tail if the web cockpit fails to become reachable.
- Added `scripts/web_status.sh`.
- Added `scripts/fix_permissions.sh`.
- `install_deps.sh` enables system site packages and fixes script permissions.
- Updated stale version/codename labels to `beta2-pre4.6-scripts`.

## Recommended commands

```bash
cd ~/norm
./scripts/fix_permissions.sh
./scripts/install_deps.sh
./scripts/repair_pygame_display.sh
./scripts/run_once.sh
./scripts/run_web.sh
```

For web + screen together:

```bash
./scripts/run_full.sh
```
