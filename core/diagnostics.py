from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

from core.state import NormState, get_lan_ip


def _run(cmd: list[str], timeout: float = 4.0) -> Dict[str, Any]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "cmd": cmd,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "cmd": cmd}


def _read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return None


def cpu_temperature_c() -> float | None:
    raw = _read_text("/sys/class/thermal/thermal_zone0/temp")
    if not raw:
        return None
    try:
        value = float(raw)
        # Raspberry Pi usually reports millidegrees C.
        if value > 1000:
            value = value / 1000.0
        return round(value, 1)
    except Exception:
        return None


def memory_info() -> Dict[str, Any]:
    data: Dict[str, int] = {}
    raw = _read_text("/proc/meminfo") or ""
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            key = parts[0].rstrip(":")
            try:
                data[key] = int(parts[1])  # kB
            except ValueError:
                pass

    total = data.get("MemTotal")
    available = data.get("MemAvailable")
    if total and available is not None:
        used = total - available
        return {
            "total_mb": round(total / 1024, 1),
            "available_mb": round(available / 1024, 1),
            "used_mb": round(used / 1024, 1),
            "used_percent": round((used / total) * 100, 1),
        }
    return {}


def disk_info(path: str = "/") -> Dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
        return {
            "path": path,
            "total_gb": round(usage.total / (1024 ** 3), 2),
            "used_gb": round(usage.used / (1024 ** 3), 2),
            "free_gb": round(usage.free / (1024 ** 3), 2),
            "used_percent": round((usage.used / usage.total) * 100, 1),
        }
    except Exception as exc:
        return {"path": path, "error": str(exc)}


def load_info() -> Dict[str, Any]:
    try:
        one, five, fifteen = os.getloadavg()
        return {"1m": round(one, 2), "5m": round(five, 2), "15m": round(fifteen, 2)}
    except Exception:
        return {}


def device_exists(path: str | None) -> bool:
    if not path:
        return False
    return Path(path).exists()


def summarize_audio_cards() -> Dict[str, Any]:
    return {
        "cards": _read_text("/proc/asound/cards") or "",
        "playback": (_run(["aplay", "-l"], timeout=4).get("stdout") or ""),
        "capture": (_run(["arecord", "-l"], timeout=4).get("stdout") or ""),
    }


def summarize_video_devices() -> Dict[str, Any]:
    video_paths = sorted(str(p) for p in Path("/dev").glob("video*"))
    listed = _run(["v4l2-ctl", "--list-devices"], timeout=4)
    return {
        "paths": video_paths,
        "v4l2_list": listed.get("stdout") or listed.get("stderr") or "",
    }


def get_system_diagnostics(config: Dict[str, Any], state: NormState) -> Dict[str, Any]:
    snap = state.snapshot()
    cam_cfg = config.get("camera", {})
    touch_cfg = config.get("touch", {})
    audio_cfg = config.get("audio", {})
    input_cfg = audio_cfg.get("input", {})
    output_cfg = audio_cfg.get("output", {})

    boot_time = snap.get("started_at", time.time())

    return {
        "system": {
            "name": snap.get("system_name"),
            "version": snap.get("version"),
            "profile": config.get("system", {}).get("profile"),
            "hostname": socket.gethostname(),
            "lan_ip": get_lan_ip(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "uptime_seconds": snap.get("uptime_seconds"),
            "started_at": boot_time,
        },
        "cpu": {
            "temperature_c": cpu_temperature_c(),
            "load": load_info(),
        },
        "memory": memory_info(),
        "disk": disk_info("/"),
        "display": config.get("display", {}),
        "touch": {
            "configured_device": touch_cfg.get("device"),
            "configured_exists": device_exists(touch_cfg.get("device")),
            "runtime_device": snap.get("touch", {}).get("device_name"),
            "tap_count": snap.get("touch", {}).get("tap_count"),
            "xy": [snap.get("touch", {}).get("x"), snap.get("touch", {}).get("y")],
            "last_event": snap.get("touch", {}).get("last_event"),
            "error": snap.get("touch", {}).get("error"),
        },
        "camera": {
            "enabled": bool(cam_cfg.get("enabled", True)),
            "device": cam_cfg.get("device", "/dev/video0"),
            "device_exists": device_exists(cam_cfg.get("device", "/dev/video0")),
            "resolution": cam_cfg.get("resolution", [640, 480]),
            "capture_command": cam_cfg.get("capture_command", "fswebcam"),
            "snapshot_path": cam_cfg.get("snapshot_path", "/tmp/norm_latest.jpg"),
            "snapshot_exists": device_exists(cam_cfg.get("snapshot_path", "/tmp/norm_latest.jpg")),
            "last_snapshot": snap.get("last_camera_snapshot"),
            "last_snapshot_at": snap.get("last_camera_snapshot_at"),
            "status": snap.get("camera_status"),
        },
        "brain": {
            "enabled": bool(config.get("brain", {}).get("enabled", False)),
            "provider": config.get("brain", {}).get("provider", "ollama"),
            "host": config.get("brain", {}).get("host"),
            "model": config.get("brain", {}).get("chat_model"),
            "status": snap.get("brain_status"),
            "last_prompt": snap.get("last_brain_prompt"),
            "last_response": snap.get("last_brain_response"),
            "last_at": snap.get("last_brain_at"),
            "last_latency_ms": snap.get("last_brain_latency_ms"),
            "last_error": snap.get("last_brain_error"),
        },
        "audio": {
            "input_device": input_cfg.get("device"),
            "output_device": output_cfg.get("device"),
            "input_status": snap.get("audio_input_status"),
            "output_status": snap.get("audio_output_status"),
            "last_recording": snap.get("last_audio_recording"),
            "last_recording_at": snap.get("last_audio_recording_at"),
            "last_playback_at": snap.get("last_audio_playback_at"),
        },
        "state": {
            "display_mode": snap.get("display_mode"),
            "face_mode": snap.get("face_mode"),
            "status_text": snap.get("status_text"),
            "last_action": snap.get("last_action"),
            "last_error": snap.get("last_error"),
        },
    }


def get_hardware_report(config: Dict[str, Any], state: NormState) -> Dict[str, Any]:
    # Keep the heavy-ish command output out of the normal diagnostics payload unless requested.
    return {
        "diagnostics": get_system_diagnostics(config, state),
        "video": summarize_video_devices(),
        "audio": summarize_audio_cards(),
        "usb": _run(["lsusb"], timeout=4).get("stdout") or "",
        "input_devices": _read_text("/proc/bus/input/devices") or "",
    }
