# N.O.R.M. beta2-pre3.5 — Screen Face Renderer

Pre3.5 grafts a real optional Pygame screen renderer onto the beta2 FaceService.

## What this adds

- Optional fullscreen/windowed Pygame face display.
- Screen renderer follows the active face pack and face state.
- Web `/face` preview and state buttons still work.
- Screen failures are contained and do not kill core/web/plugin services.
- `./scripts/run_screen.sh` starts the screen renderer for a single run.
- `./scripts/run_screen_only.sh` starts only the face/core/plugin runtime without web UI.
- `./scripts/install_screen_deps.sh` installs optional `pygame` into the venv.

## Install optional screen dependency

```bash
cd ~/norm
./scripts/install_screen_deps.sh
```

## Run with web UI + screen face

```bash
cd ~/norm
source .venv/bin/activate
./scripts/run_screen.sh
```

## Run screen face only

```bash
cd ~/norm
source .venv/bin/activate
./scripts/run_screen_only.sh
```

## Permanently enable the screen renderer

Edit `config/face.yaml`:

```yaml
screen_enabled: true
screen:
  enabled: true
```

## Safety behavior

The screen renderer checks for a display before starting. By default it requires one of:

- `DISPLAY`
- `WAYLAND_DISPLAY`
- `/dev/fb0`
- `/dev/dri/card0`
- `/dev/dri/renderD128`

If none are found, N.O.R.M. logs `face.screen.skipped` and continues running.

For unusual display setups, you can override this in `config/face.yaml`:

```yaml
screen:
  require_display: false
```

Or force it all the way through:

```yaml
screen:
  force_without_display: true
```

Use the force option only when debugging SDL weirdness. The goblin tax may apply.

## Keyboard controls while the screen face is focused

- `q` or `ESC`: stop the screen renderer window
- `b`: blink
- `SPACE`: cycle test states

The old touch config UI is not restored yet. That belongs in a later screen UI service pass.
