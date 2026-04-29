from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from core.state import NormState, FACE_MODES, DISPLAY_MODES
from hardware import camera, audio
from brain import ollama as brain
from brain import memory_store
from speech import tts
from core import diagnostics


class FaceStateRequest(BaseModel):
    mode: str


class DisplayModeRequest(BaseModel):
    mode: str


class FaceTextRequest(BaseModel):
    text: str


class BlinkRequest(BaseModel):
    count: int = 1


class GlitchRequest(BaseModel):
    duration_seconds: float = 0.9


class BrainAskRequest(BaseModel):
    prompt: str
    context: str | None = None
    speak: bool | None = None


class SpeechSpeakRequest(BaseModel):
    text: str


class MemoryRememberRequest(BaseModel):
    text: str
    memory_type: str = "note"
    importance: int = 5


class MemoryClearSessionRequest(BaseModel):
    session_id: str | None = None


def _run(cmd: list[str], timeout: float = 5.0) -> Dict[str, Any]:
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


def _clean_config_for_save(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = json.loads(json.dumps(cfg))
    for key in list(cleaned.keys()):
        if key.startswith("_"):
            cleaned.pop(key, None)
    return cleaned


def _write_config(config: Dict[str, Any], new_cfg: Dict[str, Any]) -> Dict[str, Any]:
    config_path = Path(config.get("_config_path", "configs/norm-alpha.json")).expanduser().resolve()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = _clean_config_for_save(new_cfg)

    backup = None
    if config_path.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = config_path.with_suffix(config_path.suffix + f".bak-{stamp}")
        shutil.copy2(config_path, backup)

    tmp = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
    tmp.replace(config_path)

    base_dir = config.get("_base_dir") or str(config_path.parent.parent)
    config.clear()
    config.update(cleaned)
    config["_config_path"] = str(config_path)
    config["_base_dir"] = base_dir
    return {"path": str(config_path), "backup": str(backup) if backup else None}


def _deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    for key, val in src.items():
        if isinstance(val, dict) and isinstance(dst.get(key), dict):
            _deep_merge(dst[key], val)
        else:
            dst[key] = val
    return dst


def _parse_alsa_devices(text: str) -> List[Dict[str, str]]:
    options: List[Dict[str, str]] = []
    rx = re.compile(r"card\s+(\d+):\s*([^\[]+)\[([^\]]+)\],\s*device\s+(\d+):\s*([^\[]+)(?:\[([^\]]+)\])?")
    for line in text.splitlines():
        m = rx.search(line)
        if not m:
            continue
        card, _short_name, card_name, dev, dev_name, dev_label = m.groups()
        value = f"plughw:{card},{dev}"
        label_bits = [value, card_name.strip(), (dev_label or dev_name or "").strip()]
        label = " — ".join([b for b in label_bits if b])
        options.append({"value": value, "label": label, "card": card, "device": dev})
    return options


def _camera_options() -> List[Dict[str, str]]:
    listed = _run(["v4l2-ctl", "--list-devices"], timeout=5)
    text = listed.get("stdout") or listed.get("stderr") or ""
    labels: Dict[str, str] = {}
    current_name = "USB/Video Device"
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if not line.startswith("\t") and not line.startswith(" "):
            current_name = line.rstrip(":")
        else:
            dev = line.strip()
            if dev.startswith("/dev/video"):
                labels[dev] = current_name

    paths = sorted(str(x) for x in Path("/dev").glob("video*"))
    options = []
    for path in paths:
        name = labels.get(path, "Video Device")
        options.append({"value": path, "label": f"{path} — {name}"})
    return options


def _touch_options() -> List[Dict[str, str]]:
    proc = Path("/proc/bus/input/devices")
    text = proc.read_text(encoding="utf-8", errors="replace") if proc.exists() else ""
    options: List[Dict[str, str]] = []
    block: list[str] = []
    for line in text.splitlines() + [""]:
        if line.strip():
            block.append(line)
            continue
        name = "Input Device"
        handlers = ""
        for b in block:
            if b.startswith("N: Name="):
                name = b.split("=", 1)[1].strip().strip('"')
            elif b.startswith("H: Handlers="):
                handlers = b.split("=", 1)[1]
        for token in handlers.split():
            if token.startswith("event"):
                path = f"/dev/input/{token}"
                item = {"value": path, "label": f"{path} — {name}"}
                if "touch" in name.lower() or "qdtech" in name.lower() or "mpi" in name.lower():
                    options.insert(0, item)
                else:
                    options.append(item)
        block = []
    return options


def _config_options(config: Dict[str, Any]) -> Dict[str, Any]:
    playback = _run(["aplay", "-l"], timeout=4)
    capture = _run(["arecord", "-l"], timeout=4)
    return {
        "ok": True,
        "config": _clean_config_for_save(config),
        "camera": {
            "configured": config.get("camera", {}).get("device"),
            "options": _camera_options(),
            "raw": _run(["v4l2-ctl", "--list-devices"], timeout=5),
        },
        "audio": {
            "input_configured": config.get("audio", {}).get("input", {}).get("device"),
            "output_configured": config.get("audio", {}).get("output", {}).get("device"),
            "input_options": _parse_alsa_devices(capture.get("stdout", "")),
            "output_options": _parse_alsa_devices(playback.get("stdout", "")),
            "capture_raw": capture,
            "playback_raw": playback,
        },
        "touch": {
            "configured": config.get("touch", {}).get("device"),
            "options": _touch_options(),
        },
        "speech": {
            "tts": tts.tts_status(config, state=None),
            "presets": tts.voice_presets(),
        },
    }


def create_app(config: Dict[str, Any], theme: Dict[str, Any], state: NormState) -> FastAPI:
    base_dir = Path(config.get("_base_dir", ".")).resolve()
    web_dir = base_dir / "web"
    templates = Jinja2Templates(directory=str(web_dir / "templates"))

    app = FastAPI(title="N.O.R.M. Cockpit", version=state.version)
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        return templates.TemplateResponse(request, "dashboard.html", {"request": request, "state": state.snapshot(), "config": config})

    @app.get("/face", response_class=HTMLResponse)
    async def face_page(request: Request):
        return templates.TemplateResponse(request, "face.html", {"request": request, "state": state.snapshot(), "config": config})

    @app.get("/camera", response_class=HTMLResponse)
    async def camera_page(request: Request):
        return templates.TemplateResponse(request, "camera.html", {"request": request, "state": state.snapshot(), "config": config})

    @app.get("/audio", response_class=HTMLResponse)
    async def audio_page(request: Request):
        return templates.TemplateResponse(request, "audio.html", {"request": request, "state": state.snapshot(), "config": config})

    @app.get("/brain", response_class=HTMLResponse)
    async def brain_page(request: Request):
        return templates.TemplateResponse(request, "brain.html", {"request": request, "state": state.snapshot(), "config": config})

    @app.get("/memory", response_class=HTMLResponse)
    async def memory_page(request: Request):
        return templates.TemplateResponse(request, "memory.html", {"request": request, "state": state.snapshot(), "config": config})

    @app.get("/config", response_class=HTMLResponse)
    async def config_page(request: Request):
        return templates.TemplateResponse(request, "config.html", {"request": request, "state": state.snapshot(), "config": config})

    @app.get("/diagnostics", response_class=HTMLResponse)
    async def diagnostics_page(request: Request):
        return templates.TemplateResponse(request, "diagnostics.html", {"request": request, "state": state.snapshot(), "config": config})

    @app.get("/logs", response_class=HTMLResponse)
    async def logs_page(request: Request):
        log_path = base_dir / "logs" / "norm.log"
        lines = []
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
        return templates.TemplateResponse(request, "logs.html", {"request": request, "state": state.snapshot(), "lines": lines})

    @app.get("/api/health")
    async def api_health():
        return {"ok": True, "name": state.system_name, "version": state.version}

    @app.get("/api/status")
    async def api_status():
        return state.snapshot()

    @app.get("/api/config")
    async def api_config():
        return _clean_config_for_save(config)

    @app.get("/api/config/summary")
    async def api_config_summary():
        return {
            "system": config.get("system", {}),
            "display": config.get("display", {}),
            "touch": config.get("touch", {}),
            "face": config.get("face", {}),
            "camera": config.get("camera", {}),
            "audio": config.get("audio", {}),
            "brain": config.get("brain", {}),
            "memory": config.get("memory", {}),
            "identity": config.get("identity", {}),
            "speech": config.get("speech", {}),
        }

    @app.get("/api/config/options")
    async def api_config_options():
        return _config_options(config)

    @app.post("/api/config/device-settings")
    async def api_config_device_settings(request: Request):
        patch = await request.json()
        new_cfg = _clean_config_for_save(config)
        allowed = {k: patch[k] for k in ("camera", "audio", "touch", "api", "face", "brain", "memory", "identity", "speech") if k in patch and isinstance(patch[k], dict)}
        _deep_merge(new_cfg, allowed)
        saved = _write_config(config, new_cfg)
        if "face" in patch:
            status_text = config.get("face", {}).get("default_status_text", "LISTENING...")
            if state.face_mode == "idle":
                state.status_text = status_text
        try:
            camera.camera_status(config, state)
            audio.audio_status(config, state)
        except Exception as exc:
            state.set_error(f"Config saved, status refresh failed: {exc}")
        state.last_action = "CONFIG DEVICE SETTINGS SAVED"
        return {
            "ok": True,
            "saved": saved,
            "message": "Device settings saved. Camera/audio changes apply immediately. API port/touch/display changes may require service restart.",
            "state": state.snapshot(),
            "config": _clean_config_for_save(config),
        }

    @app.post("/api/config/raw")
    async def api_config_raw(request: Request):
        payload = await request.json()
        raw_cfg = payload.get("config", payload)
        if not isinstance(raw_cfg, dict):
            raise HTTPException(status_code=400, detail="Expected JSON object or {config: object}")
        saved = _write_config(config, raw_cfg)
        try:
            camera.camera_status(config, state)
            audio.audio_status(config, state)
        except Exception as exc:
            state.set_error(f"Raw config saved, status refresh failed: {exc}")
        state.last_action = "RAW CONFIG SAVED"
        return {
            "ok": True,
            "saved": saved,
            "message": "Raw config saved. Restart N.O.R.M. for display/system/theme changes.",
            "state": state.snapshot(),
            "config": _clean_config_for_save(config),
        }

    @app.post("/api/config/reload")
    async def api_config_reload():
        state.last_action = "CONFIG CHANGES SAVED - RESTART SERVICE FOR BOOT/THEME/DISPLAY CHANGES"
        return {"ok": True, "message": state.last_action}

    @app.get("/api/display/mode")
    async def get_display_mode():
        return {"mode": state.display_mode, "valid_modes": DISPLAY_MODES}

    @app.post("/api/display/mode")
    async def set_display_mode(req: DisplayModeRequest):
        try:
            state.set_display_mode(req.mode)
            return {"ok": True, "mode": state.display_mode}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/face/state")
    async def get_face_state():
        return {"mode": state.face_mode, "status_text": state.status_text, "valid_modes": FACE_MODES}

    @app.post("/api/face/state")
    async def set_face_state(req: FaceStateRequest):
        try:
            state.set_face_mode(req.mode)
            return {"ok": True, "mode": state.face_mode, "status_text": state.status_text}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/face/text")
    async def set_face_text(req: FaceTextRequest):
        state.status_text = req.text[:80]
        state.last_action = f"STATUS TEXT -> {state.status_text}"
        return {"ok": True, "status_text": state.status_text}

    @app.post("/api/face/blink")
    async def blink(req: BlinkRequest):
        state.request_blink()
        return {"ok": True, "blink_requested": True}

    @app.post("/api/face/glitch")
    async def glitch(req: GlitchRequest):
        state.trigger_glitch(req.duration_seconds)
        return {"ok": True, "duration_seconds": req.duration_seconds}

    @app.get("/api/brain/status")
    async def api_brain_status():
        return await asyncio.to_thread(brain.brain_status, config, state)

    @app.get("/api/memory/status")
    async def api_memory_status():
        return await asyncio.to_thread(memory_store.status_from_config, config)

    @app.get("/api/memory/recent")
    async def api_memory_recent(limit: int = 20):
        if not memory_store.memory_enabled(config):
            return {"ok": True, "enabled": False, "messages": []}
        store = memory_store.MemoryStore.from_config(config)
        sid = memory_store.session_id(config)
        return {"ok": True, "enabled": True, "session_id": sid, "messages": store.recent_messages(sid, limit)}

    @app.get("/api/memory/long-term")
    async def api_memory_long_term(limit: int = 20):
        if not memory_store.memory_enabled(config):
            return {"ok": True, "enabled": False, "memories": []}
        store = memory_store.MemoryStore.from_config(config)
        return {"ok": True, "enabled": True, "memories": store.list_long_term_memories(limit)}

    @app.post("/api/memory/remember")
    async def api_memory_remember(req: MemoryRememberRequest):
        if not memory_store.memory_enabled(config):
            raise HTTPException(status_code=400, detail="Memory is disabled in config")
        store = memory_store.MemoryStore.from_config(config)
        mem_id = store.add_long_term_memory(req.text, req.memory_type, req.importance, source="manual_api")
        state.last_action = "MEMORY SAVED"
        return {"ok": True, "id": mem_id, "status": await asyncio.to_thread(memory_store.status_from_config, config)}

    @app.post("/api/memory/clear-session")
    async def api_memory_clear_session(req: MemoryClearSessionRequest):
        if not memory_store.memory_enabled(config):
            raise HTTPException(status_code=400, detail="Memory is disabled in config")
        store = memory_store.MemoryStore.from_config(config)
        sid = req.session_id or memory_store.session_id(config)
        removed = store.clear_session(sid)
        state.last_action = f"MEMORY SESSION CLEARED: {sid}"
        return {"ok": True, "session_id": sid, "removed_messages": removed, "status": store.status(sid)}

    @app.post("/api/brain/ask")
    async def api_brain_ask(req: BrainAskRequest):
        ok, text, meta = await asyncio.to_thread(brain.ask, config, state, req.prompt, req.context)

        tts_requested = bool(req.speak) if req.speak is not None else bool(config.get("speech", {}).get("tts", {}).get("speak_brain_responses_by_default", False))
        if ok and tts_requested:
            speak_ok, speak_msg, speak_meta = await asyncio.to_thread(tts.speak_text, config, state, text)
            meta = dict(meta)
            meta["speech"] = {"ok": speak_ok, "result": speak_msg, "meta": speak_meta}

        # Keep the speaking expression visible briefly when not actually playing audio.
        hold_seconds = float(config.get("brain", {}).get("speaking_hold_seconds", 4))
        if ok and hold_seconds > 0 and not tts_requested:
            response_at = state.last_brain_at

            def restore_face() -> None:
                time.sleep(hold_seconds)
                if state.last_brain_at == response_at and state.face_mode == "speaking" and state.display_mode == "face":
                    state.set_idle_expression("idle")

            threading.Thread(target=restore_face, daemon=True).start()

        return {"ok": ok, "response": text, "meta": meta, "state": state.snapshot()}

    @app.get("/api/camera/status")
    async def api_camera_status():
        return camera.camera_status(config, state)

    @app.get("/api/camera/devices")
    async def api_camera_devices():
        return camera.list_camera_devices()

    @app.get("/api/camera/formats")
    async def api_camera_formats():
        return camera.camera_formats(config.get("camera", {}).get("device", "/dev/video0"))

    @app.post("/api/camera/snapshot")
    async def api_camera_snapshot():
        ok, msg = camera.capture_snapshot(config, state)
        return {"ok": ok, "result": msg, "state": state.snapshot()}

    @app.get("/api/camera/latest.jpg")
    async def api_camera_latest():
        path = state.last_camera_snapshot or config.get("camera", {}).get("snapshot_path", "/tmp/norm_latest.jpg")
        p = Path(path)
        if not p.exists():
            raise HTTPException(status_code=404, detail="No camera snapshot available yet")
        return FileResponse(str(p), media_type="image/jpeg")

    @app.get("/api/diagnostics")
    async def api_diagnostics():
        return diagnostics.get_system_diagnostics(config, state)

    @app.get("/api/diagnostics/full")
    async def api_diagnostics_full():
        return diagnostics.get_hardware_report(config, state)

    @app.get("/api/audio/status")
    async def api_audio_status():
        return audio.audio_status(config, state)

    @app.get("/api/audio/devices")
    async def api_audio_devices():
        return audio.list_audio_devices()

    @app.get("/api/audio/latest-recording.wav")
    async def api_audio_latest_recording():
        path = state.last_audio_recording or config.get("audio", {}).get("input", {}).get("test_record_path", "/tmp/norm_mic_test.wav")
        p = Path(path)
        if not p.is_absolute():
            p = base_dir / p
        if not p.exists():
            raise HTTPException(status_code=404, detail="No audio recording available yet")
        return FileResponse(str(p), media_type="audio/wav")

    @app.post("/api/audio/record-test")
    async def api_audio_record():
        ok, msg = audio.record_test(config, state)
        return {"ok": ok, "result": msg, "state": state.snapshot()}

    @app.post("/api/audio/play-recording")
    async def api_audio_play_recording():
        ok, msg = audio.play_recording(config, state)
        return {"ok": ok, "result": msg, "state": state.snapshot()}

    @app.post("/api/audio/play-test")
    async def api_audio_play_test():
        ok, msg = audio.play_test(config, state)
        return {"ok": ok, "result": msg, "state": state.snapshot()}

    @app.get("/api/speech/status")
    async def api_speech_status():
        return tts.tts_status(config, state)

    @app.post("/api/speech/speak")
    async def api_speech_speak(req: SpeechSpeakRequest):
        ok, msg, meta = await asyncio.to_thread(tts.speak_text, config, state, req.text)
        return {"ok": ok, "result": msg, "meta": meta, "state": state.snapshot()}

    @app.post("/api/speech/speak-test")
    async def api_speech_speak_test():
        ok, msg, meta = await asyncio.to_thread(tts.speak_test, config, state)
        return {"ok": ok, "result": msg, "meta": meta, "state": state.snapshot()}

    @app.get("/api/speech/latest.wav")
    async def api_speech_latest():
        path = state.last_tts_path or config.get("speech", {}).get("tts", {}).get("output_path", "/tmp/norm_tts.wav")
        p = Path(path)
        if not p.is_absolute():
            p = base_dir / p
        if not p.exists():
            raise HTTPException(status_code=404, detail="No TTS audio available yet")
        return FileResponse(str(p), media_type="audio/wav")

    return app


def run_server(config: Dict[str, Any], theme: Dict[str, Any], state: NormState) -> None:
    import uvicorn

    api_cfg = config.get("api", {})
    app = create_app(config, theme, state)
    uvicorn.run(
        app,
        host=api_cfg.get("host", "0.0.0.0"),
        port=int(api_cfg.get("port", 8088)),
        log_level="info",
    )


def start_server_thread(config: Dict[str, Any], theme: Dict[str, Any], state: NormState) -> threading.Thread:
    thread = threading.Thread(target=run_server, args=(config, theme, state), daemon=True)
    thread.start()
    return thread
