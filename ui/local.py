from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import pygame

from core.state import NormState
from hardware import camera, audio
from brain import ollama as brain
from speech import tts
from ui.components import TerminalButton, draw_panel, draw_text

log = logging.getLogger("norm.local_ui")


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
        label = " - ".join([b for b in label_bits if b])
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
    options: List[Dict[str, str]] = []
    for path in paths:
        name = labels.get(path, "Video Device")
        options.append({"value": path, "label": f"{path} - {name}"})
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
                item = {"value": path, "label": f"{path} - {name}"}
                if "touch" in name.lower() or "qdtech" in name.lower() or "mpi" in name.lower():
                    options.insert(0, item)
                else:
                    options.append(item)
        block = []
    return options


class LocalUI:
    def __init__(self, config: Dict[str, Any], theme: Dict[str, Any], state: NormState):
        self.config = config
        self.theme = theme
        self.state = state
        self.colors = theme.get("colors", {})
        self._shutdown_pending = None
        self._last_action_tap = 0
        self.config_pages = ["CAMERA", "AUDIO", "TOUCH", "IDLE", "BRAIN", "TTS", "SYSTEM"]
        self.config_page_index = 0
        self.device_cache: Dict[str, List[Dict[str, str]]] = {"camera": [], "audio_input": [], "audio_output": [], "touch": []}
        self.refresh_devices(silent=True)

    def make_nav_buttons(self) -> List[TerminalButton]:
        x, y, w, h = 52, 98, 126, 40
        gap = 10
        labels = [
            ("FACE", "display:face_control_ui"),
            ("CAMERA", "display:camera_ui"),
            ("AUDIO", "display:audio_ui"),
            ("CONFIG", "display:config_ui"),
            ("DIAG", "display:diagnostics_ui"),
            ("POWER", "display:shutdown_ui"),
        ]
        return [TerminalButton(label, pygame.Rect(x, y + i * (h + gap), w, h), action) for i, (label, action) in enumerate(labels)]

    def buttons_for_mode(self, mode: str) -> List[TerminalButton]:
        buttons = self.make_nav_buttons()
        buttons.append(TerminalButton("RETURN", pygame.Rect(642, 32, 110, 34), "display:face"))

        if mode == "face_control_ui":
            labels = [
                ("IDLE", "face:idle"), ("LISTEN", "face:listening"), ("THINK", "face:thinking"),
                ("SPEAK", "face:speaking"), ("ERROR", "face:error"), ("SLEEP", "face:sleep"),
                ("ANNOY", "face:annoyed"), ("BORED", "face:bored"), ("WORRY", "face:worried"),
                ("BLINK", "blink"), ("GLITCH", "glitch"), ("CLEAR", "clear_error"),
            ]
            sx, sy, bw, bh, gap = 220, 140, 122, 36, 8
            for idx, (label, action) in enumerate(labels):
                buttons.append(TerminalButton(label, pygame.Rect(sx + (idx % 4) * (bw + gap), sy + (idx // 4) * (bh + gap), bw, bh), action))
        elif mode == "camera_ui":
            buttons.append(TerminalButton("SNAPSHOT", pygame.Rect(230, 340, 160, 44), "camera:snapshot"))
            buttons.append(TerminalButton("IDLE", pygame.Rect(410, 340, 120, 44), "face:idle"))
        elif mode == "audio_ui":
            buttons.append(TerminalButton("PLAY TEST", pygame.Rect(230, 160, 160, 44), "audio:play_test"))
            buttons.append(TerminalButton("RECORD", pygame.Rect(410, 160, 150, 44), "audio:record"))
            buttons.append(TerminalButton("PLAY REC", pygame.Rect(230, 230, 160, 44), "audio:play_recording"))
            buttons.append(TerminalButton("STATUS", pygame.Rect(410, 230, 150, 44), "audio:status"))
        elif mode == "config_ui":
            buttons.extend(self._config_buttons())
        elif mode == "diagnostics_ui":
            buttons.append(TerminalButton("REFRESH", pygame.Rect(230, 340, 150, 44), "diag:refresh"))
        elif mode == "shutdown_ui":
            buttons.append(TerminalButton("EXIT APP", pygame.Rect(230, 170, 170, 52), "power:exit_app"))
            buttons.append(TerminalButton("RETURN", pygame.Rect(430, 170, 150, 52), "display:face"))
        return buttons

    def _config_buttons(self) -> List[TerminalButton]:
        buttons: List[TerminalButton] = []
        page = self.config_pages[self.config_page_index]
        x0, y1, y2 = 220, 294, 346
        bw, bh, gap = 122, 36, 10

        def b(label: str, col: int, row_y: int, action: str) -> None:
            buttons.append(TerminalButton(label, pygame.Rect(x0 + col * (bw + gap), row_y, bw, bh), action))

        if page == "CAMERA":
            b("CAM ON", 0, y1, "config:camera_toggle")
            b("NEXT DEV", 1, y1, "config:camera_next")
            b("RES", 2, y1, "config:resolution_next")
            b("BACKEND", 3, y1, "config:backend_next")
        elif page == "AUDIO":
            b("NEXT IN", 0, y1, "config:audio_input_next")
            b("OUT ON", 1, y1, "config:audio_output_toggle")
            b("NEXT OUT", 2, y1, "config:audio_output_next")
            b("STATUS", 3, y1, "audio:status")
        elif page == "TOUCH":
            b("TOUCH ON", 0, y1, "config:touch_toggle")
            b("NEXT DEV", 1, y1, "config:touch_next")
            b("INVERT X", 2, y1, "config:touch_invert_x")
            b("INVERT Y", 3, y1, "config:touch_invert_y")
        elif page == "IDLE":
            b("IDLE ON", 0, y1, "config:idle_toggle")
            b("DELAY", 1, y1, "config:idle_delay_next")
            b("HOLD", 2, y1, "config:idle_hold_next")
            b("EXPR", 3, y1, "config:idle_expr_next")
        elif page == "BRAIN":
            b("BRAIN ON", 0, y1, "config:brain_toggle")
            b("HOST", 1, y1, "config:brain_host_next")
            b("MODEL", 2, y1, "config:brain_model_next")
            b("STATUS", 3, y1, "config:brain_status")
        elif page == "TTS":
            b("TTS ON", 0, y1, "config:tts_toggle")
            b("PRESET", 1, y1, "config:tts_preset_next")
            b("VOICE", 2, y1, "config:tts_voice_next")
            b("TEST", 3, y1, "config:tts_test")
            b("SPEED", 0, y2, "config:tts_speed_next")
            b("PITCH", 1, y2, "config:tts_pitch_next")
            b("GAP", 2, y2, "config:tts_gap_next")
            b("SAVE", 3, y2, "config:save")
            return buttons
        elif page == "SYSTEM":
            b("PORT", 0, y1, "config:api_port_next")
            b("DEBUG", 1, y1, "config:debug_toggle")
            b("PROFILE", 2, y1, "config:profile_pi5")
        b("PAGE -", 0, y2, "config:page_prev")
        b("PAGE +", 1, y2, "config:page_next")
        b("REFRESH", 2, y2, "config:refresh")
        b("SAVE", 3, y2, "config:save")
        return buttons

    def handle_tap(self, x: int, y: int) -> bool:
        mode = self.state.display_mode
        if mode == "face":
            # Face taps intentionally do nothing now. Local UI will later open by voice command
            # or explicit API/web action, not accidental screen pokes.
            self.state.last_action = "FACE TOUCH IGNORED"
            return True
        for button in self.buttons_for_mode(mode):
            if button.contains(x, y):
                self.perform_action(button.action)
                return True
        return False

    def perform_action(self, action: str) -> None:
        if action.startswith("display:"):
            self.state.set_display_mode(action.split(":", 1)[1])
        elif action.startswith("face:"):
            self.state.set_face_mode(action.split(":", 1)[1])
        elif action == "blink":
            self.state.request_blink()
        elif action == "glitch":
            self.state.trigger_glitch()
        elif action == "clear_error":
            self.state.clear_error()
        elif action == "camera:snapshot":
            threading.Thread(target=camera.capture_snapshot, args=(self.config, self.state), daemon=True).start()
        elif action == "audio:record":
            threading.Thread(target=audio.record_test, args=(self.config, self.state), daemon=True).start()
        elif action == "audio:play_recording":
            threading.Thread(target=audio.play_recording, args=(self.config, self.state), daemon=True).start()
        elif action == "audio:play_test":
            threading.Thread(target=audio.play_test, args=(self.config, self.state), daemon=True).start()
        elif action == "audio:status":
            audio.audio_status(self.config, self.state)
            self.state.last_action = "AUDIO STATUS REFRESHED"
        elif action.startswith("config:"):
            self._perform_config_action(action.split(":", 1)[1])
        elif action == "diag:refresh":
            self.state.last_action = "DIAGNOSTICS REFRESHED"
        elif action in ("power:reboot", "power:shutdown"):
            self.state.last_action = "OS POWER COMMANDS DISABLED IN ALPHA"
            self.state.status_text = "POWER ACTION LOCKED"
        elif action == "power:exit_app":
            self._confirm_or_execute("exit_app")

    def _perform_config_action(self, action: str) -> None:
        if action == "page_prev":
            self.config_page_index = (self.config_page_index - 1) % len(self.config_pages)
            self.state.last_action = f"CONFIG PAGE -> {self.config_pages[self.config_page_index]}"
        elif action == "page_next":
            self.config_page_index = (self.config_page_index + 1) % len(self.config_pages)
            self.state.last_action = f"CONFIG PAGE -> {self.config_pages[self.config_page_index]}"
        elif action == "refresh":
            self.refresh_devices(silent=False)
        elif action == "save":
            self.save_config()
        elif action == "camera_toggle":
            cfg = self.config.setdefault("camera", {})
            cfg["enabled"] = not bool(cfg.get("enabled", True))
            camera.camera_status(self.config, self.state)
            self.state.last_action = f"CAMERA {'ENABLED' if cfg['enabled'] else 'DISABLED'}"
        elif action == "camera_next":
            self._cycle_option("camera", self.config.setdefault("camera", {}), "device", "CAMERA DEVICE")
            camera.camera_status(self.config, self.state)
        elif action == "resolution_next":
            cfg = self.config.setdefault("camera", {})
            choices = [[320, 240], [640, 480], [800, 600], [1280, 720], [1920, 1080]]
            cur = cfg.get("resolution", [640, 480])
            try:
                idx = choices.index(cur)
            except ValueError:
                idx = 1
            cfg["resolution"] = choices[(idx + 1) % len(choices)]
            self.state.last_action = f"CAMERA RES -> {cfg['resolution'][0]}x{cfg['resolution'][1]}"
        elif action == "backend_next":
            cfg = self.config.setdefault("camera", {})
            choices = ["fswebcam", "ffmpeg"]
            cur = cfg.get("capture_command", "fswebcam")
            try:
                idx = choices.index(cur)
            except ValueError:
                idx = 0
            cfg["capture_command"] = choices[(idx + 1) % len(choices)]
            self.state.last_action = f"CAMERA BACKEND -> {cfg['capture_command']}"
        elif action == "audio_input_next":
            block = self.config.setdefault("audio", {}).setdefault("input", {})
            self._cycle_option("audio_input", block, "device", "AUDIO INPUT")
            audio.audio_status(self.config, self.state)
        elif action == "audio_output_toggle":
            block = self.config.setdefault("audio", {}).setdefault("output", {})
            block["enabled"] = not bool(block.get("enabled", False))
            audio.audio_status(self.config, self.state)
            self.state.last_action = f"AUDIO OUTPUT {'ENABLED' if block['enabled'] else 'DISABLED'}"
        elif action == "audio_output_next":
            block = self.config.setdefault("audio", {}).setdefault("output", {})
            self._cycle_option("audio_output", block, "device", "AUDIO OUTPUT")
            audio.audio_status(self.config, self.state)
        elif action == "touch_toggle":
            block = self.config.setdefault("touch", {})
            block["enabled"] = not bool(block.get("enabled", True))
            self.state.last_action = f"TOUCH {'ENABLED' if block['enabled'] else 'DISABLED'} - RESTART REQUIRED"
        elif action == "touch_next":
            block = self.config.setdefault("touch", {})
            self._cycle_option("touch", block, "device", "TOUCH DEVICE")
            self.state.last_action += " - RESTART REQUIRED"
        elif action == "touch_invert_x":
            block = self.config.setdefault("touch", {})
            block["invert_x"] = not bool(block.get("invert_x", False))
            self.state.last_action = f"TOUCH INVERT X -> {block['invert_x']} - RESTART REQUIRED"
        elif action == "touch_invert_y":
            block = self.config.setdefault("touch", {})
            block["invert_y"] = not bool(block.get("invert_y", False))
            self.state.last_action = f"TOUCH INVERT Y -> {block['invert_y']} - RESTART REQUIRED"
        elif action == "idle_toggle":
            idle = self.config.setdefault("face", {}).setdefault("idle_behavior", {})
            idle["enabled"] = not bool(idle.get("enabled", True))
            self.state.last_action = f"IDLE PERSONALITY {'ENABLED' if idle['enabled'] else 'DISABLED'}"
        elif action == "idle_delay_next":
            idle = self.config.setdefault("face", {}).setdefault("idle_behavior", {})
            choices = [(15, 30), (35, 90), (60, 180), (120, 300), (300, 900)]
            cur = (int(idle.get("min_seconds", 35)), int(idle.get("max_seconds", 90)))
            try:
                idx = choices.index(cur)
            except ValueError:
                idx = 0
            lo, hi = choices[(idx + 1) % len(choices)]
            idle["min_seconds"], idle["max_seconds"] = lo, hi
            self.state.last_action = f"IDLE DELAY -> {lo}-{hi} SEC"
        elif action == "idle_hold_next":
            idle = self.config.setdefault("face", {}).setdefault("idle_behavior", {})
            choices = [(3, 7), (5, 11), (10, 20), (20, 45)]
            cur = (int(idle.get("expression_min_seconds", 5)), int(idle.get("expression_max_seconds", 11)))
            try:
                idx = choices.index(cur)
            except ValueError:
                idx = 1
            lo, hi = choices[(idx + 1) % len(choices)]
            idle["expression_min_seconds"], idle["expression_max_seconds"] = lo, hi
            self.state.last_action = f"IDLE HOLD -> {lo}-{hi} SEC"
        elif action == "idle_expr_next":
            idle = self.config.setdefault("face", {}).setdefault("idle_behavior", {})
            choices = [
                ["annoyed", "bored", "worried"],
                ["annoyed"],
                ["bored"],
                ["worried"],
                ["annoyed", "bored"],
                ["bored", "worried"],
                ["annoyed", "worried"],
            ]
            cur = list(idle.get("expressions", ["annoyed", "bored", "worried"]))
            try:
                idx = choices.index(cur)
            except ValueError:
                idx = 0
            idle["expressions"] = choices[(idx + 1) % len(choices)]
            self.state.last_action = "IDLE EXPR -> " + ",".join(idle["expressions"])
        elif action == "brain_toggle":
            block = self.config.setdefault("brain", {})
            block["enabled"] = not bool(block.get("enabled", False))
            self.state.last_action = f"BRAIN {'ENABLED' if block['enabled'] else 'DISABLED'}"
        elif action == "brain_host_next":
            block = self.config.setdefault("brain", {})
            choices = ["http://192.168.1.24:11434", "http://127.0.0.1:11434", "http://localhost:11434"]
            cur = str(block.get("host", choices[0]))
            try:
                idx = choices.index(cur)
            except ValueError:
                idx = -1
            block["host"] = choices[(idx + 1) % len(choices)]
            self.state.last_action = f"BRAIN HOST -> {block['host']}"
        elif action == "brain_model_next":
            block = self.config.setdefault("brain", {})
            choices = ["norm-alpha", "llama3.1:8b", "mistral:7b"]
            cur = str(block.get("chat_model", "norm-alpha"))
            try:
                idx = choices.index(cur)
            except ValueError:
                idx = -1
            block["chat_model"] = choices[(idx + 1) % len(choices)]
            self.state.last_action = f"BRAIN MODEL -> {block['chat_model']}"
        elif action == "brain_status":
            threading.Thread(target=brain.brain_status, args=(self.config, self.state), daemon=True).start()
            self.state.last_action = "BRAIN STATUS CHECK REQUESTED"
        elif action == "tts_toggle":
            block = self.config.setdefault("speech", {}).setdefault("tts", {})
            block["enabled"] = not bool(block.get("enabled", True))
            self.state.last_action = f"TTS {'ENABLED' if block['enabled'] else 'DISABLED'}"
        elif action == "tts_preset_next":
            block = self.config.setdefault("speech", {}).setdefault("tts", {})
            presets = tts.voice_presets()
            ids = [p["id"] for p in presets]
            cur = str(block.get("voice_preset", "creepy_terminal"))
            try:
                idx = ids.index(cur)
            except ValueError:
                idx = -1
            preset = presets[(idx + 1) % len(presets)]
            block["voice_preset"] = preset["id"]
            for key in ("voice", "speed", "pitch", "amplitude", "word_gap"):
                block[key] = preset[key]
            self.state.last_action = f"TTS PRESET -> {preset['name'].upper()}"
        elif action == "tts_voice_next":
            block = self.config.setdefault("speech", {}).setdefault("tts", {})
            choices = ["en-us", "en-us+m1", "en-us+m2", "en-us+m3", "en-us+m4", "en-us+m5", "en-us+m6", "en-us+m7", "en-us+f1", "en-us+f2", "en-us+f3"]
            cur = str(block.get("voice", "en-us+m3"))
            try:
                idx = choices.index(cur)
            except ValueError:
                idx = -1
            block["voice"] = choices[(idx + 1) % len(choices)]
            block["voice_preset"] = "custom"
            self.state.last_action = f"TTS VOICE -> {block['voice']}"
        elif action == "tts_speed_next":
            block = self.config.setdefault("speech", {}).setdefault("tts", {})
            choices = [110, 120, 130, 145, 160, 180]
            cur = int(block.get("speed", 130))
            try:
                idx = choices.index(cur)
            except ValueError:
                idx = 1
            block["speed"] = choices[(idx + 1) % len(choices)]
            block["voice_preset"] = "custom"
            self.state.last_action = f"TTS SPEED -> {block['speed']}"
        elif action == "tts_pitch_next":
            block = self.config.setdefault("speech", {}).setdefault("tts", {})
            choices = [18, 24, 28, 35, 42, 55]
            cur = int(block.get("pitch", 28))
            try:
                idx = choices.index(cur)
            except ValueError:
                idx = 2
            block["pitch"] = choices[(idx + 1) % len(choices)]
            block["voice_preset"] = "custom"
            self.state.last_action = f"TTS PITCH -> {block['pitch']}"
        elif action == "tts_gap_next":
            block = self.config.setdefault("speech", {}).setdefault("tts", {})
            choices = [0, 2, 3, 5, 7, 10]
            cur = int(block.get("word_gap", 5))
            try:
                idx = choices.index(cur)
            except ValueError:
                idx = 3
            block["word_gap"] = choices[(idx + 1) % len(choices)]
            block["voice_preset"] = "custom"
            self.state.last_action = f"TTS WORD GAP -> {block['word_gap']}"
        elif action == "tts_test":
            threading.Thread(target=tts.speak_test, args=(self.config, self.state), daemon=True).start()
            self.state.last_action = "TTS TEST REQUESTED"
        elif action == "api_port_next":
            api = self.config.setdefault("api", {})
            choices = [8088, 8089, 8090, 8091]
            cur = int(api.get("port", 8088))
            try:
                idx = choices.index(cur)
            except ValueError:
                idx = 0
            api["port"] = choices[(idx + 1) % len(choices)]
            self.state.last_action = f"API PORT -> {api['port']} - RESTART REQUIRED"
        elif action == "debug_toggle":
            sys = self.config.setdefault("system", {})
            sys["debug"] = not bool(sys.get("debug", True))
            self.state.last_action = f"DEBUG -> {sys['debug']}"
        elif action == "profile_pi5":
            self.config.setdefault("system", {})["profile"] = "pi5-alpha"
            self.state.last_action = "PROFILE -> pi5-alpha"
        else:
            self.state.last_action = f"UNKNOWN CONFIG ACTION: {action}"

    def _cycle_option(self, cache_key: str, block: Dict[str, Any], field: str, label: str) -> None:
        opts = self.device_cache.get(cache_key, [])
        if not opts:
            self.refresh_devices(silent=True)
            opts = self.device_cache.get(cache_key, [])
        if not opts:
            self.state.last_action = f"NO {label} OPTIONS DETECTED"
            return
        cur = block.get(field)
        values = [o["value"] for o in opts]
        try:
            idx = values.index(cur)
        except ValueError:
            idx = -1
        opt = opts[(idx + 1) % len(opts)]
        block[field] = opt["value"]
        block["device_label"] = opt.get("label", opt["value"])
        self.state.last_action = f"{label} -> {opt['value']}"

    def refresh_devices(self, silent: bool = False) -> None:
        self.device_cache = {
            "camera": _camera_options(),
            "audio_input": _parse_alsa_devices(_run(["arecord", "-l"], timeout=4).get("stdout", "")),
            "audio_output": _parse_alsa_devices(_run(["aplay", "-l"], timeout=4).get("stdout", "")),
            "touch": _touch_options(),
        }
        if not silent:
            self.state.last_action = (
                f"DEVICES REFRESHED C:{len(self.device_cache['camera'])} "
                f"IN:{len(self.device_cache['audio_input'])} "
                f"OUT:{len(self.device_cache['audio_output'])} "
                f"T:{len(self.device_cache['touch'])}"
            )

    def save_config(self) -> None:
        try:
            config_path = Path(self.config.get("_config_path", "configs/norm-alpha.json")).expanduser().resolve()
            config_path.parent.mkdir(parents=True, exist_ok=True)
            cleaned = _clean_config_for_save(self.config)
            backup = None
            if config_path.exists():
                stamp = time.strftime("%Y%m%d-%H%M%S")
                backup = config_path.with_suffix(config_path.suffix + f".bak-{stamp}")
                shutil.copy2(config_path, backup)
            tmp = config_path.with_suffix(config_path.suffix + ".tmp")
            tmp.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
            tmp.replace(config_path)
            base_dir = self.config.get("_base_dir") or str(config_path.parent.parent)
            self.config.clear()
            self.config.update(cleaned)
            self.config["_config_path"] = str(config_path)
            self.config["_base_dir"] = base_dir
            camera.camera_status(self.config, self.state)
            audio.audio_status(self.config, self.state)
            brain.brain_status(self.config, self.state)
            tts.tts_status(self.config, self.state)
            self.state.last_action = f"CONFIG SAVED {time.strftime('%H:%M:%S')}"
            log.info("Local config saved to %s backup=%s", config_path, backup)
        except Exception as exc:
            log.exception("Local config save failed")
            self.state.set_error(f"Config save failed: {exc}")

    def _confirm_or_execute(self, name: str) -> None:
        now = time.time()
        timeout = float(self.config.get("local_ui", {}).get("shutdown_confirmation_timeout_seconds", 5))
        if self._shutdown_pending == name and now - self._last_action_tap < timeout:
            self._execute_power_action(name)
        else:
            self._shutdown_pending = name
            self._last_action_tap = now
            self.state.last_action = f"TAP {name.upper()} AGAIN TO CONFIRM"

    def _execute_power_action(self, name: str) -> None:
        if name == "exit_app":
            self.state.request_shutdown("local UI exit app")
            return
        self.state.last_action = f"{name.upper()} DISABLED IN ALPHA"
        self.state.status_text = "POWER ACTION LOCKED"

    def draw(self, surface: pygame.Surface, fonts: Dict[str, pygame.font.Font]) -> None:
        c = self.colors
        small, normal = fonts["small"], fonts["normal"]
        mode = self.state.display_mode

        # Opaque UI background. Do not let the face/text show behind menus.
        surface.fill(c.get("background", (8, 6, 4)))
        pygame.draw.rect(surface, c.get("border_dim", (130, 80, 25)), pygame.Rect(24, 20, 752, 436), 1)
        pygame.draw.line(surface, c.get("border_dim", (130, 80, 25)), (32, 76), (768, 76), 1)
        pygame.draw.line(surface, c.get("border_dim", (130, 80, 25)), (32, 410), (768, 410), 1)

        draw_text(surface, normal, "N.O.R.M. LOCAL CONTROL", 42, 42, c.get("text", (255, 185, 70)))
        draw_text(surface, small, mode.upper(), 310, 46, c.get("text_dim", (175, 115, 45)))

        nav_rect = pygame.Rect(40, 84, 150, 315)
        main_rect = pygame.Rect(205, 84, 555, 315)
        draw_panel(surface, nav_rect, c, "NAV", small)
        draw_panel(surface, main_rect, c, self._title_for_mode(mode), small)

        active_action = f"display:{mode}"
        for button in self.buttons_for_mode(mode):
            button.draw(surface, small, c, active=(button.action == active_action))

        if mode == "face_control_ui":
            self._draw_face_control(surface, fonts)
        elif mode == "camera_ui":
            self._draw_camera(surface, fonts)
        elif mode == "audio_ui":
            self._draw_audio(surface, fonts)
        elif mode == "config_ui":
            self._draw_config(surface, fonts)
        elif mode == "diagnostics_ui":
            self._draw_diag(surface, fonts)
        elif mode == "shutdown_ui":
            self._draw_power(surface, fonts)

        draw_text(surface, small, f"STATUS: {self.state.last_action[:52]}", 42, 424, c.get("text", (255, 185, 70)))
        draw_text(surface, small, f"FACE: {self.state.face_mode.upper()}", 600, 424, c.get("text_dim", (175, 115, 45)))

    def _title_for_mode(self, mode: str) -> str:
        return {
            "face_control_ui": "FACE CONTROL",
            "camera_ui": "CAMERA DIAGNOSTICS",
            "audio_ui": "AUDIO DIAGNOSTICS",
            "config_ui": "CONFIGURATION",
            "diagnostics_ui": "SYSTEM DIAGNOSTICS",
            "shutdown_ui": "POWER CONTROL",
        }.get(mode, "LOCAL CONTROL")

    def _draw_face_control(self, surface, fonts):
        c = self.colors
        draw_text(surface, fonts["normal"], f"CURRENT MODE: {self.state.face_mode.upper()}", 230, 110, c.get("text", (255, 185, 70)))
        draw_text(surface, fonts["small"], f"THEME: {self.state.theme}", 230, 285, c.get("text_dim", (175, 115, 45)))
        draw_text(surface, fonts["small"], "Tap buttons to force expression states.", 230, 310, c.get("text_dim", (175, 115, 45)))

    def _draw_camera(self, surface, fonts):
        c = self.colors
        cfg = self.config.get("camera", {})
        draw_text(surface, fonts["normal"], f"DEVICE: {cfg.get('device', '/dev/video0')}", 230, 112, c.get("text", (255, 185, 70)))
        draw_text(surface, fonts["normal"], f"STATUS: {self.state.camera_status.upper()}", 230, 140, c.get("text", (255, 185, 70)))
        path = self.state.last_camera_snapshot or cfg.get("snapshot_path", "/tmp/norm_latest.jpg")
        draw_text(surface, fonts["small"], f"SNAPSHOT: {path}", 230, 170, c.get("text_dim", (175, 115, 45)))
        preview_rect = pygame.Rect(230, 200, 360, 130)
        pygame.draw.rect(surface, c.get("border_dim", (130, 80, 25)), preview_rect, 1)
        try:
            if path and Path(path).exists():
                img = pygame.image.load(path)
                iw, ih = img.get_size()
                if iw > 0 and ih > 0:
                    scale = min((preview_rect.w - 8) / iw, (preview_rect.h - 8) / ih)
                    nw = max(1, int(iw * scale))
                    nh = max(1, int(ih * scale))
                    img = pygame.transform.smoothscale(img, (nw, nh))
                    surface.blit(img, (preview_rect.centerx - nw // 2, preview_rect.centery - nh // 2))
            else:
                draw_text(surface, fonts["small"], "NO SNAPSHOT YET", 252, 252, c.get("text_dim", (175, 115, 45)))
        except Exception as exc:
            draw_text(surface, fonts["small"], f"PREVIEW ERROR: {str(exc)[:34]}", 242, 252, c.get("warning", (255, 75, 45)))

    def _draw_audio(self, surface, fonts):
        c = self.colors
        icfg = self.config.get("audio", {}).get("input", {})
        ocfg = self.config.get("audio", {}).get("output", {})
        draw_text(surface, fonts["normal"], f"INPUT:  {icfg.get('device', 'default')}", 230, 112, c.get("text", (255, 185, 70)))
        draw_text(surface, fonts["normal"], f"OUTPUT: {ocfg.get('device', 'default')}", 230, 135, c.get("text", (255, 185, 70)))
        draw_text(surface, fonts["small"], f"IN STATUS:  {self.state.audio_input_status}", 230, 292, c.get("text_dim", (175, 115, 45)))
        draw_text(surface, fonts["small"], f"OUT STATUS: {self.state.audio_output_status}", 230, 315, c.get("text_dim", (175, 115, 45)))
        draw_text(surface, fonts["small"], f"LAST REC: {self.state.last_audio_recording or 'none'}", 230, 340, c.get("text_dim", (175, 115, 45)))

    def _short_label(self, value: Any, limit: int = 46) -> str:
        text = str(value) if value is not None else "none"
        return text if len(text) <= limit else text[: limit - 3] + "..."

    def _draw_kv(self, surface, font, label: str, value: Any, x: int, y: int, color=None) -> None:
        c = self.colors
        color = color or c.get("text", (255, 185, 70))
        draw_text(surface, font, f"{label:<11} {self._short_label(value)}", x, y, color)

    def _draw_config(self, surface, fonts):
        c = self.colors
        small = fonts["small"]
        normal = fonts["normal"]
        page = self.config_pages[self.config_page_index]
        x, y = 230, 112
        draw_text(surface, normal, f"PAGE {self.config_page_index + 1}/{len(self.config_pages)}: {page}", x, y, c.get("text_bright", (255, 220, 120)))
        draw_text(surface, small, "Changes modify runtime config. Tap SAVE to persist.", x, y + 26, c.get("text_dim", (175, 115, 45)))
        if page == "CAMERA":
            cfg = self.config.get("camera", {})
            self._draw_kv(surface, small, "ENABLED", cfg.get("enabled", True), x, y + 58)
            self._draw_kv(surface, small, "DEVICE", cfg.get("device"), x, y + 82)
            self._draw_kv(surface, small, "RES", "x".join(map(str, cfg.get("resolution", [640, 480]))), x, y + 106)
            self._draw_kv(surface, small, "BACKEND", cfg.get("capture_command", "fswebcam"), x, y + 130)
            draw_text(surface, small, f"DETECTED: {len(self.device_cache.get('camera', []))} camera/video devices", x, y + 160, c.get("text_dim", (175, 115, 45)))
        elif page == "AUDIO":
            icfg = self.config.get("audio", {}).get("input", {})
            ocfg = self.config.get("audio", {}).get("output", {})
            self._draw_kv(surface, small, "IN DEVICE", icfg.get("device"), x, y + 58)
            self._draw_kv(surface, small, "IN STATUS", self.state.audio_input_status, x, y + 82)
            self._draw_kv(surface, small, "OUT EN", ocfg.get("enabled", False), x, y + 106)
            self._draw_kv(surface, small, "OUT DEVICE", ocfg.get("device"), x, y + 130)
            draw_text(surface, small, f"DETECTED: {len(self.device_cache.get('audio_input', []))} inputs / {len(self.device_cache.get('audio_output', []))} outputs", x, y + 160, c.get("text_dim", (175, 115, 45)))
        elif page == "TOUCH":
            cfg = self.config.get("touch", {})
            self._draw_kv(surface, small, "ENABLED", cfg.get("enabled", True), x, y + 58)
            self._draw_kv(surface, small, "DEVICE", cfg.get("device"), x, y + 82)
            self._draw_kv(surface, small, "MATCH", cfg.get("match_name", ""), x, y + 106)
            self._draw_kv(surface, small, "INVERT X", cfg.get("invert_x", False), x, y + 130)
            self._draw_kv(surface, small, "INVERT Y", cfg.get("invert_y", False), x, y + 154)
            draw_text(surface, small, f"DETECTED: {len(self.device_cache.get('touch', []))} input event devices", x, y + 180, c.get("text_dim", (175, 115, 45)))
        elif page == "IDLE":
            face = self.config.get("face", {})
            idle = face.get("idle_behavior", {})
            expr = ",".join(idle.get("expressions", ["annoyed", "bored", "worried"]))
            self._draw_kv(surface, small, "STATUS", face.get("default_status_text", "LISTENING..."), x, y + 58)
            self._draw_kv(surface, small, "ENABLED", idle.get("enabled", True), x, y + 82)
            self._draw_kv(surface, small, "DELAY", f"{idle.get('min_seconds', 35)}-{idle.get('max_seconds', 90)} sec", x, y + 106)
            self._draw_kv(surface, small, "HOLD", f"{idle.get('expression_min_seconds', 5)}-{idle.get('expression_max_seconds', 11)} sec", x, y + 130)
            self._draw_kv(surface, small, "EXPRESS", expr, x, y + 154)
            draw_text(surface, small, "DELAY/HOLD/EXPR cycle presets. SAVE persists.", x, y + 184, c.get("text_dim", (175, 115, 45)))
        elif page == "BRAIN":
            cfg = self.config.get("brain", {})
            self._draw_kv(surface, small, "ENABLED", cfg.get("enabled", False), x, y + 58)
            self._draw_kv(surface, small, "HOST", cfg.get("host"), x, y + 82)
            self._draw_kv(surface, small, "MODEL", cfg.get("chat_model"), x, y + 106)
            self._draw_kv(surface, small, "STATUS", self.state.brain_status, x, y + 130)
            self._draw_kv(surface, small, "LATENCY", self.state.last_brain_latency_ms, x, y + 154)
            draw_text(surface, small, "Use web /brain for typed prompts. Local page is config/status.", x, y + 184, c.get("text_dim", (175, 115, 45)))
        elif page == "TTS":
            cfg = self.config.get("speech", {}).get("tts", {})
            self._draw_kv(surface, small, "ENABLED", cfg.get("enabled", True), x, y + 58)
            self._draw_kv(surface, small, "PRESET", cfg.get("voice_preset", "creepy_terminal"), x, y + 82)
            self._draw_kv(surface, small, "VOICE", cfg.get("voice", "en-us+m3"), x, y + 106)
            self._draw_kv(surface, small, "SPEED", cfg.get("speed", 130), x, y + 130)
            self._draw_kv(surface, small, "PITCH", cfg.get("pitch", 28), x, y + 154)
            self._draw_kv(surface, small, "WORD GAP", cfg.get("word_gap", 5), x, y + 178)
            draw_text(surface, small, "PRESET applies full recipe. VOICE/SPEED/PITCH/GAP make custom.", x, y + 206, c.get("text_dim", (175, 115, 45)))
        elif page == "SYSTEM":
            sys = self.config.get("system", {})
            api = self.config.get("api", {})
            self._draw_kv(surface, small, "PROFILE", sys.get("profile"), x, y + 58)
            self._draw_kv(surface, small, "VERSION", sys.get("version"), x, y + 82)
            self._draw_kv(surface, small, "DEBUG", sys.get("debug"), x, y + 106)
            self._draw_kv(surface, small, "API HOST", api.get("host", "0.0.0.0"), x, y + 130)
            self._draw_kv(surface, small, "API PORT", api.get("port", 8088), x, y + 154)
            self._draw_kv(surface, small, "CONFIG", self.config.get("_config_path", "configs/norm-alpha.json"), x, y + 180)

    def _draw_diag(self, surface, fonts):
        c = self.colors
        snap = self.state.snapshot()
        lines = [
            f"HOSTNAME: {snap.get('hostname')}",
            f"LAN IP:   {snap.get('lan_ip')}",
            f"UPTIME:   {snap.get('uptime_seconds')} sec",
            f"TOUCH:    {self.state.touch.device_name}",
            f"TAPS:     {self.state.touch.tap_count}",
            f"CAMERA:   {self.state.camera_status}",
            f"AUDIO IN: {self.state.audio_input_status}",
            f"AUDIO OUT:{self.state.audio_output_status}",
            f"BRAIN:   {self.state.brain_status}",
        ]
        for i, line in enumerate(lines):
            draw_text(surface, fonts["small"], line, 230, 112 + i * 24, c.get("text", (255, 185, 70)))

    def _draw_power(self, surface, fonts):
        c = self.colors
        draw_text(surface, fonts["normal"], "ALPHA POWER PANEL", 230, 112, c.get("text", (255, 185, 70)))
        draw_text(surface, fonts["small"], "REBOOT and SHUTDOWN are disabled in the app for now.", 230, 285, c.get("text_dim", (175, 115, 45)))
        draw_text(surface, fonts["small"], "This prevents sudo/systemctl password prompts from hanging the UI.", 230, 310, c.get("text_dim", (175, 115, 45)))
        draw_text(surface, fonts["small"], "Use EXIT APP to close N.O.R.M. during testing.", 230, 335, c.get("text", (255, 185, 70)))
        draw_text(surface, fonts["small"], "Reboot the Pi from SSH until permissions are deliberately configured.", 230, 360, c.get("text_dim", (175, 115, 45)))
