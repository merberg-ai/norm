# N.O.R.M. beta2-pre2 migration notes

pre2 is still a foundation package. It is safe to run in `~/norm` if that is now your beta2 working directory.

## From pre1 to pre2

Overlay the files into your beta2 folder:

```bash
cd ~/norm
unzip -o /path/to/norm-beta2-pre2-overlay.zip
./scripts/install_deps.sh
source .venv/bin/activate
./scripts/run_once.sh
./scripts/run_once_web.sh
./scripts/run_web.sh
```

## What changed

- Added `webui/service.py`
- Added `webui/static/norm.css`
- Added web config in `config/norm.yaml`
- Added `services.webui.enabled`
- AppContext now starts PluginManager first, then WebUI
- hello_norm now exposes `/hello`
- requirements now include FastAPI/Uvicorn

## Notes

`run_once.sh` intentionally uses `--no-web` so a basic smoke test does not need to bind a port.

`run_once_web.sh` tests that the web dependencies and route mounting are working.

`run_web.sh` runs the actual cockpit until Ctrl+C.
