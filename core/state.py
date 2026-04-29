from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


FACE_MODES = [
    "idle", "listening", "thinking", "speaking", "error", "sleep", "glitch",
    "annoyed", "bored", "worried",
]
DISPLAY_MODES = ["face", "face_control_ui", "config_ui", "camera_ui", "audio_ui", "diagnostics_ui", "shutdown_ui"]


@dataclass
class TouchState:
    x: int = 400
    y: int = 240
    active: bool = False
    tap_count: int = 0
    last_tap_time: float = 0.0
    last_event: str = "NONE"
    device_name: str = "UNKNOWN"
    error: str = ""


@dataclass
class NormState:
    system_name: str = "N.O.R.M."
    version: str = "0.02-alpha-r4-memory"
    started_at: float = field(default_factory=time.time)

    display_mode: str = "face"
    face_mode: str = "idle"
    theme: str = "norm_terminal_amber"
    status_text: str = "LISTENING..."

    brain_status: str = "offline"
    last_brain_prompt: Optional[str] = None
    last_brain_response: Optional[str] = None
    last_brain_at: Optional[float] = None
    last_brain_latency_ms: Optional[int] = None
    last_brain_error: Optional[str] = None

    camera_status: str = "unknown"
    audio_input_status: str = "unknown"
    audio_output_status: str = "unknown"
    speech_status: str = "unknown"
    last_tts_text: Optional[str] = None
    last_tts_path: Optional[str] = None
    last_tts_at: Optional[float] = None

    glitch_enabled: bool = True
    temporary_glitch_until: Optional[float] = None
    look_x: float = 0.0
    look_y: float = 0.0
    blink_requested: bool = False
    last_error: Optional[str] = None

    last_camera_snapshot: Optional[str] = None
    last_camera_snapshot_at: Optional[float] = None
    last_audio_recording: Optional[str] = None
    last_audio_recording_at: Optional[float] = None
    last_audio_playback_at: Optional[float] = None
    last_action: str = "BOOT"

    shutdown_requested: bool = False
    shutdown_reason: Optional[str] = None

    last_interaction_at: float = field(default_factory=time.time)

    touch: TouchState = field(default_factory=TouchState)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def mark_interaction(self, reason: str = "activity") -> None:
        """Record user/system activity so the idle personality timer backs off."""
        with self.lock:
            self.last_interaction_at = time.time()

    def request_shutdown(self, reason: str = "requested") -> None:
        with self.lock:
            self.shutdown_requested = True
            self.shutdown_reason = reason
            self.last_action = f"EXIT REQUESTED: {reason}"
            self.last_interaction_at = time.time()

    def set_face_mode(self, mode: str) -> None:
        with self.lock:
            if mode not in FACE_MODES:
                raise ValueError(f"Invalid face mode: {mode}")
            self.face_mode = mode
            self.status_text = status_for_mode(mode)
            self.last_action = f"FACE MODE -> {mode.upper()}"
            self.last_interaction_at = time.time()

    def cycle_face_mode(self) -> str:
        with self.lock:
            cycle = ["idle", "listening", "thinking", "speaking", "error", "sleep"]
            try:
                idx = cycle.index(self.face_mode)
            except ValueError:
                idx = 0
            new_mode = cycle[(idx + 1) % len(cycle)]
            self.face_mode = new_mode
            self.status_text = status_for_mode(new_mode)
            self.last_action = f"FACE MODE -> {new_mode.upper()}"
            self.last_interaction_at = time.time()
            return new_mode

    def set_display_mode(self, mode: str) -> None:
        with self.lock:
            if mode not in DISPLAY_MODES:
                raise ValueError(f"Invalid display mode: {mode}")
            self.display_mode = mode
            self.last_action = f"DISPLAY MODE -> {mode.upper()}"
            self.last_interaction_at = time.time()

    def request_blink(self) -> None:
        with self.lock:
            self.blink_requested = True
            self.last_action = "BLINK REQUESTED"
            self.last_interaction_at = time.time()

    def trigger_glitch(self, duration_seconds: float = 0.9) -> None:
        with self.lock:
            self.temporary_glitch_until = time.time() + duration_seconds
            self.last_action = "GLITCH REQUESTED"
            self.last_interaction_at = time.time()

    def set_idle_expression(self, mode: str) -> None:
        """Set a temporary internal idle expression without counting it as user activity."""
        with self.lock:
            if mode not in ("annoyed", "bored", "worried", "idle"):
                return
            self.face_mode = mode
            self.status_text = status_for_mode(mode)
            if mode == "idle":
                self.last_action = "IDLE WATCH"
            else:
                self.last_action = f"IDLE EXPRESSION -> {mode.upper()}"

    def set_error(self, message: str) -> None:
        with self.lock:
            self.last_error = message
            self.face_mode = "error"
            self.status_text = "ERROR DETECTED"
            self.last_action = f"ERROR: {message}"
            self.last_interaction_at = time.time()

    def clear_error(self) -> None:
        with self.lock:
            self.last_error = None
            self.face_mode = "idle"
            self.status_text = "LISTENING..."
            self.last_action = "ERROR CLEARED"
            self.last_interaction_at = time.time()

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "system_name": self.system_name,
                "version": self.version,
                "started_at": self.started_at,
                "uptime_seconds": int(time.time() - self.started_at),
                "hostname": socket.gethostname(),
                "lan_ip": get_lan_ip(),
                "display_mode": self.display_mode,
                "face_mode": self.face_mode,
                "theme": self.theme,
                "status_text": self.status_text,
                "brain_status": self.brain_status,
                "last_brain_prompt": self.last_brain_prompt,
                "last_brain_response": self.last_brain_response,
                "last_brain_at": self.last_brain_at,
                "last_brain_latency_ms": self.last_brain_latency_ms,
                "last_brain_error": self.last_brain_error,
                "camera_status": self.camera_status,
                "audio_input_status": self.audio_input_status,
                "audio_output_status": self.audio_output_status,
                "speech_status": self.speech_status,
                "last_tts_text": self.last_tts_text,
                "last_tts_path": self.last_tts_path,
                "last_tts_at": self.last_tts_at,
                "glitch_enabled": self.glitch_enabled,
                "temporary_glitch_until": self.temporary_glitch_until,
                "look_x": self.look_x,
                "look_y": self.look_y,
                "blink_requested": self.blink_requested,
                "last_error": self.last_error,
                "last_camera_snapshot": self.last_camera_snapshot,
                "last_camera_snapshot_at": self.last_camera_snapshot_at,
                "last_audio_recording": self.last_audio_recording,
                "last_audio_recording_at": self.last_audio_recording_at,
                "last_audio_playback_at": self.last_audio_playback_at,
                "last_action": self.last_action,
                "shutdown_requested": self.shutdown_requested,
                "shutdown_reason": self.shutdown_reason,
                "last_interaction_at": self.last_interaction_at,
                "idle_seconds": int(time.time() - self.last_interaction_at),
                "touch": {
                    "x": self.touch.x,
                    "y": self.touch.y,
                    "active": self.touch.active,
                    "tap_count": self.touch.tap_count,
                    "last_tap_time": self.touch.last_tap_time,
                    "last_event": self.touch.last_event,
                    "device_name": self.touch.device_name,
                    "error": self.touch.error,
                },
            }


def status_for_mode(mode: str) -> str:
    return {
        "idle": "LISTENING...",
        "listening": "LISTENING...",
        "thinking": "PROCESSING",
        "speaking": "RESPONSE ACTIVE",
        "error": "ERROR DETECTED",
        "sleep": "STANDBY",
        "glitch": "SIGNAL INSTABILITY",
        "annoyed": "ANNOYED",
        "bored": "BORED",
        "worried": "MILDLY CONCERNED",
    }.get(mode, "LISTENING...")


def get_lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "unknown"


def state_from_config(config: Dict[str, Any]) -> NormState:
    system = config.get("system", {})
    face = config.get("face", {})
    st = NormState(
        system_name=system.get("name", "N.O.R.M."),
        version=system.get("version", "0.02-alpha-r4-memory"),
        display_mode=config.get("local_ui", {}).get("default_display_mode", "face"),
        face_mode=face.get("idle_mode", "idle"),
        theme=face.get("theme", "norm_terminal_amber"),
        status_text=face.get("default_status_text", "LISTENING..."),
        glitch_enabled=bool(face.get("allow_glitch", True)),
    )
    return st
