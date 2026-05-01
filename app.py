#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from core.app_context import AppContext
from core.config import ConfigManager
from core.lifecycle import ShutdownSignal
from core.logging import setup_logging
from core.paths import NormPaths


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="N.O.R.M. beta2-pre3.5-hotfix4 modular runtime + optional screen face")
    parser.add_argument("--root", default=".", help="Project root directory. Default: current directory")
    parser.add_argument("--config-dir", default="config", help="Config directory relative to root")
    parser.add_argument("--safe-mode", action="store_true", help="Boot without starting plugins")
    parser.add_argument("--once", action="store_true", help="Start, print health report, then shut down")
    parser.add_argument("--json-health", action="store_true", help="Print health report as JSON")
    parser.add_argument("--no-web", action="store_true", help="Disable the Web UI service for this run")
    parser.add_argument("--host", help="Override web UI host for this run")
    parser.add_argument("--port", type=int, help="Override web UI port for this run")
    parser.add_argument("--screen", action="store_true", help="Start the optional Pygame face screen renderer for this run")
    parser.add_argument("--screen-direct", action="store_true", help="Run the face renderer on the main thread for Pi Lite/kmsdrm/fbcon displays")
    parser.add_argument("--no-screen", action="store_true", help="Disable the optional Pygame face screen renderer for this run")
    parser.add_argument("--screen-driver", help="Override SDL video driver for screen run: auto, x11, wayland, kmsdrm, fbcon, dummy")
    parser.add_argument("--screen-display", help="Override DISPLAY for X11 screen runs, for example :0")
    parser.add_argument("--screen-wayland-display", help="Override WAYLAND_DISPLAY for Wayland screen runs, for example wayland-1")
    parser.add_argument("--screen-windowed", action="store_true", help="Run screen face windowed instead of fullscreen")
    parser.add_argument("--screen-size", help="Override screen size for this run, e.g. 800x480")
    return parser


