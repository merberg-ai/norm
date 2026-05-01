from __future__ import annotations

import asyncio
import math
import glob
import os
import random
import threading
import time
from typing import Any

from face.face_pack import FacePack


Color = tuple[int, int, int]


def _hex_to_rgb(value: Any, default: Color) -> Color:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return (int(value[0]), int(value[1]), int(value[2]))
        except Exception:
            return default
    text = str(value or "").strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return default
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return default


def _get(data: dict[str, Any], path: str, default: Any) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _num(pack: FacePack, key: str, default: float) -> float:
    try:
        return float(_get(pack.config, key, default))
    except (TypeError, ValueError):
        return float(default)


class FaceScreenRenderer:
    """Optional Pygame fullscreen/windowed renderer for beta2-pre3.5.

    The renderer follows FaceService state and active face pack. It intentionally
    runs in a background thread and is allowed to fail without taking down the
    core runtime or web UI. Pygame is imported only when the screen renderer is
    actually started, so headless/web-only boots stay lightweight.
    """

    def __init__(self, face_service, loop: asyncio.AbstractEventLoop | None = None):
        self.face = face_service
        self.context = face_service.context
        self.loop = loop
        self.config = face_service.face_config.get("screen", {}) or {}
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.started_at: float | None = None
        self.last_error: str | None = None
        self._pygame = None
        self._blink_until = 0.0
        self._last_blink = time.time()
        self._next_blink = random.uniform(4.0, 9.0)
        self._noise_surface = None
        self._last_noise_update = 0.0
        self._scanline_overlay = None
        self._vignette_overlay = None
        self._last_state_seen = ""
        self.status: dict[str, Any] = {
            "enabled": True,
            "running": False,
            "ok": False,
            "last_error": None,
        }

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run_wrapper, name="norm-face-screen", daemon=True)
        self.thread.start()

    def stop(self, timeout: float = 0.25) -> None:
        self.stop_event.set()
        # The screen thread is daemonized and intentionally non-critical. Do not
        # let SDL/Pygame shutdown quirks block N.O.R.M. shutdown.
        if self.thread and self.thread.is_alive():
            try:
                self.thread.join(timeout=timeout)
            except RuntimeError:
                pass

    def _publish_from_thread(self, event_type: str, payload: dict[str, Any]) -> None:
        # Thread-to-async event publishing caused occasional shutdown stalls on
        # early screen failures. The renderer is non-critical; log/status is
        # enough for pre3.5 hotfix3. We can re-enable this later with a queued
        # event bridge owned by the main loop.
        return

    def _apply_environment_base(self) -> None:
        """Apply screen/display environment from config before SDL video init."""
        os.environ.setdefault("SDL_AUDIODRIVER", str(self.config.get("audio_driver", "dummy") or "dummy"))
        os.environ.setdefault("SDL_RENDER_DRIVER", str(self.config.get("render_driver", "software") or "software"))

        display = str(self.config.get("display") or "").strip()
        if display:
            os.environ["DISPLAY"] = display
        wayland_display = str(self.config.get("wayland_display") or "").strip()
        if wayland_display:
            os.environ["WAYLAND_DISPLAY"] = wayland_display
        xauth = str(self.config.get("xauthority") or "").strip()
        if xauth:
            os.environ["XAUTHORITY"] = xauth

        xdg_runtime_dir = str(self.config.get("xdg_runtime_dir") or "").strip()
        if xdg_runtime_dir:
            os.environ["XDG_RUNTIME_DIR"] = xdg_runtime_dir
        elif os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("XDG_RUNTIME_DIR"):
            runtime = f"/run/user/{os.getuid()}"
            if os.path.isdir(runtime):
                os.environ["XDG_RUNTIME_DIR"] = runtime

        framebuffer = str(self.config.get("framebuffer") or self.config.get("fbdev") or "").strip()
        if framebuffer:
            os.environ["SDL_FBDEV"] = framebuffer
        mouse_dev = str(self.config.get("mouse_device") or "").strip()
        if mouse_dev:
            os.environ["SDL_MOUSEDEV"] = mouse_dev
        mouse_driver = str(self.config.get("mouse_driver") or "").strip()
        if mouse_driver:
            os.environ["SDL_MOUSEDRV"] = mouse_driver

        kms_require_master = self.config.get("kmsdrm_require_drm_master")
        if kms_require_master is not None:
            os.environ["SDL_KMSDRM_REQUIRE_DRM_MASTER"] = "1" if bool(kms_require_master) else "0"

        pygame_display = str(self.config.get("pygame_display") or "").strip()
        if pygame_display:
            os.environ["PYGAME_DISPLAY"] = pygame_display
        window_pos = str(self.config.get("window_position") or "").strip()
        if window_pos:
            os.environ["SDL_VIDEO_WINDOW_POS"] = window_pos

    def _driver_candidates(self) -> list[str | None]:
        explicit = str(self.config.get("video_driver") or self.config.get("driver") or "").strip().lower()
        if explicit and explicit not in {"auto", "default", "none"}:
            return [explicit]

        raw = self.config.get("auto_driver_candidates")
        if isinstance(raw, str):
            candidates = [part.strip() for part in raw.split(",") if part.strip()]
        elif isinstance(raw, list):
            candidates = [str(part).strip() for part in raw if str(part).strip()]
        else:
            candidates = []

        if not candidates:
            # On Pi Lite/headless installs the old working N.O.R.M. renderer used
            # SDL_VIDEODRIVER=kmsdrm directly. Prefer direct console/DRM paths
            # when there is no desktop session.
            if os.environ.get("DISPLAY"):
                candidates = ["default", "x11", "kmsdrm", "fbcon"]
            elif os.environ.get("WAYLAND_DISPLAY"):
                candidates = ["default", "wayland", "kmsdrm", "fbcon"]
            else:
                candidates = ["kmsdrm", "fbcon"]

        normalized: list[str | None] = []
        for candidate in candidates:
            c = str(candidate).strip().lower()
            if c in {"", "auto", "default", "none"}:
                normalized.append(None)
            elif c == "framebuffer":
                normalized.append("fbcon")
            elif c in {"kms", "drm"}:
                normalized.append("kmsdrm")
            else:
                normalized.append(c)

        seen: set[str | None] = set()
        out: list[str | None] = []
        for item in normalized:
            if item not in seen:
                out.append(item)
                seen.add(item)
        return out or [None]

    def _open_display_with_fallbacks(self, pygame, width: int, height: int, flags: int):
        attempts: list[dict[str, str]] = []
        original_driver = os.environ.get("SDL_VIDEODRIVER")
        last_exc: Exception | None = None

        for driver in self._driver_candidates():
            if driver is None:
                if original_driver:
                    os.environ["SDL_VIDEODRIVER"] = original_driver
                else:
                    os.environ.pop("SDL_VIDEODRIVER", None)
                label = "default"
            else:
                os.environ["SDL_VIDEODRIVER"] = driver
                label = driver

            try:
                try:
                    pygame.display.quit()
                except Exception:
                    pass
                pygame.display.init()
                screen = pygame.display.set_mode((width, height), flags)
                chosen = pygame.display.get_driver()
                attempts.append({"driver": label, "result": "ok", "chosen": str(chosen)})
                return screen, str(chosen), attempts
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                attempts.append({"driver": label, "result": "failed", "error": str(exc)})
                try:
                    pygame.display.quit()
                except Exception:
                    pass

        raise RuntimeError(f"No SDL/Pygame display driver worked. Attempts: {attempts}") from last_exc

    def _run_wrapper(self) -> None:
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            self.status.update({"running": False, "ok": False, "last_error": self.last_error})
            self.context.logger.exception("Face screen renderer failed: %s", exc)
            self._publish_from_thread("face.screen.failed", {"error": self.last_error})
        finally:
            self.status["running"] = False
            self._publish_from_thread("face.screen.stopped", {})

    def run_foreground(self) -> None:
        """Run the Pygame renderer on the main thread.

        This is important on Raspberry Pi Lite/headless installs using the
        kmsdrm/fbcon backends. The old working alpha renderer ran Pygame on the
        main thread; background-thread SDL init can succeed strangely or render
        nowhere on some Pi display stacks.
        """
        self.stop_event.clear()
        try:
            self._run()
        except KeyboardInterrupt:
            self.stop_event.set()
            raise
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            self.status.update({"running": False, "ok": False, "last_error": self.last_error})
            self.context.logger.exception("Face screen renderer failed: %s", exc)
            raise
        finally:
            self.status["running"] = False

    def _run(self) -> None:
        self._apply_environment_base()

        try:
            import pygame  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("pygame is not installed. Run ./scripts/install_screen_deps.sh") from exc

        self._pygame = pygame

        width = int(self.config.get("width", self.face.face_config.get("preview_width", 800)))
        height = int(self.config.get("height", self.face.face_config.get("preview_height", 480)))
        fps = max(1, int(self.config.get("fps", 24)))
        fullscreen = bool(self.config.get("fullscreen", True))
        flags = pygame.FULLSCREEN if fullscreen else 0

        screen, chosen_driver, attempts = self._open_display_with_fallbacks(pygame, width, height, flags)
        pygame.font.init()
        if bool(self.config.get("hide_mouse", True)):
            try:
                pygame.mouse.set_visible(False)
            except Exception:
                pass
        pygame.display.set_caption("N.O.R.M. beta2")
        clock = pygame.time.Clock()
        fonts = {
            "small": pygame.font.SysFont("DejaVu Sans Mono", 15),
            "normal": pygame.font.SysFont("DejaVu Sans Mono", 20),
            "large": pygame.font.SysFont("DejaVu Sans Mono", 24),
        }
        self._build_static_overlays(width, height)

        self.started_at = time.time()
        self.status.update(
            {
                "running": True,
                "ok": True,
                "last_error": None,
                "width": width,
                "height": height,
                "fps": fps,
                "fullscreen": fullscreen,
                "video_driver": chosen_driver,
                "requested_video_driver": os.environ.get("SDL_VIDEODRIVER", ""),
                "display": os.environ.get("DISPLAY", ""),
                "wayland_display": os.environ.get("WAYLAND_DISPLAY", ""),
                "xdg_runtime_dir": os.environ.get("XDG_RUNTIME_DIR", ""),
                "attempts": attempts,
            }
        )
        self.context.logger.info("Face screen renderer started: %sx%s fullscreen=%s", width, height, fullscreen)
        self._publish_from_thread(
            "face.screen.started",
            {"width": width, "height": height, "fps": fps, "fullscreen": fullscreen},
        )

        while not self.stop_event.is_set():
            now = time.time()
            if hasattr(self.face, "sync_from_runtime_state"):
                try:
                    self.face.sync_from_runtime_state()
                except Exception as exc:  # noqa: BLE001
                    try:
                        self.context.logger.debug("Face runtime sync poll failed: %s", exc)
                    except Exception:
                        pass
            t = now - (self.started_at or now)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.stop_event.set()
                elif event.type == pygame.KEYDOWN:
                    self._handle_key(event.key, now)

            pack = self.face.active_pack
            if pack is None:
                self._draw_missing_pack(screen, fonts, width, height)
            else:
                self._draw_face_screen(screen, fonts, pack, self.face.state, width, height, now, t)
            pygame.display.flip()
            clock.tick(fps)

        pygame.quit()
        self.context.logger.info("Face screen renderer stopped")

    def _handle_key(self, key: int, now: float) -> None:
        pygame = self._pygame
        if pygame is None:
            return
        if key in (pygame.K_ESCAPE, pygame.K_q):
            self.stop_event.set()
        elif key == pygame.K_b:
            self._blink_until = now + 0.14
        elif key == pygame.K_SPACE:
            states = [
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
            try:
                idx = states.index(self.face.state)
            except ValueError:
                idx = 0
            next_state = states[(idx + 1) % len(states)]
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(self.face.set_state(next_state, source="keyboard"), self.loop)
            else:
                old = self.face.state
                self.face.state = next_state
                try:
                    self.context.logger.info("Face state changed from keyboard: %s -> %s", old, next_state)
                except Exception:
                    pass

    def _draw_missing_pack(self, screen, fonts, width: int, height: int) -> None:
        pygame = self._pygame
        screen.fill((8, 4, 4))
        self._text_center(screen, fonts["large"], "N.O.R.M. FACE PACK MISSING", width // 2, height // 2 - 18, (255, 80, 55))
        pygame.draw.rect(screen, (255, 80, 55), (32, 28, width - 64, height - 56), 2)

    def _draw_face_screen(self, screen, fonts, pack: FacePack, state: str, width: int, height: int, now: float, t: float) -> None:
        pygame = self._pygame
        cfg = pack.state_config(state)
        colors = pack.config.get("colors", {}) if isinstance(pack.config.get("colors"), dict) else {}

        bg = self._color(colors, cfg, "background", (9, 6, 4))
        frame = self._color(colors, cfg, "frame", (255, 174, 40))
        primary = self._color(colors, cfg, "primary", (255, 174, 40))
        bright = self._color(colors, cfg, "bright", (255, 229, 168))
        dim = self._color(colors, cfg, "dim", (155, 100, 34))
        warning = self._color(colors, cfg, "warning", (255, 80, 56))
        label = str(cfg.get("label") or state.upper())
        mood = str(cfg.get("mood") or state)
        mouth = str(cfg.get("mouth") or "idle")
        brow = str(cfg.get("brow") or "flat")
        glitch = bool(cfg.get("glitch", False))

        screen.fill(bg)
        self._draw_noise(screen, now, width, height)
        self._draw_terminal_frame(screen, fonts, width, height, frame, dim, primary, pack, label)

        eye_w = int(_num(pack, "geometry.eye_w", 170))
        eye_h = int(_num(pack, "geometry.eye_h", 92))
        eye_y = int(_num(pack, "geometry.eye_y", 150))
        gap = int(_num(pack, "geometry.eye_gap", 95))
        mouth_w = int(_num(pack, "geometry.mouth_w", 330))
        mouth_y = int(_num(pack, "geometry.mouth_y", 325))
        cx = width // 2
        left = pygame.Rect(cx - gap // 2 - eye_w, eye_y, eye_w, eye_h)
        right = pygame.Rect(cx + gap // 2, eye_y, eye_w, eye_h)

        blink_amount = self._blink_amount(now, cfg, mood)
        drift_x, drift_y = self._pupil_drift(mood, t)
        drift_x += float(cfg.get("pupil_dx", 0.0) or 0.0)
        drift_y += float(cfg.get("pupil_dy", 0.0) or 0.0)

        self._draw_brow(screen, left, brow, mood, primary, dim, side="left")
        self._draw_brow(screen, right, brow, mood, primary, dim, side="right")
        self._draw_eye(screen, left, (drift_x, drift_y), blink_amount, primary, bright, dim, bg, mood)
        self._draw_eye(screen, right, (drift_x, drift_y), blink_amount, primary, bright, dim, bg, mood)

        mouth_rect = pygame.Rect(cx - mouth_w // 2, mouth_y - 18, mouth_w, 54)
        self._draw_mouth(screen, mouth_rect, t, mouth, mood, primary, bright, dim, warning)

        status_color = warning if state in {"error", "emergency"} else primary
        self._text_center(screen, fonts["large"], label, cx, max(366, height - 126), status_color)
        self._text(screen, fonts["small"], f"STATUS: {state.upper()}", 44, height - 68, status_color)
        self._text(screen, fonts["small"], f"PACK: {pack.pack_id}", 300, height - 68, dim)
        self._text(screen, fonts["small"], "BETA2 SCREEN CORE", max(44, width - 320), height - 68, dim)

        cursor_on = int(t / 0.55) % 2 == 0
        self._text(screen, fonts["normal"], ">>>", 48, height - 38, primary)
        if cursor_on:
            pygame.draw.rect(screen, bright, (92, height - 34, 12, 16))

        if glitch:
            self._draw_glitch(screen, width, height, bright, warning)
        self._draw_effects(screen, now, width, height, primary)

    def _draw_terminal_frame(self, surface, fonts, width: int, height: int, frame: Color, dim: Color, text: Color, pack: FacePack, label: str) -> None:
        pygame = self._pygame
        rect = pygame.Rect(24, 20, width - 48, height - 44)
        pygame.draw.rect(surface, dim, rect, 1)
        tick = 24
        x, y, w, h = rect
        corners = [
            ((x, y), (x + tick, y)), ((x, y), (x, y + tick)),
            ((x + w, y), (x + w - tick, y)), ((x + w, y), (x + w, y + tick)),
            ((x, y + h), (x + tick, y + h)), ((x, y + h), (x, y + h - tick)),
            ((x + w, y + h), (x + w - tick, y + h)), ((x + w, y + h), (x + w, y + h - tick)),
        ]
        for a, b in corners:
            pygame.draw.line(surface, frame, a, b, 2)
        pygame.draw.line(surface, dim, (32, 68), (width - 32, 68), 1)
        pygame.draw.line(surface, dim, (32, height - 88), (width - 32, height - 88), 1)
        self._text(surface, fonts["small"], "N.O.R.M. / ROUTINE MONITORING", 42, 36, text)
        self._text(surface, fonts["small"], "FACE: " + pack.pack_id, max(42, width - 280), 36, dim)
        self._text_center(surface, fonts["small"], label, width // 2, 42, dim)

    def _draw_eye(self, surface, rect, pupil_offset: tuple[float, float], blink_amount: float, primary: Color, bright: Color, dim: Color, bg: Color, mood: str) -> None:
        pygame = self._pygame
        x, y, w, h = rect
        fill = tuple(max(0, int(c * 0.35)) for c in bg)
        self._draw_glow_rect(surface, rect, primary, radius=26, passes=3)
        pygame.draw.rect(surface, fill, rect, border_radius=26)
        pygame.draw.rect(surface, primary, rect, 3, border_radius=26)
        inner = pygame.Rect(x + 10, y + 10, w - 20, h - 20)
        pygame.draw.rect(surface, dim, inner, 1, border_radius=20)
        pygame.draw.line(surface, dim, (x + 18, y + h // 2), (x + 42, y + h // 2), 1)
        pygame.draw.line(surface, dim, (x + w - 42, y + h // 2), (x + w - 18, y + h // 2), 1)

        if blink_amount > 0.02 or mood == "sleeping":
            cover = int((h / 2) * max(blink_amount, 1.0 if mood == "sleeping" else 0.0))
            pygame.draw.rect(surface, bg, (x - 3, y - 3, w + 6, cover + 4))
            pygame.draw.rect(surface, bg, (x - 3, y + h - cover, w + 6, cover + 6))
            pygame.draw.line(surface, primary, (x + 14, y + h // 2), (x + w - 14, y + h // 2), 3)
            return

        px = x + w // 2 + int(pupil_offset[0])
        py = y + h // 2 + int(pupil_offset[1])
        if mood == "annoyed":
            px -= 5
        pygame.draw.circle(surface, primary, (px, py), max(13, min(w, h) // 5))
        pygame.draw.circle(surface, bright, (px - 4, py - 5), max(5, min(w, h) // 12))
        pygame.draw.circle(surface, tuple(max(0, c // 3) for c in bg), (px + 5, py + 5), 4)

    def _draw_brow(self, surface, eye_rect, brow: str, mood: str, primary: Color, dim: Color, side: str) -> None:
        pygame = self._pygame
        x, y, w, _h = eye_rect
        by = y - 25
        flip = 1 if side == "left" else -1
        if brow == "angry" or mood == "annoyed":
            y1, y2 = by + (12 * flip), by - (5 * flip)
        elif brow == "worried" or mood == "confused":
            y1, y2 = by - (8 * flip), by + (10 * flip)
        elif brow == "bored":
            y1, y2 = by + 12, by + 12
        else:
            y1, y2 = by, by
        pygame.draw.line(surface, dim, (x + 18, y1 + 3), (x + w - 18, y2 + 3), 5)
        pygame.draw.line(surface, primary, (x + 18, y1), (x + w - 18, y2), 3)

    def _draw_mouth(self, surface, rect, t: float, mouth: str, mood: str, primary: Color, bright: Color, dim: Color, warning: Color) -> None:
        pygame = self._pygame
        x, y, w, h = rect
        cy = y + h // 2
        if mouth == "speaking" or mood == "speaking":
            segments = 26
            seg_w = max(2, w // segments)
            for i in range(segments):
                wave = math.sin(t * 10.0 + i * 0.72)
                amp = int((wave + 1.25 + random.uniform(-0.22, 0.22)) * 8)
                sx = x + i * seg_w
                pygame.draw.line(surface, bright, (sx, cy - amp), (sx, cy + amp), 2)
        elif mouth == "thinking" or mood == "thinking":
            for i in range(3):
                pulse = (math.sin(t * 4.0 + i * 1.2) + 1) / 2
                pygame.draw.circle(surface, bright, (x + w // 2 - 34 + i * 34, cy), int(5 + pulse * 5))
        elif mouth == "error" or mood in {"error", "emergency"}:
            points = []
            for i in range(13):
                px = x + i * (w // 12)
                py = cy + random.choice([-12, -7, 0, 7, 12])
                points.append((px, py))
            pygame.draw.lines(surface, warning, False, points, 3)
        elif mouth == "frown":
            pygame.draw.arc(surface, primary, (x + 42, cy - 24, w - 84, 56), math.radians(205), math.radians(335), 3)
        elif mouth == "flat":
            pygame.draw.line(surface, dim, (x + 70, cy), (x + w - 70, cy), 3)
        else:
            pulse = int((math.sin(t * 1.7) + 1) * 18)
            color = primary if pulse > 13 else dim
            pygame.draw.line(surface, color, (x + 35, cy), (x + w - 35, cy), 3)
            pygame.draw.line(surface, dim, (x + 95, cy + 13), (x + w - 95, cy + 13), 1)

    def _draw_glow_rect(self, surface, rect, color: Color, radius: int = 18, passes: int = 3) -> None:
        pygame = self._pygame
        x, y, w, h = rect
        for i in range(passes, 0, -1):
            grow = i * 5
            alpha = max(6, 28 // i)
            glow = pygame.Surface((w + grow * 2, h + grow * 2), pygame.SRCALPHA)
            pygame.draw.rect(glow, (*color, alpha), (0, 0, w + grow * 2, h + grow * 2), border_radius=radius + grow)
            surface.blit(glow, (x - grow, y - grow))

    def _draw_noise(self, surface, now: float, width: int, height: int) -> None:
        pygame = self._pygame
        effects = self.config.get("effects", {}) if isinstance(self.config.get("effects"), dict) else {}
        if not bool(effects.get("noise", True)):
            return
        refresh = float(effects.get("noise_refresh_fps", 6))
        if self._noise_surface is None or now - self._last_noise_update > 1.0 / max(1.0, refresh):
            self._noise_surface = pygame.Surface((width, height), pygame.SRCALPHA)
            count = int(effects.get("noise_pixels", 300))
            for _ in range(max(0, count)):
                x = random.randrange(0, width)
                y = random.randrange(0, height)
                shade = random.randrange(20, 60)
                self._noise_surface.set_at((x, y), (shade, shade // 2, 0, 52))
            self._last_noise_update = now
        surface.blit(self._noise_surface, (0, 0))

    def _build_static_overlays(self, width: int, height: int) -> None:
        pygame = self._pygame
        self._scanline_overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        effects = self.config.get("effects", {}) if isinstance(self.config.get("effects"), dict) else {}
        spacing = int(effects.get("scanline_spacing", 4))
        opacity = int(effects.get("scanline_opacity", 36))
        for y in range(0, height, max(1, spacing)):
            pygame.draw.line(self._scanline_overlay, (0, 0, 0, opacity), (0, y), (width, y))

        self._vignette_overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        strength = int(effects.get("vignette_strength", 90))
        for i in range(32):
            alpha = int(strength * (1 - i / 32) / 8)
            pygame.draw.rect(self._vignette_overlay, (0, 0, 0, alpha), (i, i, width - i * 2, height - i * 2), 1)

    def _draw_effects(self, surface, now: float, width: int, height: int, primary: Color) -> None:
        pygame = self._pygame
        effects = self.config.get("effects", {}) if isinstance(self.config.get("effects"), dict) else {}
        if self._scanline_overlay and bool(effects.get("scanlines", True)):
            surface.blit(self._scanline_overlay, (0, 0))
        if self._vignette_overlay and bool(effects.get("vignette", True)):
            surface.blit(self._vignette_overlay, (0, 0))
        if bool(effects.get("crt_flicker", True)) and random.random() < float(effects.get("flicker_chance", 0.07)):
            flicker = pygame.Surface((width, height), pygame.SRCALPHA)
            flicker.fill((*primary, random.randint(3, 9)))
            surface.blit(flicker, (0, 0))

    def _draw_glitch(self, surface, width: int, height: int, bright: Color, warning: Color) -> None:
        pygame = self._pygame
        for _ in range(7):
            y = random.randint(80, max(81, height - 110))
            xoff = random.randint(-22, 22)
            color = bright if random.random() > 0.25 else warning
            pygame.draw.line(surface, color, (42 + xoff, y), (width - 42 + xoff, y), random.choice([1, 1, 2]))

    def _blink_amount(self, now: float, cfg: dict[str, Any], mood: str) -> float:
        forced = float(cfg.get("blink", 0.0) or 0.0)
        if forced >= 0.85 or mood == "sleeping":
            return 1.0
        if now < self._blink_until:
            phase = 1.0 - ((self._blink_until - now) / 0.14)
            return math.sin(phase * math.pi)
        if now - self._last_blink > self._next_blink:
            self._blink_until = now + 0.14
            self._last_blink = now
            self._next_blink = random.uniform(4.0, 9.0)
        return 0.0

    def _pupil_drift(self, mood: str, t: float) -> tuple[float, float]:
        if mood in {"thinking", "sleeping"}:
            return 0.0, 0.0
        if mood in {"error", "emergency"}:
            return float(random.randint(-3, 3)), float(random.randint(-2, 2))
        if mood == "annoyed":
            return math.sin(t * 0.55) * 9, -3.0
        if mood == "confused":
            return math.sin(t * 2.2) * 16, math.sin(t * 1.7) * 6
        if mood == "listening":
            return math.sin(t * 0.8) * 10, 0.0
        if mood == "happy":
            return math.sin(t * 0.35) * 14, -4.0
        return math.sin(t * 0.35) * 28 + math.sin(t * 0.17) * 8, math.sin(t * 0.42) * 7

    def _color(self, colors: dict[str, Any], cfg: dict[str, Any], key: str, default: Color) -> Color:
        return _hex_to_rgb(cfg.get(key, colors.get(key)), default)

    def _text(self, surface, font, text: str, x: int, y: int, color: Color) -> None:
        surface.blit(font.render(str(text), True, color), (x, y))

    def _text_center(self, surface, font, text: str, center_x: int, y: int, color: Color) -> None:
        img = font.render(str(text), True, color)
        surface.blit(img, (center_x - img.get_width() // 2, y))
