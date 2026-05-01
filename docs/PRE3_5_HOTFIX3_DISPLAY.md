# N.O.R.M. beta2-pre3.5 hotfix3 — display config + diagnostics

This hotfix makes the optional Pygame screen renderer more configurable and easier to debug.

## New config keys

`config/face.yaml` now includes display/session/SDL options under `screen:`:

- `driver` / `video_driver`: `auto`, `x11`, `wayland`, `kmsdrm`, `fbcon`, `dummy`
- `auto_driver_candidates`: ordered fallback list
- `display`: X11 display, often `:0`
- `wayland_display`: Wayland socket, often `wayland-1`
- `xdg_runtime_dir`: usually `/run/user/1000` for the `jim` user
- `framebuffer`: usually `/dev/fb0`
- `preflight_enabled`, `require_display`, `force_without_display`

## Useful commands

```bash
./scripts/run_screen.sh
./scripts/run_screen.sh --screen-driver kmsdrm
./scripts/run_screen.sh --screen-driver fbcon
./scripts/run_screen.sh --screen-driver x11 --screen-display :0
./scripts/run_screen.sh --screen-windowed --screen-size 800x480
./scripts/screen_diagnostics.sh
./scripts/screen_diagnostics.sh --try-drivers
```

## Web endpoints

- `/face`
- `/api/core/face/status`
- `/api/core/face/screen/diagnostics`