async def amain() -> int:
    args = build_arg_parser().parse_args()
    root = Path(args.root).resolve()

    paths = NormPaths.from_root(root=root, config_dir=args.config_dir)
    paths.ensure()

    config_manager = ConfigManager(paths.config_dir)
    config = config_manager.load()

    # Runtime CLI overrides. We do not write them back to disk.
    if args.safe_mode:
        config.norm.setdefault("app", {})["safe_mode"] = True
    if args.no_web:
        config.norm.setdefault("services", {}).setdefault("webui", {})["enabled"] = False
        config.norm.setdefault("webui", {})["enabled"] = False
    if args.host:
        config.norm.setdefault("webui", {})["host"] = args.host
    if args.port:
        config.norm.setdefault("webui", {})["port"] = args.port
    if args.screen:
        config.norm.setdefault("services", {}).setdefault("face", {})["enabled"] = True
        config.face["screen_enabled"] = True
        config.face.setdefault("screen", {})["enabled"] = True
    if args.screen_direct:
        # Direct mode runs Pygame on the main thread, matching the old working
        # alpha renderer. Disable the threaded screen auto-start; app.py will
        # launch it explicitly after services are ready.
        config.norm.setdefault("services", {}).setdefault("face", {})["enabled"] = True
        config.norm.setdefault("services", {}).setdefault("webui", {})["enabled"] = False
        config.norm.setdefault("webui", {})["enabled"] = False
        config.face["screen_enabled"] = False
        config.face.setdefault("screen", {})["enabled"] = False
    if args.no_screen:
        config.face["screen_enabled"] = False
        config.face.setdefault("screen", {})["enabled"] = False
    if args.screen_driver:
        config.face.setdefault("screen", {})["video_driver"] = args.screen_driver
    if args.screen_display:
        config.face.setdefault("screen", {})["display"] = args.screen_display
    if args.screen_wayland_display:
        config.face.setdefault("screen", {})["wayland_display"] = args.screen_wayland_display
    if args.screen_windowed:
        config.face.setdefault("screen", {})["fullscreen"] = False
    if args.screen_size:
        try:
            raw_w, raw_h = args.screen_size.lower().replace(",", "x").split("x", 1)
            config.face.setdefault("screen", {})["width"] = int(raw_w)
            config.face.setdefault("screen", {})["height"] = int(raw_h)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"Invalid --screen-size value: {args.screen_size!r}. Use WIDTHxHEIGHT, e.g. 800x480") from exc

    # Re-resolve paths after config load in case the user customized dirs.
    paths = NormPaths.from_root(
        root=root,
        config_dir=args.config_dir,
        data_dir=config.get("paths.data_dir", "data"),
        logs_dir=config.get("paths.logs_dir", "data/logs"),
        plugins_dir=config.get("paths.plugins_dir", "plugins"),
    )
    paths.ensure()

    logger = setup_logging(config.norm, paths.logs_dir)
    logger.info("Starting %s %s", config.get("app.name"), config.get("app.codename"))
    logger.info("Config loaded: config_version=%s", config.norm.get("config_version"))

    context = AppContext.create(root=root, paths=paths, config=config, logger=logger)

    try:
        await context.start()
        report = await context.health_report()

        if config.get("runtime.print_startup_report", True):
            if args.json_health:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print_startup_report(report)

        if args.screen_direct:
            from face.screen import FaceScreenRenderer

            face = context.get_service("face")
            if face is None:
                logger.error("Cannot start screen-direct: FaceService is not registered")
                await context.stop()
                return 1

            logger.info("Starting direct foreground face renderer on the main thread")
            renderer = FaceScreenRenderer(face, loop=None)
            face.screen = renderer
            try:
                renderer.run_foreground()
            finally:
                await context.stop()
            return 0

        if args.once:
            await context.stop()
            return 0

        shutdown = ShutdownSignal()
        shutdown.install()

        web_enabled = bool(config.get("services.webui.enabled", True)) and bool(config.get("webui.enabled", True))
        if web_enabled:
            logger.info("N.O.R.M. beta2-pre3.5-hotfix4 is running. Web UI: http://%s:%s", config.get("webui.host", "0.0.0.0"), config.get("webui.port", 8090))
        else:
            logger.info("N.O.R.M. beta2-pre3.5-hotfix4 is running without Web UI. Press Ctrl+C to stop.")
        heartbeat_seconds = int(config.get("runtime.heartbeat_seconds", 30))
        heartbeat_task = asyncio.create_task(context.wait_forever(heartbeat_seconds))
        shutdown_task = asyncio.create_task(shutdown.wait())
        _done, pending = await asyncio.wait(
            {heartbeat_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await context.stop()
        return 0
    except KeyboardInterrupt:
        logger.warning("Interrupted")
        await context.stop()
        return 130
    except Exception as exc:  # noqa: BLE001
        try:
            logger.exception("Fatal startup error: %s", exc)
        except Exception:
            print(f"Fatal startup error: {exc}")
        return 1


def print_startup_report(report: dict) -> None:
    app = report.get("app", {})
    print("\n=== N.O.R.M. beta2-pre3.5-hotfix4 startup report ===")
    print(f"App:        {app.get('name')} / {app.get('codename')}")
    print(f"Install ID: {app.get('install_id')}")
    print(f"Safe mode:  {app.get('safe_mode')}")
    print("Services:")
    for name, health in report.get("services", {}).items():
        ok = "OK" if health.get("ok") else "FAIL"
        print(f"  - {name}: {ok} ({health.get('status')})")
        details = health.get("details") or {}
        if name == "face" and details:
            packs = details.get("packs") or []
            print(f"    Face: state={details.get('state')} active_pack={details.get('active_pack')} packs={len(packs)}")
            screen = details.get("screen") or {}
            print(
                f"    Screen: configured={screen.get('configured_enabled')} "
                f"running={screen.get('running')} size={screen.get('width')}x{screen.get('height')} "
                f"fullscreen={screen.get('fullscreen')}"
            )
            if screen.get("last_error"):
                print(f"    Screen error: {screen.get('last_error')}")
        if name == "webui" and details:
            print(f"    Web: enabled={details.get('enabled')} host={details.get('host')} port={details.get('port')}")
            if details.get("routes"):
                print(f"    Plugin routes: {', '.join(details.get('routes'))}")
        if name == "plugin_manager" and details:
            print("    Plugins:")
            for plugin_id, plugin_health in details.items():
                print(
                    f"      - {plugin_id}: {plugin_health.get('status')} "
                    f"enabled={plugin_health.get('enabled')} route={plugin_health.get('route')}"
                )
    print(f"Events seen: {report.get('events_seen')}")
    print("==============================================\n")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
