#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import threading
import time
from typing import Optional

from core.config import load_config, load_theme
from core.logging import setup_logging
from core.state import state_from_config
from hardware.touch import TouchReader
from hardware import camera, audio
from brain import ollama as brain
from speech import tts
from face.renderer import FaceRenderer
from web.server import start_server_thread


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="N.O.R.M. v0.02-alpha-r4-memory core")
    parser.add_argument("--config", default="configs/norm-alpha.json", help="Path to config JSON")
    parser.add_argument("--no-web", action="store_true", help="Disable web/API server")
    parser.add_argument("--no-display", action="store_true", help="Disable Pygame display renderer")
    parser.add_argument("--no-touch", action="store_true", help="Disable evdev touch reader")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    config = load_config(args.config)
    theme = load_theme(config)
    logger = setup_logging(config)
    state = state_from_config(config)

    logger.info("Starting %s %s", state.system_name, state.version)
    logger.info("Config loaded: %s", config.get("_config_path"))
    logger.info("Theme loaded: %s", theme.get("_theme_path"))

    # Initial lightweight hardware status pass.
    try:
        camera.camera_status(config, state)
    except Exception as exc:
        logger.warning("Initial camera status check failed: %s", exc)

    try:
        audio.audio_status(config, state)
    except Exception as exc:
        logger.warning("Initial audio status check failed: %s", exc)

    try:
        brain.brain_status(config, state)
    except Exception as exc:
        logger.warning("Initial brain status check failed: %s", exc)

    try:
        tts.tts_status(config, state)
    except Exception as exc:
        logger.warning("Initial speech status check failed: %s", exc)

    width = int(config.get("display", {}).get("width", 800))
    height = int(config.get("display", {}).get("height", 480))

    touch_reader: Optional[TouchReader] = None
    renderer: Optional[FaceRenderer] = None
    stop_event = threading.Event()

    def force_exit_later(code: int = 130, delay: float = 2.0) -> None:
        """Safety valve for dev mode if SDL/Pygame or a worker refuses to exit."""
        def killer() -> None:
            time.sleep(delay)
            if stop_event.is_set():
                logger.warning("Forced exit after signal; one subsystem did not stop cleanly")
                os._exit(code)

        threading.Thread(target=killer, daemon=True).start()

    def request_stop(reason: str, code: int = 0) -> None:
        nonlocal renderer, touch_reader

        if stop_event.is_set():
            logger.warning("Second shutdown request received; forcing exit")
            os._exit(130 if code == 0 else code)

        logger.info("Shutdown requested: %s", reason)
        stop_event.set()
        state.request_shutdown(reason)

        if touch_reader is not None:
            touch_reader.stop()
        if renderer is not None:
            renderer.stop()

    def handle_signal(signum, frame):
        # Pygame/kmsdrm + background uvicorn can wedge during graceful shutdown on Raspberry Pi Lite.
        # For dev mode, Ctrl-C must always give the terminal back.
        code = 130 if signum == signal.SIGINT else 143
        try:
            os.write(2, f"\nN.O.R.M. received signal {signum}; exiting now.\n".encode())
        except Exception:
            pass
        try:
            stop_event.set()
            state.shutdown_requested = True
            state.shutdown_reason = f"signal {signum}"
            if touch_reader is not None:
                touch_reader.stop()
            if renderer is not None:
                renderer.stop()
        except Exception:
            pass
        os._exit(code)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        if not args.no_touch and config.get("touch", {}).get("enabled", True):
            touch_reader = TouchReader(state, config, width, height)
            touch_reader.start()

        if not args.no_web and config.get("web_ui", {}).get("enabled", True) and config.get("api", {}).get("enabled", True):
            start_server_thread(config, theme, state)
            logger.info("Web/API server thread started")

        if args.no_display or not config.get("display", {}).get("enabled", True):
            logger.info("Display disabled. Running web/API loop only.")
            while not stop_event.is_set() and not state.shutdown_requested:
                time.sleep(0.25)
            return 0

        # Pygame should run on the main thread.
        renderer = FaceRenderer(config, theme, state)
        renderer.run()
        return 0

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt caught")
        request_stop("keyboard interrupt", 130)
        return 130

    finally:
        if touch_reader is not None:
            touch_reader.stop()
        if renderer is not None:
            renderer.stop()
        logger.info("N.O.R.M. shutdown complete")


if __name__ == "__main__":
    raise SystemExit(main())
