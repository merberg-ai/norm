from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from core.state import NormState
from hardware import audio

log = logging.getLogger("norm.speech.tts")


def _resolve_path(config: Dict[str, Any], path: str | None) -> Path:
    if not path:
        return Path("")
    p = Path(path)
    if p.is_absolute():
        return p
    return Path(config.get("_base_dir", ".")).resolve() / p


def _tts_cfg(config: Dict[str, Any]) -> Dict[str, Any]:
    speech = config.setdefault("speech", {})
    return speech.setdefault("tts", config.get("tts", {}))


def voice_presets() -> list[dict[str, Any]]:
    return [
        {"id": "creepy_terminal", "name": "Creepy Terminal", "voice": "en-us+m3", "speed": 130, "pitch": 28, "amplitude": 135, "word_gap": 5, "description": "Slow, low, machine-like default for N.O.R.M."},
        {"id": "deep_overseer", "name": "Deep Overseer", "voice": "en-us+m7", "speed": 115, "pitch": 20, "amplitude": 150, "word_gap": 7, "description": "Deeper, slower, more ominous."},
        {"id": "clear_assistant", "name": "Clear Assistant", "voice": "en-us+m1", "speed": 150, "pitch": 42, "amplitude": 120, "word_gap": 3, "description": "More understandable for normal assistant responses."},
        {"id": "fast_diagnostic", "name": "Fast Diagnostic", "voice": "en-us", "speed": 170, "pitch": 45, "amplitude": 115, "word_gap": 1, "description": "Quick system-report voice."},
        {"id": "speak_spell_goblin", "name": "Speak & Spell Goblin", "voice": "en-us+m4", "speed": 145, "pitch": 55, "amplitude": 120, "word_gap": 2, "description": "Leans into the cursed 1980s computer vibe."},
    ]


def apply_preset_to_config(config: Dict[str, Any], preset_id: str) -> Dict[str, Any] | None:
    preset = next((p for p in voice_presets() if p["id"] == preset_id), None)
    if not preset:
        return None
    cfg = _tts_cfg(config)
    cfg["voice_preset"] = preset["id"]
    for key in ("voice", "speed", "pitch", "amplitude", "word_gap"):
        cfg[key] = preset[key]
    return preset


def tts_status(config: Dict[str, Any], state: NormState | None = None) -> Dict[str, Any]:
    cfg = _tts_cfg(config)
    provider = cfg.get("provider", "espeak-ng")
    enabled = bool(cfg.get("enabled", False))
    output_path = _resolve_path(config, cfg.get("output_path", "/tmp/norm_tts.wav"))
    espeak = subprocess.run(["bash", "-lc", "command -v espeak-ng"], capture_output=True, text=True)
    available = espeak.returncode == 0
    status = "ready" if enabled and provider == "espeak-ng" and available else "disabled" if not enabled else "missing"
    if state is not None:
        state.speech_status = status
    return {
        "ok": status == "ready" or not enabled,
        "enabled": enabled,
        "provider": provider,
        "status": status,
        "espeak_ng_available": available,
        "espeak_ng_path": espeak.stdout.strip(),
        "voice_preset": cfg.get("voice_preset", "creepy_terminal"),
        "voice": cfg.get("voice", "en-us+m3"),
        "speed": int(cfg.get("speed", 130)),
        "pitch": int(cfg.get("pitch", 28)),
        "amplitude": int(cfg.get("amplitude", 135)),
        "word_gap": int(cfg.get("word_gap", 5)),
        "max_spoken_chars": int(cfg.get("max_spoken_chars", 500)),
        "speak_brain_responses_by_default": bool(cfg.get("speak_brain_responses_by_default", False)),
        "output_path": str(output_path),
        "output_exists": output_path.exists(),
        "output_size_bytes": output_path.stat().st_size if output_path.exists() else 0,
        "presets": voice_presets(),
        "future_providers": cfg.get("future_providers", ["piper", "remote"]),
    }


def synthesize(config: Dict[str, Any], state: NormState, text: str, output_path: str | None = None) -> Tuple[bool, str, Dict[str, Any]]:
    cfg = _tts_cfg(config)
    if not cfg.get("enabled", False):
        state.speech_status = "disabled"
        state.last_action = "TTS DISABLED"
        return False, "TTS disabled in config", tts_status(config, state)
    provider = cfg.get("provider", "espeak-ng")
    if provider != "espeak-ng":
        msg = f"Unsupported TTS provider: {provider}"
        state.speech_status = "error"
        state.set_error(msg)
        return False, msg, tts_status(config, state)
    text = (text or "").strip()
    if not text:
        return False, "No text provided", tts_status(config, state)
    text = text[: int(cfg.get("max_spoken_chars", 500))]
    out = _resolve_path(config, output_path or cfg.get("output_path", "/tmp/norm_tts.wav"))
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "espeak-ng", "-v", str(cfg.get("voice", "en-us+m3")),
        "-s", str(int(cfg.get("speed", 130))),
        "-p", str(int(cfg.get("pitch", 28))),
        "-a", str(int(cfg.get("amplitude", 135))),
        "-g", str(int(cfg.get("word_gap", 5))),
        "-w", str(out), text,
    ]
    state.speech_status = "synthesizing"
    state.last_tts_text = text
    state.last_action = "TTS SYNTHESIS ACTIVE"
    log.info("Synthesizing speech: %s", " ".join(cmd[:-1]) + " <text>")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=float(cfg.get("synthesis_timeout_seconds", 30)))
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip() or "espeak-ng failed"
            state.speech_status = "error"
            state.set_error(f"TTS failed: {msg[:120]}")
            return False, msg, tts_status(config, state)
        state.speech_status = "ready"
        state.last_tts_path = str(out)
        state.last_tts_at = time.time()
        state.last_action = f"TTS READY {time.strftime('%H:%M:%S')}"
        return True, str(out), tts_status(config, state)
    except Exception as exc:
        state.speech_status = "error"
        state.set_error(f"TTS error: {exc}")
        return False, str(exc), tts_status(config, state)


def speak_text(config: Dict[str, Any], state: NormState, text: str) -> Tuple[bool, str, Dict[str, Any]]:
    ok, result, meta = synthesize(config, state, text)
    if not ok:
        return False, result, meta
    play_ok, play_msg = audio.play_file(config, state, result)
    meta = dict(meta)
    meta["playback"] = {"ok": play_ok, "result": play_msg}
    if play_ok:
        state.speech_status = "ready"
        state.last_action = f"SPOKEN RESPONSE {time.strftime('%H:%M:%S')}"
        return True, play_msg, meta
    return False, play_msg, meta


def speak_test(config: Dict[str, Any], state: NormState) -> Tuple[bool, str, Dict[str, Any]]:
    cfg = _tts_cfg(config)
    phrase = cfg.get("test_phrase", "Routine oversight is active. Your compliance has been logged.")
    return speak_text(config, state, phrase)
