from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from core.state import NormState

log = logging.getLogger("norm.camera")


def _run(cmd: list[str], timeout: float = 6.0) -> Dict[str, Any]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "stdout": "", "stderr": str(exc)}


def camera_status(config: Dict[str, Any], state: NormState | None = None) -> Dict[str, Any]:
    cfg = config.get("camera", {})
    dev = Path(cfg.get("device", "/dev/video0"))
    snapshot_path = Path(cfg.get("snapshot_path", "/tmp/norm_latest.jpg"))
    enabled = bool(cfg.get("enabled", True))
    exists = dev.exists()

    status = "disabled"
    if enabled:
        status = "ready" if exists else "missing"

    result = {
        "enabled": enabled,
        "device": str(dev),
        "exists": exists,
        "status": status,
        "resolution": cfg.get("resolution", [640, 480]),
        "capture_command": cfg.get("capture_command", "fswebcam"),
        "snapshot_path": str(snapshot_path),
        "snapshot_exists": snapshot_path.exists(),
        "snapshot_size_bytes": snapshot_path.stat().st_size if snapshot_path.exists() else 0,
        "last_modified": snapshot_path.stat().st_mtime if snapshot_path.exists() else None,
    }

    if state is not None and state.camera_status in ("unknown", "missing", "ready"):
        state.camera_status = status

    return result


def list_camera_devices() -> Dict[str, Any]:
    devices = sorted(str(p) for p in Path("/dev").glob("video*"))
    listed = _run(["v4l2-ctl", "--list-devices"], timeout=5)
    return {
        "video_paths": devices,
        "v4l2": listed.get("stdout") or listed.get("stderr") or "",
        "ok": listed.get("ok", False),
    }


def camera_formats(device: str = "/dev/video0") -> Dict[str, Any]:
    if not Path(device).exists():
        return {"ok": False, "device": device, "error": "device does not exist"}
    result = _run(["v4l2-ctl", "--device", device, "--list-formats-ext"], timeout=6)
    return {
        "ok": result.get("ok", False),
        "device": device,
        "formats": result.get("stdout") or result.get("stderr") or "",
    }


def capture_snapshot(config: Dict[str, Any], state: NormState) -> Tuple[bool, str]:
    cfg = config.get("camera", {})
    if not cfg.get("enabled", True):
        state.camera_status = "disabled"
        return False, "Camera disabled in config"

    device = cfg.get("device", "/dev/video0")
    resolution = cfg.get("resolution", [640, 480])
    snapshot_path = cfg.get("snapshot_path", "/tmp/norm_latest.jpg")
    command = cfg.get("capture_command", "fswebcam")

    Path(snapshot_path).parent.mkdir(parents=True, exist_ok=True)

    if not Path(device).exists():
        state.camera_status = "missing"
        state.set_error(f"Camera device missing: {device}")
        return False, f"Camera device missing: {device}"

    if command == "ffmpeg":
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
            "-f", "v4l2",
            "-video_size", f"{resolution[0]}x{resolution[1]}",
            "-i", device,
            "-frames:v", "1",
            snapshot_path,
        ]
    else:
        cmd = [
            "fswebcam",
            "-d", device,
            "-r", f"{resolution[0]}x{resolution[1]}",
            "--no-banner",
            "--jpeg", "90",
            snapshot_path,
        ]

    log.info("Capturing camera snapshot: %s", " ".join(cmd))
    state.camera_status = "capturing"
    state.set_face_mode("thinking")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            state.camera_status = "error"
            msg = result.stderr.strip() or result.stdout.strip() or "Camera command failed"
            state.set_error(f"Camera snapshot failed: {msg[:120]}")
            return False, msg

        if not Path(snapshot_path).exists():
            state.camera_status = "error"
            state.set_error("Camera command succeeded but no snapshot was written")
            return False, "Camera command succeeded but no snapshot was written"

        state.camera_status = "ready"
        state.last_camera_snapshot = snapshot_path
        state.last_camera_snapshot_at = time.time()
        state.set_face_mode("idle")
        state.last_action = f"CAMERA SNAPSHOT {time.strftime('%H:%M:%S')}"
        return True, snapshot_path
    except Exception as exc:
        state.camera_status = "error"
        state.set_error(f"Camera error: {exc}")
        return False, str(exc)
