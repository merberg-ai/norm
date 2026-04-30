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
    parser = argparse.ArgumentParser(description="N.O.R.M. beta2-pre1 modular runtime skeleton")
    parser.add_argument("--root", default=".", help="Project root directory. Default: current directory")
    parser.add_argument("--config-dir", default="config", help="Config directory relative to root")
    parser.add_argument("--safe-mode", action="store_true", help="Boot without starting plugins")
    parser.add_argument("--once", action="store_true", help="Start, print health report, then shut down")
    parser.add_argument("--json-health", action="store_true", help="Print health report as JSON")
    return parser


async def amain() -> int:
    args = build_arg_parser().parse_args()
    root = Path(args.root).resolve()

    paths = NormPaths.from_root(root=root, config_dir=args.config_dir)
    paths.ensure()

    config_manager = ConfigManager(paths.config_dir)
    config = config_manager.load()

    # Runtime CLI safe-mode override. We do not write it back to disk.
    if args.safe_mode:
        config.norm.setdefault("app", {})["safe_mode"] = True

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

    shutdown = ShutdownSignal()
    try:
        shutdown.install()
        await context.start()
        report = await context.health_report()

        if config.get("runtime.print_startup_report", True):
            if args.json_health:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print_startup_report(report)

        if args.once:
            await context.stop()
            return 0

        logger.info("N.O.R.M. beta2-pre1 is running. Press Ctrl+C to stop.")
        heartbeat_seconds = int(config.get("runtime.heartbeat_seconds", 30))
        heartbeat_task = asyncio.create_task(context.wait_forever(heartbeat_seconds))
        shutdown_task = asyncio.create_task(shutdown.wait())
        done, pending = await asyncio.wait(
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
    print("\n=== N.O.R.M. beta2-pre1 startup report ===")
    print(f"App:        {app.get('name')} / {app.get('codename')}")
    print(f"Install ID: {app.get('install_id')}")
    print(f"Safe mode:  {app.get('safe_mode')}")
    print("Services:")
    for name, health in report.get("services", {}).items():
        ok = "OK" if health.get("ok") else "FAIL"
        print(f"  - {name}: {ok} ({health.get('status')})")
        details = health.get("details") or {}
        if name == "plugin_manager" and details:
            print("    Plugins:")
            for plugin_id, plugin_health in details.items():
                print(
                    f"      - {plugin_id}: {plugin_health.get('status')} "
                    f"enabled={plugin_health.get('enabled')} route={plugin_health.get('route')}"
                )
    print(f"Events seen: {report.get('events_seen')}")
    print("==========================================\n")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
