# N.O.R.M. beta2-pre3.5

Neural Overseer for Routine Management — modular beta2 skeleton with plugin containment, web cockpit, swappable face packs, and an optional Pygame screen face renderer.

## Current milestone

`beta2-pre3.5` adds the first real screen-face graft:

- core `FaceService`
- swappable face packs
- SVG web previews
- `/face` web controls
- optional Pygame fullscreen/windowed screen renderer
- screen renderer follows active pack/state
- screen failures are contained and do not kill the runtime

## Install/update

```bash
cd ~/norm
./scripts/install_deps.sh
source .venv/bin/activate
```

## Smoke test core

```bash
./scripts/run_once.sh
```

## Run web UI

```bash
./scripts/run_web.sh
```

Open:

```text
http://<pi-ip>:8090
```

## Optional screen renderer

Install Pygame into the venv:

```bash
./scripts/install_screen_deps.sh
```

Run web UI + screen face:

```bash
./scripts/run_screen.sh
```

Run screen face without web UI:

```bash
./scripts/run_screen_only.sh
```

Useful URLs:

```text
/face
/api/core/face/status
/api/core/face/preview.svg?pack=norm_default&state=annoyed
/api/core/face/preview.svg?pack=norm_crt&state=speaking
/api/core/face/preview.svg?pack=norm_void&state=error
```

## Notes

The old alpha touch config UI is intentionally not restored in this step. Pre3.5 only brings back the face display layer. Touch/screen config controls should become a dedicated `screenui` service later so the face renderer stays simple and stable.
