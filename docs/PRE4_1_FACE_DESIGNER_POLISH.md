# N.O.R.M. beta2-pre4.1

This overlay clarifies the runtime modes and polishes the Face Designer layout.

## Runtime modes

- `./scripts/run_web.sh` starts the web cockpit only.
- `./scripts/run_screen.sh` starts the direct Pi/KMS display face only.
- `./scripts/run_full.sh` starts the web cockpit in the background and the direct screen face in the foreground.

On Raspberry Pi Lite/headless installs, the fullscreen display uses SDL/KMS and is happiest when Pygame owns the foreground/main process. Running web and screen as two processes is the safer path.

## Face runtime bridge

Web and screen processes now share face state through:

```text
data/runtime/face_state.json
```

The web process writes active pack/state changes. The screen process polls this file and updates the physical face without needing X11/Wayland or a shared event loop.

## Face Designer polish

- Better two-column desktop layout
- Better one-column mobile layout
- Cards align more predictably
- Preview gets its own main panel
- YAML editor fills the available space better
- Status log wraps instead of pushing layout sideways
