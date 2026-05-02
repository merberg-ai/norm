from __future__ import annotations

import os
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any


class ModelManager:
    def __init__(self, context):
        self.context = context
        self.last_download: dict[str, Any] | None = None

    def _audio_config(self) -> dict[str, Any]:
        return self.context.config.audio or {}

    def _resolve(self, raw: str | Path) -> Path:
        path = Path(raw)
        if not path.is_absolute():
            path = self.context.root / path
        return path

    def piper_model_dir(self) -> Path:
        audio = self._audio_config()
        return self._resolve(audio.get("tts", {}).get("piper", {}).get("model_dir", "./models/piper"))

    def piper_voices_config(self) -> dict[str, Any]:
        return ((self._audio_config().get("models") or {}).get("piper") or {}).get("voices") or {}

    def selected_piper_voice(self) -> str:
        audio = self._audio_config()
        return str(
            ((audio.get("models") or {}).get("piper") or {}).get("selected_voice")
            or (audio.get("tts", {}).get("piper", {}) or {}).get("selected_voice")
            or "en_US-lessac-medium"
        )

    def piper_voice_paths(self, voice_id: str | None = None) -> dict[str, Path]:
        voice_id = voice_id or self.selected_piper_voice()
        voices = self.piper_voices_config()
        voice = voices.get(voice_id) or {}
        model_dir = self.piper_model_dir()
        return {
            "model": model_dir / str(voice.get("model_file", f"{voice_id}.onnx")),
            "config": model_dir / str(voice.get("config_file", f"{voice_id}.onnx.json")),
            "model_card": model_dir / str(voice.get("model_card_file", "MODEL_CARD")),
        }

    def piper_voice_status(self, voice_id: str | None = None) -> dict[str, Any]:
        voice_id = voice_id or self.selected_piper_voice()
        voice = self.piper_voices_config().get(voice_id) or {}
        paths = self.piper_voice_paths(voice_id)
        files = {}
        missing = []
        for key, path in paths.items():
            exists = path.exists()
            files[key] = {
                "path": str(path),
                "exists": exists,
                "size": path.stat().st_size if exists else 0,
            }
            if key in {"model", "config"} and not exists:
                missing.append(key)
        return {
            "voice_id": voice_id,
            "label": voice.get("label", voice_id),
            "language": voice.get("language", ""),
            "size_hint": voice.get("size_hint", ""),
            "ok": not missing,
            "missing": missing,
            "files": files,
            "urls": {
                "model": voice.get("model_url", ""),
                "config": voice.get("config_url", ""),
                "model_card": voice.get("model_card_url", ""),
            },
        }

    def all_piper_status(self) -> dict[str, Any]:
        return {
            "selected_voice": self.selected_piper_voice(),
            "model_dir": str(self.piper_model_dir()),
            "voices": {voice_id: self.piper_voice_status(voice_id) for voice_id in self.piper_voices_config().keys()},
            "last_download": self.last_download,
        }

    def _download_one(self, url: str, dest: Path) -> dict[str, Any]:
        if not url:
            raise RuntimeError(f"Missing download URL for {dest.name}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        started = time.time()
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".download", dir=str(dest.parent))
        os.close(tmp_fd)
        tmp_path = Path(tmp_name)
        try:
            with urllib.request.urlopen(url, timeout=60) as response, tmp_path.open("wb") as handle:
                total = 0
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    handle.write(chunk)
                    total += len(chunk)
            tmp_path.replace(dest)
            return {"ok": True, "path": str(dest), "bytes": dest.stat().st_size, "seconds": round(time.time() - started, 2)}
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise

    def download_piper_voice(self, voice_id: str | None = None, force: bool = False) -> dict[str, Any]:
        voice_id = voice_id or self.selected_piper_voice()
        voices = self.piper_voices_config()
        if voice_id not in voices:
            raise RuntimeError(f"Unknown Piper voice: {voice_id}")
        voice = voices[voice_id]
        paths = self.piper_voice_paths(voice_id)
        urls = {
            "model": voice.get("model_url", ""),
            "config": voice.get("config_url", ""),
            "model_card": voice.get("model_card_url", ""),
        }
        results = {}
        for key in ("model", "config", "model_card"):
            dest = paths[key]
            if dest.exists() and not force:
                results[key] = {"ok": True, "path": str(dest), "skipped": True, "bytes": dest.stat().st_size}
                continue
            # MODEL_CARD is helpful but not required for synthesis; don't kill the whole install if it fails.
            try:
                results[key] = self._download_one(str(urls[key]), dest)
            except Exception as exc:  # noqa: BLE001
                if key == "model_card":
                    results[key] = {"ok": False, "optional": True, "error": str(exc)}
                else:
                    raise
        self.last_download = {"voice_id": voice_id, "force": force, "results": results, "status": self.piper_voice_status(voice_id)}
        return self.last_download
