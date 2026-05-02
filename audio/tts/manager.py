from __future__ import annotations

from pathlib import Path
from typing import Any

from audio.tts.espeak_engine import EspeakEngine
from audio.tts.piper_engine import PiperEngine


class TTSManager:
    def __init__(self, context, audio_service):
        self.context = context
        self.audio = audio_service
        self.engines = {
            "piper": PiperEngine(context, audio_service),
            "espeak": EspeakEngine(context, audio_service),
        }
        self.last_result: dict[str, Any] | None = None
        self.last_error: str | None = None

    def _tts_cfg(self) -> dict[str, Any]:
        return ((self.context.config.audio or {}).get("tts") or {})

    def default_engine(self) -> str:
        return str(self._tts_cfg().get("default_engine", "piper"))

    def fallback_engine(self) -> str:
        return str(self._tts_cfg().get("fallback_engine", "espeak"))

    def status(self) -> dict[str, Any]:
        engines = {name: engine.available() for name, engine in self.engines.items()}
        active = self.default_engine()
        if active not in self.engines or not engines.get(active, {}).get("ok"):
            fallback = self.fallback_engine()
            if fallback in self.engines and engines.get(fallback, {}).get("ok"):
                active = fallback
        return {
            "enabled": bool(self._tts_cfg().get("enabled", True)),
            "default_engine": self.default_engine(),
            "fallback_engine": self.fallback_engine(),
            "active_engine": active,
            "engines": engines,
            "last_result": self.last_result,
            "last_error": self.last_error,
        }

    async def synthesize(self, text: str, output_path: Path, engine: str | None = None, allow_fallback: bool = True) -> dict[str, Any]:
        requested = engine or self.default_engine()
        attempted: list[str] = []
        errors: dict[str, str] = {}
        candidates = [requested]
        fallback = self.fallback_engine()
        if allow_fallback and fallback not in candidates:
            candidates.append(fallback)
        for name in candidates:
            attempted.append(name)
            tts_engine = self.engines.get(name)
            if tts_engine is None:
                errors[name] = "unknown engine"
                continue
            avail = tts_engine.available()
            if not avail.get("ok"):
                errors[name] = str(avail.get("reason") or "not available")
                continue
            try:
                result = await tts_engine.speak_to_file(text, output_path)
                result["attempted"] = attempted
                self.last_result = result
                self.last_error = None
                return result
            except Exception as exc:  # noqa: BLE001
                errors[name] = str(exc)
        self.last_error = "; ".join(f"{k}: {v}" for k, v in errors.items()) or "no TTS engine worked"
        raise RuntimeError(self.last_error)
