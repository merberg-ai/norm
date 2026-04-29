from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

try:
    from evdev import InputDevice, ecodes, list_devices
    EVDEV_AVAILABLE = True
except Exception:  # pragma: no cover - evdev may not exist off Pi
    EVDEV_AVAILABLE = False
    InputDevice = None  # type: ignore
    ecodes = None  # type: ignore
    list_devices = None  # type: ignore

from core.state import NormState

log = logging.getLogger("norm.touch")


def _scale(value: int, src_min: int, src_max: int, dst_max: int) -> int:
    if src_max == src_min:
        return 0
    value = max(src_min, min(src_max, value))
    return int((value - src_min) / (src_max - src_min) * dst_max)


def find_touch_device(config: Dict[str, Any]) -> Optional[str]:
    touch_cfg = config.get("touch", {})
    forced = touch_cfg.get("device")
    match_name = str(touch_cfg.get("match_name", "")).lower()

    if forced:
        return forced

    if not EVDEV_AVAILABLE:
        return None

    for path in list_devices():
        dev = InputDevice(path)
        name = dev.name.lower()
        if match_name and match_name in name:
            return path
        if "touch" in name or "qdtech" in name or "mpi5001" in name:
            return path
    return None


class TouchReader:
    def __init__(self, state: NormState, config: Dict[str, Any], width: int, height: int):
        self.state = state
        self.config = config
        self.width = width
        self.height = height
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

    def start(self) -> None:
        if not self.config.get("touch", {}).get("enabled", True):
            log.info("Touch disabled in config")
            return
        if not EVDEV_AVAILABLE:
            self.state.touch.error = "python evdev unavailable"
            log.warning("Touch disabled: evdev unavailable")
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _run(self) -> None:
        touch_cfg = self.config.get("touch", {})
        device_path = find_touch_device(self.config) or "/dev/input/event0"
        invert_x = bool(touch_cfg.get("invert_x", False))
        invert_y = bool(touch_cfg.get("invert_y", False))
        swap_xy = bool(touch_cfg.get("swap_xy", False))
        debounce = float(touch_cfg.get("tap_debounce_seconds", 0.25))

        try:
            dev = InputDevice(device_path)
            self.state.touch.device_name = dev.name
            self.state.touch.last_event = f"OPENED {device_path}"
            log.info("Touch active: %s / %s", device_path, dev.name)

            x_code = y_code = None
            x_info = y_info = None

            for candidate in (ecodes.ABS_MT_POSITION_X, ecodes.ABS_X):
                try:
                    x_info = dev.absinfo(candidate)
                    x_code = candidate
                    break
                except Exception:
                    pass

            for candidate in (ecodes.ABS_MT_POSITION_Y, ecodes.ABS_Y):
                try:
                    y_info = dev.absinfo(candidate)
                    y_code = candidate
                    break
                except Exception:
                    pass

            log.info("Touch X code=%s range=%s", ecodes.ABS.get(x_code, x_code), x_info)
            log.info("Touch Y code=%s range=%s", ecodes.ABS.get(y_code, y_code), y_info)

            down = False
            last_trigger = 0.0

            def trigger_tap(reason: str) -> None:
                nonlocal last_trigger
                now = time.time()
                if now - last_trigger > debounce:
                    with self.state.lock:
                        self.state.touch.tap_count += 1
                        self.state.touch.last_tap_time = now
                        self.state.touch.last_event = f"TAP {self.state.touch.tap_count}: {reason} @ {self.state.touch.x},{self.state.touch.y}"
                    last_trigger = now

            for event in dev.read_loop():
                if self.stop_event.is_set():
                    break

                if event.type == ecodes.EV_ABS:
                    code_name = ecodes.ABS.get(event.code, str(event.code))
                elif event.type == ecodes.EV_KEY:
                    code_name = ecodes.KEY.get(event.code, str(event.code))
                else:
                    code_name = str(event.code)

                with self.state.lock:
                    self.state.touch.last_event = f"{code_name}={event.value}"

                if event.type == ecodes.EV_ABS:
                    if event.code == x_code and x_info:
                        x = _scale(event.value, x_info.min, x_info.max, self.width - 1)
                        with self.state.lock:
                            if swap_xy:
                                self.state.touch.y = self.height - 1 - x if invert_y else x
                            else:
                                self.state.touch.x = self.width - 1 - x if invert_x else x

                    elif event.code == y_code and y_info:
                        y = _scale(event.value, y_info.min, y_info.max, self.height - 1)
                        with self.state.lock:
                            if swap_xy:
                                self.state.touch.x = self.width - 1 - y if invert_x else y
                            else:
                                self.state.touch.y = self.height - 1 - y if invert_y else y

                    elif event.code == ecodes.ABS_MT_TRACKING_ID:
                        if event.value >= 0:
                            down = True
                            with self.state.lock:
                                self.state.touch.active = True
                            trigger_tap("TRACKING_ID DOWN")
                        else:
                            down = False
                            with self.state.lock:
                                self.state.touch.active = False
                                self.state.touch.last_event = "TRACKING_ID UP"

                    elif event.code == ecodes.ABS_PRESSURE:
                        if event.value > 0 and not down:
                            down = True
                            with self.state.lock:
                                self.state.touch.active = True
                            trigger_tap("PRESSURE DOWN")
                        elif event.value == 0:
                            down = False
                            with self.state.lock:
                                self.state.touch.active = False

                elif event.type == ecodes.EV_KEY:
                    if event.code in (ecodes.BTN_TOUCH, ecodes.BTN_LEFT, ecodes.BTN_TOOL_FINGER):
                        if event.value == 1:
                            down = True
                            with self.state.lock:
                                self.state.touch.active = True
                            trigger_tap(f"{code_name} DOWN")
                        elif event.value == 0:
                            down = False
                            with self.state.lock:
                                self.state.touch.active = False

        except PermissionError:
            self.state.touch.error = "TOUCH PERMISSION DENIED. ADD USER TO input GROUP."
            log.exception("Touch permission denied")
        except Exception as exc:
            self.state.touch.error = f"TOUCH ERROR: {exc}"
            log.exception("Touch reader failed")
