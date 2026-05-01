# N.O.R.M. beta2-pre3.5 hotfix4 — direct Pi Lite screen mode

This hotfix targets headless Raspberry Pi Lite installs with no X11 or Wayland.

The old alpha face renderer worked because Pygame ran on the main thread with:

```bash
SDL_VIDEODRIVER=kmsdrm
SDL_RENDER_DRIVER=software
SDL_AUDIODRIVER=dummy
```

pre3.5 originally ran the screen renderer in a background thread so web/core could
survive display failures. That is safer, but some Pi Lite + SDL/KMSDRM setups do
not actually render visibly from the background thread.

Hotfix4 adds direct mode:

```bash
./scripts/run_screen.sh
```

`run_screen.sh` now uses `python3 app.py --screen-direct`, disables the web UI for
that run, starts core services, then runs the Pygame face renderer on the main
thread.

Use this first on the 5-inch Pi display. Keep `./scripts/run_web.sh` for the web
cockpit.

A threaded mode is still available for experiments:

```bash
./scripts/run_screen_threaded.sh
```
