from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from core.state import NormState

log = logging.getLogger("norm.audio")


def _run(cmd: list[str], timeout: float = 6.0) -> Dict[str, Any]:
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
        return {"ok": False, "error": str(exc), "stdout": "", "stderr": str(exc), "cmd": cmd}


def _resolve_path(config: Dict[str, Any], path: str | None) -> Path:
    if not path:
        return Path("")
    p = Path(path)
    if p.is_absolute():
        return p
    return Path(config.get("_base_dir", ".")).resolve() / p


def list_audio_devices() -> Dict[str, Any]:
    cards_path = Path("/proc/asound/cards")
    return {
        "ok": True,
        "cards": cards_path.read_text(encoding="utf-8", errors="replace") if cards_path.exists() else "",
        "playback_hardware": _run(["aplay", "-l"], timeout=4),
        "capture_hardware": _run(["arecord", "-l"], timeout=4),
        "playback_names": _run(["aplay", "-L"], timeout=5),
        "capture_names": _run(["arecord", "-L"], timeout=5),
    }


def audio_status(config: Dict[str, Any], state: NormState) -> Dict[str, Any]:
    audio_cfg = config.get("audio", {})
    input_cfg = audio_cfg.get("input", {})
    output_cfg = audio_cfg.get("output", {})
    record_path = _resolve_path(config, input_cfg.get("test_record_path", "/tmp/norm_mic_test.wav"))
    startup = _resolve_path(config, output_cfg.get("startup_sound", "sounds/startup.wav"))
    error = _resolve_path(config, output_cfg.get("error_sound", "sounds/error.wav"))

    # Keep disabled devices shown as disabled every time, not stale error/configured.
    if not input_cfg.get("enabled", True):
        state.audio_input_status = "disabled"
    elif state.audio_input_status == "unknown":
        state.audio_input_status = "configured"

    if not output_cfg.get("enabled", True):
        state.audio_output_status = "disabled"
    elif state.audio_output_status == "unknown":
        state.audio_output_status = "configured"

    return {
        "input": {
            "enabled": bool(input_cfg.get("enabled", True)),
            "device": input_cfg.get("device", "default"),
            "sample_rate": input_cfg.get("sample_rate", 16000),
            "channels": input_cfg.get("channels", 1),
            "record_seconds": input_cfg.get("record_seconds", 5),
            "status": state.audio_input_status,
            "test_record_path": str(record_path),
            "test_record_exists": record_path.exists(),
            "test_record_size_bytes": record_path.stat().st_size if record_path.exists() else 0,
            "last_recording": state.last_audio_recording,
            "last_recording_at": state.last_audio_recording_at,
        },
        "output": {
            "enabled": bool(output_cfg.get("enabled", True)),
            "device": output_cfg.get("device", "default"),
            "status": state.audio_output_status,
            "startup_sound": str(startup),
            "startup_sound_exists": startup.exists(),
            "error_sound": str(error),
            "error_sound_exists": error.exists(),
            "last_playback_at": state.last_audio_playback_at,
        },
        "state": state.snapshot(),
    }


def record_test(config: Dict[str, Any], state: NormState) -> Tuple[bool, str]:
    cfg = config.get("audio", {}).get("input", {})
    if not cfg.get("enabled", True):
        state.audio_input_status = "disabled"
        state.last_action = "AUDIO INPUT DISABLED"
        return False, "Audio input disabled in config"

    device = cfg.get("device", "default")
    sample_rate = str(cfg.get("sample_rate", 16000))
    channels = str(cfg.get("channels", 1))
    seconds = str(cfg.get("record_seconds", 5))
    path = _resolve_path(config, cfg.get("test_record_path", "/tmp/norm_mic_test.wav"))
    path.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["arecord", "-D", device, "-f", "S16_LE", "-r", sample_rate, "-c", channels, "-d", seconds, str(path)]
    log.info("Recording audio test: %s", " ".join(cmd))
    state.audio_input_status = "recording"
    state.set_face_mode("listening")
    state.last_action = "MIC RECORDING ACTIVE"

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=int(float(seconds)) + 5)
        if result.returncode != 0:
            state.audio_input_status = "error"
            msg = result.stderr.strip() or result.stdout.strip() or "arecord failed"
            state.set_error(f"Mic record failed: {msg[:120]}")
            return False, msg

        state.audio_input_status = "ready"
        state.last_audio_recording = str(path)
        state.last_audio_recording_at = time.time()
        # A successful mic test should not keep an old playback error screaming on the dashboard.
        if state.last_error and str(state.last_error).lower().startswith("audio"):
            state.last_error = None
        state.set_face_mode("idle")
        state.last_action = f"MIC RECORD TEST {time.strftime('%H:%M:%S')}"
        return True, str(path)
    except Exception as exc:
        state.audio_input_status = "error"
        state.set_error(f"Mic error: {exc}")
        return False, str(exc)


def play_recording(config: Dict[str, Any], state: NormState) -> Tuple[bool, str]:
    path = state.last_audio_recording or config.get("audio", {}).get("input", {}).get("test_record_path", "/tmp/norm_mic_test.wav")
    return play_file(config, state, path)


def play_test(config: Dict[str, Any], state: NormState) -> Tuple[bool, str]:
    output = config.get("audio", {}).get("output", {})
    startup = output.get("startup_sound")
    if startup and _resolve_path(config, startup).exists():
        return play_file(config, state, startup)
    return play_file(config, state, "/usr/share/sounds/alsa/Front_Center.wav")


def play_file(config: Dict[str, Any], state: NormState, path: str) -> Tuple[bool, str]:
    cfg = config.get("audio", {}).get("output", {})
    if not cfg.get("enabled", True):
        state.audio_output_status = "disabled"
        state.set_face_mode("idle")
        # This is not an error during bench testing; N.O.R.M. simply has no mouth attached yet.
        if state.last_error and str(state.last_error).lower().startswith("audio"):
            state.last_error = None
        state.last_action = "AUDIO OUTPUT DISABLED"
        return False, "Audio output disabled in config"

    device = cfg.get("device", "default")
    audio_path = _resolve_path(config, path)
    if not audio_path.exists():
        state.audio_output_status = "error"
        state.set_error(f"Audio file not found: {audio_path}")
        return False, f"Audio file not found: {audio_path}"

    cmd = ["aplay", "-D", device, str(audio_path)]
    log.info("Playing audio: %s", " ".join(cmd))
    state.audio_output_status = "playing"
    state.set_face_mode("speaking")
    state.last_action = "AUDIO PLAYBACK ACTIVE"

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            state.audio_output_status = "error"
            msg = result.stderr.strip() or result.stdout.strip() or "aplay failed"
            state.set_error(f"Audio play failed: {msg[:120]}")
            return False, msg

        state.audio_output_status = "ready"
        state.last_audio_playback_at = time.time()
        state.set_face_mode("idle")
        state.last_action = f"AUDIO PLAYBACK {time.strftime('%H:%M:%S')}"
        return True, str(audio_path)
    except Exception as exc:
        state.audio_output_status = "error"
        state.set_error(f"Audio playback error: {exc}")
        return False, str(exc)
