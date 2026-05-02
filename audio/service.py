from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from audio.devices import scan_audio_devices
from audio.tts.espeak_engine import EspeakEngine
from audio.tts.piper_engine import PiperEngine
from core.service import BaseService, ServiceHealth


@dataclass
class AudioAction:
    id: str
    kind: str
    status: str = "queued"
    progress: float = 0.0
    message: str = "Queued"
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": round(float(self.progress), 2),
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "result": self.result,
        }


class AudioService(BaseService):
    """Audio devices, TTS, recording, playback, and Piper model management."""

    name = "audio"

    def __init__(self, context):
        super().__init__(context)
        self.audio_config: dict[str, Any] = getattr(context.config, "audio", {}) or {}
        self.actions: dict[str, AudioAction] = {}
        self.devices_cache: dict[str, list[dict[str, Any]]] = {"inputs": [], "outputs": []}
        self.data_dir = self._resolve_path(self._cfg("audio.data_dir", "./data/audio"))
        self.tts_dir = self.data_dir / "tts"
        self.record_dir = self.data_dir / "recordings"
        self.latest_tts_path = self.tts_dir / "latest.wav"
        self.latest_recording_path = self.record_dir / "latest_recording.wav"
        self._cleanup_task: asyncio.Task | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        await super().start()
        self.loop = asyncio.get_running_loop()
        self.tts_dir.mkdir(parents=True, exist_ok=True)
        self.record_dir.mkdir(parents=True, exist_ok=True)
        await self.refresh_devices()
        self._cleanup_task = asyncio.create_task(self._cleanup_actions_loop())
        await self.context.events.publish("audio.ready", self.status_payload(), source="audio")

    async def stop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
        await super().stop()

    def _cfg(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.audio_config
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def _resolve_path(self, raw: str | Path) -> Path:
        path = Path(str(raw))
        return path if path.is_absolute() else (self.context.root / path).resolve()

    async def _cleanup_actions_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            cutoff = time.time() - 1800
            for action_id in list(self.actions.keys()):
                action = self.actions[action_id]
                if action.finished_at and action.finished_at < cutoff:
                    self.actions.pop(action_id, None)

    async def refresh_devices(self) -> dict[str, list[dict[str, Any]]]:
        self.devices_cache = await asyncio.to_thread(scan_audio_devices)
        await self.context.events.publish("audio.devices.scanned", self.devices_cache, source="audio")
        return self.devices_cache

    def _new_action(self, kind: str, message: str) -> AudioAction:
        action = AudioAction(id=uuid.uuid4().hex[:12], kind=kind, message=message)
        self.actions[action.id] = action
        return action

    def action_payload(self, action_id: str) -> dict[str, Any] | None:
        action = self.actions.get(action_id)
        return action.to_dict() if action else None

    def actions_payload(self) -> dict[str, Any]:
        return {action_id: action.to_dict() for action_id, action in sorted(self.actions.items(), key=lambda kv: kv[1].started_at, reverse=True)}

    def _run_action(self, action: AudioAction, runner: Callable[[AudioAction], dict[str, Any]]) -> None:
        async def task() -> None:
            action.status = "running"
            action.progress = max(action.progress, 1)
            try:
                result = await asyncio.to_thread(runner, action)
                action.result = result or {}
                action.status = "success"
                action.progress = 100
                action.message = action.result.get("message") or "Complete"
            except Exception as exc:  # noqa: BLE001
                action.status = "error"
                action.error = str(exc)
                action.message = f"Error: {exc}"
                action.progress = max(action.progress, 100 if action.progress >= 99 else action.progress)
                self.context.logger.exception("Audio action failed: %s", action.kind)
            finally:
                action.finished_at = time.time()

        asyncio.create_task(task())

    def _piper_config(self) -> dict[str, Any]:
        return self._cfg("tts.piper", {}) or {}

    def _espeak_config(self) -> dict[str, Any]:
        return self._cfg("tts.espeak", {}) or {}

    def _piper_voices(self) -> dict[str, Any]:
        cfg = self._piper_config()
        voices = cfg.get("voices") or {}
        if isinstance(voices, dict) and voices:
            return voices
        # Backward-compatible single voice fallback for older configs.
        voice_id = str(cfg.get("voice_id") or "default")
        return {
            voice_id: {
                "label": voice_id,
                "base_url": (cfg.get("download") or {}).get("base_url", ""),
                "model_file": (cfg.get("download") or {}).get("model_file") or Path(str(cfg.get("model_path", "model.onnx"))).name,
                "config_file": (cfg.get("download") or {}).get("config_file") or Path(str(cfg.get("config_path", "model.onnx.json"))).name,
                "model_card_file": (cfg.get("download") or {}).get("model_card_file", "MODEL_CARD"),
                "model_path": cfg.get("model_path"),
                "config_path": cfg.get("config_path"),
                "model_card_path": cfg.get("model_card_path"),
            }
        }

    def _selected_piper_voice_id(self) -> str:
        cfg = self._piper_config()
        voices = self._piper_voices()
        selected = str(cfg.get("voice_id") or cfg.get("selected_voice") or "").strip()
        if selected in voices:
            return selected
        return next(iter(voices.keys()), "default")

    def _piper_voice_config(self, voice_id: str | None = None) -> dict[str, Any]:
        base = dict(self._piper_config())
        voices = self._piper_voices()
        chosen = str(voice_id or self._selected_piper_voice_id())
        if chosen not in voices:
            raise RuntimeError(f"Unknown Piper voice: {chosen}")
        voice = dict(voices[chosen] or {})
        model_dir = self._resolve_path(base.get("model_dir", "./data/models/piper"))
        model_file = str(voice.get("model_file") or f"{chosen}.onnx")
        config_file = str(voice.get("config_file") or f"{model_file}.json")
        model_path = voice.get("model_path") or str(model_dir / model_file)
        config_path = voice.get("config_path") or str(model_dir / config_file)
        model_card_path = voice.get("model_card_path") or str(model_dir / f"{chosen}.MODEL_CARD")
        merged = {k: v for k, v in base.items() if k not in {"voices", "download"}}
        merged.update(voice)
        merged.update({
            "voice_id": chosen,
            "model_path": model_path,
            "config_path": config_path,
            "model_card_path": model_card_path,
        })
        return merged

    def _piper_engine(self, voice_id: str | None = None) -> PiperEngine:
        return PiperEngine(self._piper_voice_config(voice_id), root=self.context.root)

    def _espeak_engine(self) -> EspeakEngine:
        return EspeakEngine(self._espeak_config())

    def _piper_voice_status(self, voice_id: str) -> dict[str, Any]:
        voice_cfg = self._piper_voice_config(voice_id)
        engine = PiperEngine(voice_cfg, root=self.context.root)
        ok, reason = engine.available()
        return {
            "id": voice_id,
            "label": str(voice_cfg.get("label") or voice_id),
            "ok": ok,
            "reason": reason,
            "missing": engine.missing_files(),
            "model_path": str(engine.model_path),
            "config_path": str(engine.config_path),
            "model_card_path": str(self._resolve_path(voice_cfg.get("model_card_path"))),
            "base_url": str(voice_cfg.get("base_url") or ""),
        }

    def engine_status(self) -> dict[str, Any]:
        selected_voice = self._selected_piper_voice_id()
        piper = self._piper_engine(selected_voice)
        espeak = self._espeak_engine()
        piper_ok, piper_reason = piper.available()
        espeak_ok, espeak_reason = espeak.available()
        default_engine = str(self._cfg("tts.default_engine", "piper"))
        active = default_engine if (default_engine == "piper" and piper_ok) or (default_engine == "espeak" and espeak_ok) else None
        if active is None:
            active = "espeak" if espeak_ok else ("piper" if piper_ok else "none")
        voice_statuses = {voice_id: self._piper_voice_status(voice_id) for voice_id in self._piper_voices().keys()}
        return {
            "default_engine": default_engine,
            "active_engine": active,
            "piper": {
                "ok": piper_ok,
                "reason": piper_reason,
                "executable": piper.executable,
                "executable_diagnostics": piper.executable_diagnostics(),
                "voice_id": selected_voice,
                "selected_voice": selected_voice,
                "model_path": str(piper.model_path),
                "config_path": str(piper.config_path),
                "missing": piper.missing_files(),
                "voices": voice_statuses,
            },
            "espeak": {
                "ok": espeak_ok,
                "reason": espeak_reason,
                "executable": espeak.executable,
            },
        }

    def status_payload(self) -> dict[str, Any]:
        return {
            "enabled": bool(self._cfg("audio.enabled", True)),
            "devices": self.devices_cache,
            "selected": {
                "input_device": self._cfg("audio.input_device", "default"),
                "output_device": self._cfg("audio.output_device", "default"),
            },
            "tts": self.engine_status(),
            "latest": {
                "tts_exists": self.latest_tts_path.exists(),
                "recording_exists": self.latest_recording_path.exists(),
            },
            "actions": self.actions_payload(),
        }

    async def start_download_piper(self, voice_id: str | None = None) -> dict[str, Any]:
        chosen = voice_id or self._selected_piper_voice_id()
        action = self._new_action("piper_download", f"Starting Piper voice download: {chosen}")
        self._run_action(action, lambda a: self._download_piper_files(a, chosen))
        return action.to_dict()

    def _download_piper_files(self, action: AudioAction, voice_id: str) -> dict[str, Any]:
        piper_cfg = self._piper_voice_config(voice_id)
        base_url = str(piper_cfg.get("base_url", "")).rstrip("/")
        if not base_url:
            raise RuntimeError(f"Piper download base_url is not configured for {voice_id}")

        model_name = str(piper_cfg.get("model_file") or Path(str(piper_cfg.get("model_path"))).name)
        config_name = str(piper_cfg.get("config_file") or Path(str(piper_cfg.get("config_path"))).name)
        card_name = str(piper_cfg.get("model_card_file") or "MODEL_CARD")
        targets = [
            (f"{base_url}/{model_name}", self._resolve_path(piper_cfg.get("model_path")), "model"),
            (f"{base_url}/{config_name}", self._resolve_path(piper_cfg.get("config_path")), "config"),
            (f"{base_url}/{card_name}", self._resolve_path(piper_cfg.get("model_card_path")), "model_card"),
        ]

        downloaded: list[str] = []
        skipped: list[str] = []
        total_files = len(targets)
        for index, (url, destination, label) in enumerate(targets):
            if destination.exists() and destination.stat().st_size > 0:
                skipped.append(str(destination))
                action.message = f"{voice_id}: {label} already exists"
                action.progress = ((index + 1) / total_files) * 100
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            tmp = destination.with_suffix(destination.suffix + ".part")
            action.message = f"{voice_id}: downloading {label}"
            try:
                self._download_file(url, tmp, action, file_index=index, total_files=total_files)
                tmp.replace(destination)
                downloaded.append(str(destination))
            except Exception:
                tmp.unlink(missing_ok=True)
                # MODEL_CARD is nice to have but should not block a working voice.
                if label == "model_card":
                    action.message = f"{voice_id}: MODEL_CARD skipped"
                    action.progress = ((index + 1) / total_files) * 100
                    continue
                raise
        return {
            "message": f"Piper voice {voice_id} files are installed",
            "voice_id": voice_id,
            "downloaded": downloaded,
            "skipped": skipped,
            "tts": self.engine_status(),
        }

    def _download_file(self, url: str, destination: Path, action: AudioAction, *, file_index: int, total_files: int) -> None:
        request = Request(url, headers={"User-Agent": "NORM-beta2/0.1"})
        with urlopen(request, timeout=30) as response:  # noqa: S310 - user-configured public voice URL
            total_header = response.headers.get("Content-Length")
            total = int(total_header) if total_header and total_header.isdigit() else 0
            downloaded = 0
            with destination.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        file_progress = downloaded / total
                    else:
                        file_progress = 0.5
                    action.progress = ((file_index + file_progress) / total_files) * 100
                    action.message = f"Downloading {destination.name}: {downloaded / (1024*1024):.1f} MB"
        if destination.stat().st_size <= 0:
            raise RuntimeError(f"Downloaded file is empty: {url}")

    async def start_speak(self, text: str, *, output_device: str | None = None, browser_only: bool = False, voice_id: str | None = None) -> dict[str, Any]:
        action = self._new_action("tts", "Starting speech synthesis")
        self._run_action(action, lambda a: self._speak_runner(a, text=text, output_device=output_device, browser_only=browser_only, voice_id=voice_id))
        return action.to_dict()

    def _choose_engine(self, voice_id: str | None = None):
        status = self.engine_status()
        default_engine = status.get("default_engine")
        selected_voice = voice_id or status.get("piper", {}).get("selected_voice") or self._selected_piper_voice_id()
        piper_engine = self._piper_engine(str(selected_voice))
        piper_ok, _ = piper_engine.available()
        espeak_ok = status.get("espeak", {}).get("ok")
        if default_engine == "piper" and piper_ok:
            return piper_engine
        if default_engine == "espeak" and espeak_ok:
            return self._espeak_engine()
        if piper_ok:
            return piper_engine
        if espeak_ok:
            return self._espeak_engine()
        raise RuntimeError("No TTS engine is available. Install Piper TTS in .venv or eSpeak.")

    def _speak_runner(self, action: AudioAction, *, text: str, output_device: str | None, browser_only: bool, voice_id: str | None) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise RuntimeError("No text provided")
        action.progress = 10
        action.message = "Synthesizing speech"
        self._publish_event_from_thread("tts.started", {"text": text[:120]})
        engine = self._choose_engine(voice_id)
        result = engine.synthesize_to_file(text, self.latest_tts_path)
        if not result.ok:
            raise RuntimeError(result.error or "TTS failed")
        action.progress = 70
        if browser_only:
            action.message = "Speech ready for browser playback"
            self._publish_tts_finished()
            return {"message": "Speech generated for browser playback", "engine": result.engine, "browser_url": "/api/core/audio/file/latest_tts.wav"}
        action.message = "Playing speech through speaker"
        self._play_wav(self.latest_tts_path, output_device or str(self._cfg("audio.output_device", "default")))
        self._publish_tts_finished()
        return {"message": "Speech played", "engine": result.engine, "speaker": True, "browser_url": "/api/core/audio/file/latest_tts.wav"}

    def _publish_event_from_thread(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        if not self.loop:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.context.events.publish(event_type, payload or {}, source="audio"),
                self.loop,
            )
        except Exception:
            pass

    def _publish_tts_finished(self) -> None:
        self._publish_event_from_thread("tts.finished", {})

    async def start_record(self, *, seconds: int | None = None, input_device: str | None = None) -> dict[str, Any]:
        action = self._new_action("record", "Starting microphone recording")
        self._run_action(action, lambda a: self._record_runner(a, seconds=seconds, input_device=input_device))
        return action.to_dict()

    def _record_runner(self, action: AudioAction, *, seconds: int | None, input_device: str | None) -> dict[str, Any]:
        if not shutil.which("arecord"):
            raise RuntimeError("arecord not found. Run ./scripts/install_audio_deps.sh")
        max_seconds = int(self._cfg("audio.max_record_seconds", 20))
        duration = int(seconds or self._cfg("audio.record_seconds_default", 5))
        duration = max(1, min(duration, max_seconds))
        device = input_device or str(self._cfg("audio.input_device", "default"))
        sample_rate = int(self._cfg("audio.sample_rate", 44100))
        channels = int(self._cfg("audio.channels", 1))
        self.latest_recording_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["arecord", "-D", device, "-f", "S16_LE", "-r", str(sample_rate), "-c", str(channels), "-d", str(duration), str(self.latest_recording_path)]
        action.message = f"Recording {duration}s from {device}"
        start = time.time()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        while proc.poll() is None:
            elapsed = min(duration, time.time() - start)
            action.progress = (elapsed / duration) * 95
            action.message = f"Recording... {elapsed:.1f}/{duration}s"
            time.sleep(0.2)
        stdout, stderr = proc.communicate(timeout=2)
        if proc.returncode != 0:
            raise RuntimeError((stderr or stdout or "arecord failed").strip())
        if not self.latest_recording_path.exists() or self.latest_recording_path.stat().st_size <= 44:
            raise RuntimeError("Recording file was not created or is empty")
        return {"message": "Recording complete", "seconds": duration, "browser_url": "/api/core/audio/file/latest_recording.wav"}

    async def start_play_recording(self, *, output_device: str | None = None) -> dict[str, Any]:
        action = self._new_action("play_recording", "Starting recording playback")
        self._run_action(action, lambda a: self._play_recording_runner(a, output_device=output_device))
        return action.to_dict()

    def _play_recording_runner(self, action: AudioAction, *, output_device: str | None) -> dict[str, Any]:
        if not self.latest_recording_path.exists():
            raise RuntimeError("No recording exists yet")
        action.progress = 20
        action.message = "Playing latest recording"
        self._play_wav(self.latest_recording_path, output_device or str(self._cfg("audio.output_device", "default")))
        return {"message": "Recording played", "browser_url": "/api/core/audio/file/latest_recording.wav"}

    def _play_wav(self, path: Path, device: str = "default") -> None:
        if not shutil.which("aplay"):
            raise RuntimeError("aplay not found. Run ./scripts/install_audio_deps.sh")
        if not path.exists():
            raise RuntimeError(f"WAV file not found: {path}")
        cmd = ["aplay"]
        if device and device != "default":
            cmd.extend(["-D", device])
        cmd.append(str(path))
        proc = subprocess.run(cmd, check=False, text=True, capture_output=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "aplay failed").strip())

    async def health(self) -> ServiceHealth:
        status = self.status_payload()
        return ServiceHealth(ok=True, status="running" if self.started else "stopped", details=status)
