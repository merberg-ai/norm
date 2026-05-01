from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from core.service import BaseService, ServiceHealth
from face.face_pack import FacePack, FacePackError, load_face_pack
from face.renderers import ProceduralRenderer
from face.screen import FaceScreenRenderer


FACE_STATES = [
    "sleeping",
    "idle",
    "wake_detected",
    "listening",
    "thinking",
    "speaking",
    "happy",
    "annoyed",
    "confused",
    "error",
    "emergency",
]


class FaceService(BaseService):
    """Core swappable face-pack service for beta2-pre3.5.

    Pre3 added face-pack discovery, state switching, and SVG preview rendering.
    Pre3.5 adds an optional Pygame screen renderer that follows the same state
    and active face pack, but it is contained: display/Pygame failures do not
    kill the main runtime or web UI.
    """

    name = "face"

    def __init__(self, context):
        super().__init__(context)
        self.face_config: dict[str, Any] = getattr(context.config, "face", {}) or {}
        self.face_packs: dict[str, FacePack] = {}
        self.active_pack_id: str = str(self.face_config.get("active_pack", "norm_default"))
        self.state: str = str(self.face_config.get("default_state", "idle"))
        self.renderers = {
            "procedural": ProceduralRenderer(),
        }
        self.errors: list[str] = []
        self.screen: FaceScreenRenderer | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.screen_skip_reason: str | None = None
        self.runtime_sync_config: dict[str, Any] = self.face_config.get("runtime_sync", {}) or {}
        self.runtime_state_path = self.context.paths.data_dir / "runtime" / "face_state.json"
        self._last_runtime_state_mtime_ns: int = 0
        self._last_runtime_sync_check: float = 0.0

    async def start(self) -> None:
        await super().start()
        self.loop = asyncio.get_running_loop()
        self._subscribe_events()
        self.load_face_packs()
        if self.active_pack_id not in self.face_packs and self.face_packs:
            old = self.active_pack_id
            self.active_pack_id = sorted(self.face_packs.keys())[0]
            self.context.logger.warning(
                "Configured face pack %s not found; using %s",
                old,
                self.active_pack_id,
            )
        if self.state not in FACE_STATES:
            self.state = "idle"

        # Process bridge: when web and direct KMS screen run as separate processes,
        # they need a tiny shared state file. Read it first so a newly started
        # screen process follows the already-running web process, then create it
        # if missing.
        self.sync_from_runtime_state(force=True)
        self._write_runtime_state(source="startup", create_only=True)

        await self.context.events.publish(
            "face.ready",
            {
                "active_pack": self.active_pack_id,
                "state": self.state,
                "packs": sorted(self.face_packs.keys()),
            },
            source="face",
        )

        if self._screen_should_start():
            display_ok, reason = self._screen_display_available()
            if display_ok:
                self.start_screen_renderer()
            else:
                self.screen_skip_reason = reason
                self.context.logger.warning("Face screen renderer requested but skipped: %s", reason)
                await self.context.events.publish("face.screen.skipped", {"reason": reason}, source="face")

    async def stop(self) -> None:
        self.stop_screen_renderer()
        await super().stop()

    def _screen_display_available(self) -> tuple[bool, str]:
        screen_cfg = self.face_config.get("screen", {}) or {}

        # In hotfix3, preflight is advisory and configurable. SDL/Pygame is often
        # better at telling us what is wrong than our guesses, especially across
        # X11, Wayland, framebuffer, and KMS/DRM Pi setups.
        if not bool(screen_cfg.get("preflight_enabled", False)):
            return True, "preflight_disabled"
        if bool(screen_cfg.get("force_without_display", False)):
            return True, "forced"
        if not bool(screen_cfg.get("require_display", False)):
            return True, "not_required"

        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            return True, "display_env"

        # Configured explicit driver/session counts as enough to attempt start.
        driver = str(screen_cfg.get("video_driver") or screen_cfg.get("driver") or "").strip()
        if driver and driver.lower() not in {"auto", "default", "none"}:
            return True, f"configured_driver:{driver}"

        from glob import glob

        device_patterns = [
            "/dev/fb*",
            "/dev/dri/card*",
            "/dev/dri/renderD*",
            "/tmp/.X11-unix/X*",
            f"/run/user/{os.getuid()}/wayland-*",
        ]
        for pattern in device_patterns:
            matches = glob(pattern)
            if matches:
                return True, matches[0]
        return False, "no DISPLAY/WAYLAND_DISPLAY, framebuffer, DRM, X11, or Wayland socket found"

    def _screen_should_start(self) -> bool:
        screen_cfg = self.face_config.get("screen", {}) or {}
        return bool(self.face_config.get("screen_enabled", False)) or bool(screen_cfg.get("enabled", False))

    def start_screen_renderer(self) -> bool:
        if not self.face_packs:
            self.context.logger.warning("Face screen renderer not started: no face packs loaded")
            return False
        if self.screen and self.screen.thread and self.screen.thread.is_alive():
            return True
        self.screen = FaceScreenRenderer(self, loop=self.loop)
        self.screen.start()
        return True

    def stop_screen_renderer(self) -> None:
        if self.screen:
            self.screen.stop()

    def _subscribe_events(self) -> None:
        self.context.events.subscribe("face.state.set", self._on_face_state_set)
        self.context.events.subscribe("brain.thinking", self._event_state("thinking"))
        self.context.events.subscribe("brain.response.ready", self._event_state("speaking"))
        self.context.events.subscribe("tts.started", self._event_state("speaking"))
        self.context.events.subscribe("tts.finished", self._event_state("idle"))
        self.context.events.subscribe("stt.started", self._event_state("listening"))
        self.context.events.subscribe("wakeword.detected", self._event_state("wake_detected"))
        self.context.events.subscribe("system.error", self._event_state("error"))
        self.context.events.subscribe("body.emergency_stop", self._event_state("emergency"))

    def _event_state(self, state: str):
        async def handler(event):
            await self.set_state(state, source=event.type)

        return handler

    async def _on_face_state_set(self, event) -> None:
        state = str(event.payload.get("state", "idle"))
        await self.set_state(state, source=event.source)

    def load_face_packs(self) -> None:
        self.face_packs.clear()
        self.errors.clear()
        roots = [
            self.context.root / "face" / "packs",
            self.context.paths.data_dir / "face_packs",
        ]
        for root in roots:
            if not root.exists():
                continue
            readonly = root == self.context.root / "face" / "packs"
            for pack_dir in sorted(p for p in root.iterdir() if p.is_dir()):
                if not (pack_dir / "face_pack.yaml").exists():
                    continue
                try:
                    pack = load_face_pack(pack_dir, readonly=readonly)
                    self.face_packs[pack.pack_id] = pack
                    self.context.logger.info("Face pack loaded: %s (%s)", pack.pack_id, pack.renderer)
                except Exception as exc:  # noqa: BLE001
                    message = f"{pack_dir.name}: {exc}"
                    self.errors.append(message)
                    self.context.logger.exception("Face pack failed: %s", pack_dir)

    @property
    def active_pack(self) -> FacePack | None:
        return self.face_packs.get(self.active_pack_id)

    async def set_state(self, state: str, *, source: str = "face") -> bool:
        if state not in FACE_STATES:
            await self.context.events.publish(
                "face.error",
                {"error": "unknown state", "state": state},
                source="face",
            )
            return False
        if state == self.state:
            return True
        old = self.state
        self.state = state
        self._write_runtime_state(source=source)
        await self.context.events.publish(
            "face.state.changed",
            {"old": old, "state": state, "source": source},
            source="face",
        )
        return True

    async def set_active_pack(self, pack_id: str, *, source: str = "face") -> bool:
        if pack_id not in self.face_packs:
            await self.context.events.publish(
                "face.error",
                {"error": "unknown face pack", "pack_id": pack_id},
                source="face",
            )
            return False
        if pack_id == self.active_pack_id:
            return True
        old = self.active_pack_id
        self.active_pack_id = pack_id
        self._write_runtime_state(source=source)
        await self.context.events.publish(
            "face.pack.changed",
            {"old": old, "pack_id": pack_id, "source": source},
            source="face",
        )
        return True


    def _runtime_sync_enabled(self) -> bool:
        return bool(self.runtime_sync_config.get("enabled", True))

    def _runtime_state_payload(self, *, source: str = "face") -> dict[str, Any]:
        return {
            "config_version": 2,
            "updated_at": time.time(),
            "source": source,
            "active_pack": self.active_pack_id,
            "state": self.state,
        }

    def _write_runtime_state(self, *, source: str = "face", create_only: bool = False) -> None:
        if not self._runtime_sync_enabled():
            return
        try:
            self.runtime_state_path.parent.mkdir(parents=True, exist_ok=True)
            if create_only and self.runtime_state_path.exists():
                try:
                    self._last_runtime_state_mtime_ns = self.runtime_state_path.stat().st_mtime_ns
                except OSError:
                    pass
                return
            tmp = self.runtime_state_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._runtime_state_payload(source=source), indent=2), encoding="utf-8")
            tmp.replace(self.runtime_state_path)
            self._last_runtime_state_mtime_ns = self.runtime_state_path.stat().st_mtime_ns
        except Exception as exc:  # noqa: BLE001
            try:
                self.context.logger.warning("Face runtime state write failed: %s", exc)
            except Exception:
                pass

    def sync_from_runtime_state(self, *, force: bool = False) -> bool:
        """Import face state written by another N.O.R.M. beta2 process.

        This is intentionally tiny and boring: web writes active_pack/state,
        direct KMS screen polls it. It lets us run the web cockpit and the
        fullscreen Pi display as separate processes without giving SDL a chance
        to eat the event loop.
        """
        if not self._runtime_sync_enabled():
            return False
        poll_seconds = float(self.runtime_sync_config.get("poll_seconds", 0.25) or 0.25)
        now = time.time()
        if not force and now - self._last_runtime_sync_check < poll_seconds:
            return False
        self._last_runtime_sync_check = now
        try:
            stat = self.runtime_state_path.stat()
        except FileNotFoundError:
            return False
        except OSError:
            return False
        if not force and stat.st_mtime_ns <= self._last_runtime_state_mtime_ns:
            return False
        try:
            data = json.loads(self.runtime_state_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            self.context.logger.warning("Face runtime state read failed: %s", exc)
            self._last_runtime_state_mtime_ns = stat.st_mtime_ns
            return False

        changed = False
        requested_pack = str(data.get("active_pack") or "").strip()
        if requested_pack and requested_pack not in self.face_packs:
            # The web process may have created/duplicated a pack after the screen
            # process started. Reload once before declaring it unknown.
            self.load_face_packs()
        if requested_pack and requested_pack in self.face_packs and requested_pack != self.active_pack_id:
            old = self.active_pack_id
            self.active_pack_id = requested_pack
            changed = True
            self.context.logger.info("Face runtime sync: active_pack %s -> %s", old, requested_pack)

        requested_state = str(data.get("state") or "").strip()
        if requested_state in FACE_STATES and requested_state != self.state:
            old = self.state
            self.state = requested_state
            changed = True
            self.context.logger.info("Face runtime sync: state %s -> %s", old, requested_state)

        self._last_runtime_state_mtime_ns = stat.st_mtime_ns
        return changed

    def render_preview_svg(
        self,
        *,
        pack_id: str | None = None,
        state: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> str:
        pack = self.face_packs.get(pack_id or self.active_pack_id)
        if pack is None:
            raise FacePackError("No active face pack available")
        renderer = self.renderers.get(pack.renderer)
        if renderer is None:
            raise FacePackError(f"Renderer is not available: {pack.renderer}")
        w = int(width or self.face_config.get("preview_width", 800))
        h = int(height or self.face_config.get("preview_height", 480))
        return renderer.render_svg(pack, state or self.state, width=w, height=h)

    def screen_diagnostics_payload(self) -> dict[str, Any]:
        screen_cfg = self.face_config.get("screen", {}) or {}
        from glob import glob

        return {
            "config": {
                "enabled": bool(screen_cfg.get("enabled", False)),
                "screen_enabled": bool(self.face_config.get("screen_enabled", False)),
                "driver": screen_cfg.get("driver", "auto"),
                "video_driver": screen_cfg.get("video_driver", ""),
                "fullscreen": bool(screen_cfg.get("fullscreen", True)),
                "width": int(screen_cfg.get("width", self.face_config.get("preview_width", 800))),
                "height": int(screen_cfg.get("height", self.face_config.get("preview_height", 480))),
                "preflight_enabled": bool(screen_cfg.get("preflight_enabled", False)),
                "require_display": bool(screen_cfg.get("require_display", False)),
            },
            "env": {
                "DISPLAY": os.environ.get("DISPLAY", ""),
                "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY", ""),
                "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", ""),
                "XAUTHORITY": os.environ.get("XAUTHORITY", ""),
                "SDL_VIDEODRIVER": os.environ.get("SDL_VIDEODRIVER", ""),
                "SDL_FBDEV": os.environ.get("SDL_FBDEV", ""),
                "PYGAME_DISPLAY": os.environ.get("PYGAME_DISPLAY", ""),
            },
            "devices": {
                "fb": sorted(glob("/dev/fb*")),
                "dri_cards": sorted(glob("/dev/dri/card*")),
                "dri_render": sorted(glob("/dev/dri/renderD*")),
                "x11_sockets": sorted(glob("/tmp/.X11-unix/X*")),
                "wayland_sockets": sorted(glob(f"/run/user/{os.getuid()}/wayland-*")),
            },
            "screen_status": self.screen_status_payload(),
        }

    def screen_status_payload(self) -> dict[str, Any]:
        screen_cfg = self.face_config.get("screen", {}) or {}
        payload = {
            "configured_enabled": self._screen_should_start(),
            "width": int(screen_cfg.get("width", self.face_config.get("preview_width", 800))),
            "height": int(screen_cfg.get("height", self.face_config.get("preview_height", 480))),
            "fps": int(screen_cfg.get("fps", 24)),
            "fullscreen": bool(screen_cfg.get("fullscreen", True)),
            "skip_reason": self.screen_skip_reason,
        }
        if self.screen:
            payload.update(self.screen.status)
        else:
            payload.update({"running": False, "ok": not self._screen_should_start(), "last_error": None})
        return payload

    def status_payload(self) -> dict[str, Any]:
        return {
            "ok": self.started and bool(self.face_packs),
            "state": self.state,
            "states": FACE_STATES,
            "active_pack": self.active_pack_id,
            "packs": [
                {
                    "id": pack.pack_id,
                    "name": pack.name,
                    "description": pack.description,
                    "renderer": pack.renderer,
                    "readonly": pack.readonly,
                    "states": pack.states,
                }
                for pack in sorted(self.face_packs.values(), key=lambda p: p.pack_id)
            ],
            "errors": list(self.errors),
            "screen_enabled": self._screen_should_start(),
            "screen": self.screen_status_payload(),
            "runtime_sync": {
                "enabled": self._runtime_sync_enabled(),
                "path": str(self.runtime_state_path),
                "last_mtime_ns": self._last_runtime_state_mtime_ns,
            },
            "note": "pre3.5 face core with optional Pygame screen renderer",
        }

    async def health(self) -> ServiceHealth:
        details = self.status_payload()
        screen = details.get("screen", {})
        # A failed screen renderer is degraded, not fatal. Web/API face core can
        # still be healthy and usable.
        status = "running"
        if screen.get("configured_enabled") and not screen.get("running"):
            status = "running_screen_inactive"
        return ServiceHealth(
            ok=self.started and bool(self.face_packs),
            status=status if self.started else "stopped",
            details=details,
        )
