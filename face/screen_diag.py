from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def gather_basic() -> dict[str, object]:
    uid = os.getuid()
    return {
        "user": {
            "uid": uid,
            "gid": os.getgid(),
            "groups": os.getgroups(),
            "home": str(Path.home()),
        },
        "env": {
            key: os.environ.get(key, "")
            for key in [
                "DISPLAY",
                "WAYLAND_DISPLAY",
                "XDG_RUNTIME_DIR",
                "XAUTHORITY",
                "SDL_VIDEODRIVER",
                "SDL_FBDEV",
                "PYGAME_DISPLAY",
                "SSH_TTY",
                "SSH_CONNECTION",
            ]
        },
        "devices": {
            "fb": sorted(glob.glob("/dev/fb*")),
            "dri": sorted(glob.glob("/dev/dri/*")),
            "input": sorted(glob.glob("/dev/input/event*"))[:20],
            "x11_sockets": sorted(glob.glob("/tmp/.X11-unix/X*")),
            "wayland_sockets": sorted(glob.glob(f"/run/user/{uid}/wayland-*")),
        },
        "paths": {
            "home_xauthority_exists": Path.home().joinpath(".Xauthority").exists(),
            "run_user_exists": Path(f"/run/user/{uid}").exists(),
        },
        "system": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
        },
    }


def try_driver(driver: str, width: int, height: int) -> dict[str, object]:
    code = f'''
import json, os, sys
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
if {driver!r} not in ("auto", "default", "none", ""):
    os.environ["SDL_VIDEODRIVER"] = {driver!r}
else:
    os.environ.pop("SDL_VIDEODRIVER", None)
try:
    import pygame
    pygame.display.init()
    screen = pygame.display.set_mode(({width}, {height}))
    payload = {{
        "ok": True,
        "driver_requested": {driver!r},
        "driver_chosen": pygame.display.get_driver(),
        "num_displays": pygame.display.get_num_displays(),
        "surface_size": screen.get_size(),
    }}
    print(json.dumps(payload))
    pygame.display.quit()
except Exception as exc:
    print(json.dumps({{"ok": False, "driver_requested": {driver!r}, "error": str(exc)}}))
    sys.exit(1)
'''
    try:
        proc = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True, timeout=8)
    except subprocess.TimeoutExpired:
        return {"ok": False, "driver_requested": driver, "error": "timeout"}
    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
    except Exception:
        payload = {"raw_stdout": proc.stdout.strip()}
    payload.update({"returncode": proc.returncode, "stderr": proc.stderr.strip()})
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="N.O.R.M. screen/display diagnostics")
    parser.add_argument("--try-drivers", action="store_true", help="Attempt to open a tiny Pygame window/screen with common SDL drivers")
    parser.add_argument("--drivers", default="auto,x11,wayland,kmsdrm,fbcon,dummy", help="Comma-separated drivers to try")
    parser.add_argument("--size", default="320x240", help="Test surface size, e.g. 320x240")
    args = parser.parse_args()

    payload = gather_basic()
    if args.try_drivers:
        width, height = 320, 240
        try:
            raw_w, raw_h = args.size.lower().split("x", 1)
            width, height = int(raw_w), int(raw_h)
        except Exception:
            pass
        payload["pygame_driver_attempts"] = [
            try_driver(driver.strip(), width, height)
            for driver in args.drivers.split(",")
            if driver.strip()
        ]

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
