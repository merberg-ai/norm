# N.O.R.M. beta2-pre3.5 hotfix5: Raspberry Pi system Pygame repair

The old working N.O.R.M. alpha installed `python3-pygame` through apt and created its virtual environment with `--system-site-packages`.

The beta2 pre3.5 screen dependency script installed `pygame` from pip. On this Raspberry Pi Lite/headless setup, that pip wheel does not expose the SDL `kmsdrm` or `fbcon` video drivers, causing errors like:

```text
kmsdrm not available
fbcon not available
```

This hotfix restores the alpha-style dependency path:

- install Raspberry Pi OS `python3-pygame`
- enable `.venv` system site packages
- uninstall the pip `pygame` wheel from the venv
- add `check_pygame_backend.sh`

Run:

```bash
cd ~/norm
./scripts/repair_pygame_display.sh
./scripts/check_pygame_backend.sh
./scripts/run_screen.sh
```

The desired result is that `kmsdrm` initializes successfully.
