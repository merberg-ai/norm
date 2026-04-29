from __future__ import annotations

import logging
import math
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, Tuple

# Audio is not needed for the face renderer.
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from core.state import NormState
from ui.local import LocalUI

log = logging.getLogger("norm.face")
Color = Tuple[int, int, int]


class FaceRenderer:
    def __init__(self, config: Dict[str, Any], theme: Dict[str, Any], state: NormState):
        self.config = config
        self.theme = theme
        self.state = state
        self.display_cfg = config.get("display", {})
        self.face_cfg = config.get("face", {})
        self.width = int(self.display_cfg.get("width", 800))
        self.height = int(self.display_cfg.get("height", 480))
        self.fps = int(self.display_cfg.get("fps", 24))
        self.colors = theme.get("colors", {})
        self.running = False
        self.local_ui = LocalUI(config, theme, state)

        self.last_seen_tap = 0
        self.last_blink = time.time()
        self.next_blink = random.uniform(4, 9)
        self.blink_until = 0.0
        self.boot_until = 0.0

        self.scanline_overlay = None
        self.vignette_overlay = None
        self.noise_surface = None
        self.last_noise_update = 0.0

        self._idle_signature = None
        self._sync_idle_behavior_config(force=True)
        self.next_idle_expression_at = time.time() + random.uniform(self.idle_min_seconds, self.idle_max_seconds)
        self.idle_expression_until = 0.0
        self.last_idle_activity_seen = state.last_interaction_at

    def run(self) -> None:
        pygame.init()
        if self.display_cfg.get("hide_mouse", True):
            pygame.mouse.set_visible(False)

        flags = pygame.FULLSCREEN if self.display_cfg.get("fullscreen", True) else 0
        screen = pygame.display.set_mode((self.width, self.height), flags)
        pygame.display.set_caption("N.O.R.M. v0.02-alpha-r1")
        clock = pygame.time.Clock()

        self.fonts = {
            "small": pygame.font.SysFont("DejaVu Sans Mono", 16),
            "normal": pygame.font.SysFont("DejaVu Sans Mono", 20),
            "large": pygame.font.SysFont("DejaVu Sans Mono", 24),
            "header": pygame.font.SysFont("DejaVu Sans Mono", 22),
        }
        self._build_static_overlays()

        start = time.time()
        self.boot_until = start + 3.2
        self.state.face_mode = self.face_cfg.get("startup_mode", "boot")
        self.running = True
        log.info("Face renderer started")

        while self.running and not self.state.shutdown_requested:
            now = time.time()
            t = now - start

            self._handle_pygame_events(now)
            self._handle_touch()
            self._handle_blink(now)
            self._handle_idle_behavior(now)

            if self.state.face_mode == "boot" and now > self.boot_until:
                self.state.set_face_mode(self.face_cfg.get("idle_mode", "idle"))

            self._draw(screen, now, t)
            pygame.display.flip()
            clock.tick(self.fps)

        pygame.quit()

    def stop(self) -> None:
        self.running = False

    def _handle_pygame_events(self, now: float) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    self.running = False
                elif event.key == pygame.K_SPACE:
                    self.state.cycle_face_mode()
                elif event.key == pygame.K_b:
                    self.blink_until = now + 0.14
                elif event.key == pygame.K_TAB:
                    self.state.set_display_mode("face_control_ui")

    def _handle_touch(self) -> None:
        tap = self.state.touch.tap_count
        if tap != self.last_seen_tap:
            self.last_seen_tap = tap
            self.state.mark_interaction("touch")
            x, y = self.state.touch.x, self.state.touch.y
            self.local_ui.handle_tap(x, y)

    def _handle_blink(self, now: float) -> None:
        with self.state.lock:
            if self.state.blink_requested:
                self.blink_until = now + 0.14
                self.state.blink_requested = False

        face_mode = self.state.face_mode
        anim = self.face_cfg.get("animations", {})
        if face_mode not in ("sleep", "boot") and anim.get("blink_enabled", True):
            if now - self.last_blink > self.next_blink:
                self.blink_until = now + float(anim.get("blink_duration_ms", 140)) / 1000.0
                self.last_blink = now
                self.next_blink = random.uniform(
                    float(anim.get("blink_min_seconds", 4)),
                    float(anim.get("blink_max_seconds", 9)),
                )

    def _sync_idle_behavior_config(self, force: bool = False) -> None:
        """Pull idle personality settings from the live config.

        The web /config page and local CONFIG_UI modify the shared config dict at
        runtime. Keeping this dynamic means idle personality settings take effect
        without a full service restart.
        """
        self.face_cfg = self.config.get("face", {})
        idle_cfg = self.face_cfg.get("idle_behavior", {})
        signature = (
            bool(idle_cfg.get("enabled", True)),
            float(idle_cfg.get("min_seconds", 35)),
            float(idle_cfg.get("max_seconds", 90)),
            float(idle_cfg.get("expression_min_seconds", 5)),
            float(idle_cfg.get("expression_max_seconds", 11)),
            tuple(idle_cfg.get("expressions", ["annoyed", "bored", "worried"])),
        )
        if not force and signature == self._idle_signature:
            return
        self._idle_signature = signature
        self.idle_behavior_enabled = signature[0]
        self.idle_min_seconds = max(5.0, signature[1])
        self.idle_max_seconds = max(self.idle_min_seconds, signature[2])
        self.idle_expression_min_seconds = max(1.0, signature[3])
        self.idle_expression_max_seconds = max(self.idle_expression_min_seconds, signature[4])
        self.idle_expression_modes = list(signature[5]) or ["annoyed", "bored", "worried"]

    def _schedule_next_idle_expression(self, now: float) -> None:
        lo = max(5.0, self.idle_min_seconds)
        hi = max(lo, self.idle_max_seconds)
        self.next_idle_expression_at = now + random.uniform(lo, hi)

    def _handle_idle_behavior(self, now: float) -> None:
        self._sync_idle_behavior_config()
        if not self.idle_behavior_enabled:
            return

        # No personality fidgets while menus are open. The UI should stay boring and readable.
        if self.state.display_mode != "face":
            self._schedule_next_idle_expression(now)
            return

        mode = self.state.face_mode
        expression_modes = {"annoyed", "bored", "worried"}

        # Any real activity resets the idle timer.
        if self.state.last_interaction_at != self.last_idle_activity_seen:
            self.last_idle_activity_seen = self.state.last_interaction_at
            self._schedule_next_idle_expression(max(now, self.last_idle_activity_seen))
            # If a user manually chooses an idle-expression mode, let it show briefly.
            if mode in expression_modes:
                self.idle_expression_until = now + random.uniform(self.idle_expression_min_seconds, self.idle_expression_max_seconds)
            return

        # Let temporary idle expressions play for a few seconds, then go back to normal watch mode.
        if mode in expression_modes:
            if now >= self.idle_expression_until:
                self.state.set_idle_expression("idle")
                self._schedule_next_idle_expression(now)
            return

        # Only fidget when the face is truly idle. Do not interrupt camera/audio/error/sleep states.
        if mode != "idle":
            self._schedule_next_idle_expression(now)
            return

        if now < self.next_idle_expression_at:
            return

        if now - self.state.last_interaction_at < self.idle_min_seconds:
            self._schedule_next_idle_expression(now)
            return

        choices = [m for m in self.idle_expression_modes if m in expression_modes]
        if not choices:
            return
        chosen = random.choice(choices)
        duration = random.uniform(self.idle_expression_min_seconds, self.idle_expression_max_seconds)
        self.idle_expression_until = now + duration
        self.state.set_idle_expression(chosen)

    def _draw(self, screen: pygame.Surface, now: float, t: float) -> None:
        bg = self._color("background", (8, 6, 4))
        screen.fill(bg)

        if self.state.display_mode == "face":
            # Normal face mode: draw the full terminal face stack.
            self._draw_noise(screen, now)
            self._draw_terminal_frame(screen)
            self._draw_face(screen, now, t)
        else:
            # Local UI mode: do NOT draw the face or face terminal frame behind it.
            # This keeps menu/config text readable on the 5-inch display.
            self._draw_noise(screen, now)
            self.local_ui.draw(screen, self.fonts)

        self._draw_touch_feedback(screen, now)
        self._draw_effects(screen, now)

    def _draw_face(self, screen: pygame.Surface, now: float, t: float) -> None:
        mode = self.state.face_mode
        geom = self.face_cfg.get("geometry", {})
        blink_amount = self._blink_amount(now)
        if mode == "sleep":
            blink_amount = 1.0
        elif mode == "bored":
            blink_amount = max(blink_amount, 0.42)
        elif mode == "annoyed":
            blink_amount = max(blink_amount, 0.15)

        drift_x, drift_y = self._pupil_drift(mode, t)
        brightness = 1.2 if mode in ("listening", "speaking", "worried") else 1.0
        if mode == "bored":
            brightness = 0.75
        elif mode == "annoyed":
            brightness = 0.95

        self._draw_brow(screen, self._rect_from_config(geom.get("left_brow"), (165, 125, 195, 12)), mode)
        self._draw_brow(screen, self._rect_from_config(geom.get("right_brow"), (440, 125, 195, 12)), mode)

        self._draw_eye(screen, self._rect_from_config(geom.get("left_eye"), (170, 145, 185, 70)), (drift_x, drift_y), blink_amount, brightness)
        self._draw_eye(screen, self._rect_from_config(geom.get("right_eye"), (445, 145, 185, 70)), (drift_x, drift_y), blink_amount, brightness)
        self._draw_mouth(screen, self._rect_from_config(geom.get("mouth"), (250, 285, 300, 36)), t, mode)

        status = self.state.status_text
        status_color = self._color("warning", (255, 75, 45)) if mode == "error" else self._color("text", (255, 185, 70))
        self._text_center(screen, self.fonts["large"], status, 400, 338, status_color)
        self._text(screen, self.fonts["small"], f"STATUS: {status}", 42, 410, status_color)
        self._text(screen, self.fonts["small"], f"MODE: {mode.upper()}", 300, 410, self._color("text_dim", (175, 115, 45)))
        self._text(screen, self.fonts["small"], f"BRAIN: {self.state.brain_status.upper()}", 585, 410, self._color("text_dim", (175, 115, 45)))

        cursor_on = int(t / 0.55) % 2 == 0
        self._text(screen, self.fonts["normal"], ">>>", 48, 438, self._color("text", (255, 185, 70)))
        if cursor_on:
            pygame.draw.rect(screen, self._color("primary_bright", (255, 210, 90)), (92, 442, 12, 16))

        # Tiny touch diagnostics line, useful during alpha.
        self._text(
            screen,
            self.fonts["small"],
            f"TOUCH: {self.state.touch.device_name[:24]}  TAPS:{self.state.touch.tap_count}",
            240,
            452,
            self._color("text_muted", (120, 80, 35)),
        )

    def _draw_terminal_frame(self, surface: pygame.Surface) -> None:
        amber = self._color("primary", (255, 170, 40))
        dim = self._color("border_dim", (130, 80, 25))
        text = self._color("text", (255, 185, 70))
        text_dim = self._color("text_dim", (175, 115, 45))
        rect = pygame.Rect(24, 20, self.width - 48, self.height - 44)
        pygame.draw.rect(surface, dim, rect, 1)

        tick = 24
        x, y, w, h = rect
        pygame.draw.line(surface, amber, (x, y), (x + tick, y), 2)
        pygame.draw.line(surface, amber, (x, y), (x, y + tick), 2)
        pygame.draw.line(surface, amber, (x + w, y), (x + w - tick, y), 2)
        pygame.draw.line(surface, amber, (x + w, y), (x + w, y + tick), 2)
        pygame.draw.line(surface, amber, (x, y + h), (x + tick, y + h), 2)
        pygame.draw.line(surface, amber, (x, y + h), (x, y + h - tick), 2)
        pygame.draw.line(surface, amber, (x + w, y + h), (x + w - tick, y + h), 2)
        pygame.draw.line(surface, amber, (x + w, y + h), (x + w, y + h - tick), 2)

        pygame.draw.line(surface, dim, (32, 68), (768, 68), 1)
        pygame.draw.line(surface, dim, (32, 392), (768, 392), 1)
        self._text(surface, self.fonts["small"], "N.O.R.M. / ROUTINE MONITORING", 42, 36, text)
        self._text(surface, self.fonts["small"], self.state.version, 635, 36, text_dim)

    def _draw_eye(self, surface: pygame.Surface, rect: pygame.Rect, pupil_offset: tuple[float, float], blink_amount: float, brightness: float) -> None:
        x, y, w, h = rect
        color = self._color("primary_bright", (255, 210, 90)) if brightness > 1.1 else self._color("primary", (255, 170, 40))
        dim = self._color("primary_dim", (170, 110, 35))
        bg = self._color("background", (8, 6, 4))
        fill = self._color("eye_fill", (12, 9, 6))

        self._draw_glow_rect(surface, rect, color, radius=28, passes=3)
        pygame.draw.rect(surface, fill, rect, border_radius=28)
        pygame.draw.rect(surface, color, rect, 2, border_radius=28)
        inner = pygame.Rect(x + 10, y + 10, w - 20, h - 20)
        pygame.draw.rect(surface, dim, inner, 1, border_radius=20)
        pygame.draw.line(surface, dim, (x + 18, y + h // 2), (x + 42, y + h // 2), 1)
        pygame.draw.line(surface, dim, (x + w - 42, y + h // 2), (x + w - 18, y + h // 2), 1)

        if blink_amount > 0:
            cover = int((h / 2) * blink_amount)
            pygame.draw.rect(surface, bg, (x - 2, y - 2, w + 4, cover + 2))
            pygame.draw.rect(surface, bg, (x - 2, y + h - cover, w + 4, cover + 4))
            pygame.draw.line(surface, color, (x + 12, y + h // 2), (x + w - 12, y + h // 2), 2)
            return

        px = x + w // 2 + int(pupil_offset[0])
        py = y + h // 2 + int(pupil_offset[1])
        pygame.draw.circle(surface, self._color("pupil", (255, 220, 95)), (px, py), 15)
        pygame.draw.circle(surface, self._color("primary_bright", (255, 210, 90)), (px, py), 9)
        pygame.draw.circle(surface, self._color("pupil_core", (255, 245, 180)), (px - 3, py - 3), 3)

    def _draw_brow(self, surface: pygame.Surface, rect: pygame.Rect, mode: str) -> None:
        x, y, w, h = rect
        if mode == "thinking":
            y += 8
        elif mode == "listening":
            y -= 4
        elif mode == "error":
            y += 4
        elif mode == "sleep":
            y += 14
        elif mode == "bored":
            y += 14
        elif mode == "annoyed":
            y += 8
        elif mode == "worried":
            y -= 8
        pygame.draw.rect(surface, self._color("primary_dim", (170, 110, 35)), (x, y, w, 2))
        pygame.draw.line(surface, self._color("primary", (255, 170, 40)), (x + 10, y), (x + w - 10, y), 2)

    def _draw_mouth(self, surface: pygame.Surface, rect: pygame.Rect, t: float, mode: str) -> None:
        x, y, w, h = rect
        cy = y + h // 2
        amber = self._color("mouth", (255, 170, 40))
        bright = self._color("mouth_bright", (255, 220, 95))
        dim = self._color("mouth_dim", (150, 95, 30))
        warn = self._color("warning", (255, 75, 45))

        if mode == "speaking":
            segments = 24
            seg_w = w // segments
            for i in range(segments):
                wave = math.sin(t * 9 + i * 0.7)
                jitter = random.uniform(-0.25, 0.25)
                amp = int((wave + 1.3 + jitter) * 7)
                sx = x + i * seg_w
                pygame.draw.line(surface, bright, (sx, cy - amp), (sx, cy + amp), 2)
        elif mode == "thinking":
            for i in range(3):
                pulse = (math.sin(t * 4 + i * 1.2) + 1) / 2
                pygame.draw.circle(surface, bright, (x + 120 + i * 32, cy), int(4 + pulse * 4))
        elif mode == "listening":
            pulse = int((math.sin(t * 6) + 1) * 8)
            pygame.draw.line(surface, bright, (x + 80, cy), (x + w - 80, cy), 2)
            pygame.draw.rect(surface, amber, (x + w // 2 - 35, cy - pulse // 2, 70, max(2, pulse)), 1)
        elif mode == "error":
            points = [(x + i * (w // 11), cy + random.choice([-8, -4, 0, 4, 8])) for i in range(12)]
            pygame.draw.lines(surface, warn, False, points, 2)
        elif mode == "annoyed":
            points = [(x + 45, cy), (x + 105, cy - 5), (x + 150, cy), (x + 205, cy - 4), (x + w - 45, cy)]
            pygame.draw.lines(surface, amber, False, points, 2)
            pygame.draw.line(surface, dim, (x + 90, cy + 9), (x + w - 90, cy + 9), 1)
        elif mode == "bored":
            pygame.draw.line(surface, dim, (x + 105, cy + 2), (x + w - 105, cy + 2), 2)
            pygame.draw.line(surface, dim, (x + 140, cy + 10), (x + w - 140, cy + 10), 1)
        elif mode == "worried":
            pts = []
            for i in range(18):
                px = x + 45 + i * ((w - 90) // 17)
                py = cy + int(math.sin(t * 4.0 + i * 0.8) * 4)
                pts.append((px, py))
            pygame.draw.lines(surface, bright, False, pts, 2)
        elif mode == "sleep":
            pygame.draw.line(surface, dim, (x + 120, cy), (x + w - 120, cy), 1)
        else:
            pulse = int((math.sin(t * 1.7) + 1) * 20)
            color = amber if pulse > 15 else dim
            pygame.draw.line(surface, color, (x + 35, cy), (x + w - 35, cy), 2)
            pygame.draw.line(surface, dim, (x + 90, cy + 8), (x + w - 90, cy + 8), 1)

    def _draw_touch_feedback(self, surface: pygame.Surface, now: float) -> None:
        with self.state.lock:
            x, y = self.state.touch.x, self.state.touch.y
            active = self.state.touch.active
            last_tap = self.state.touch.last_tap_time
        if now - last_tap < 0.35:
            pygame.draw.circle(surface, self._color("primary_bright", (255, 210, 90)), (x, y), 14, 1)
            pygame.draw.circle(surface, self._color("primary_dim", (170, 110, 35)), (x, y), 24, 1)
        if active:
            pygame.draw.circle(surface, self._color("primary_dim", (170, 110, 35)), (x, y), 8, 1)

    def _draw_effects(self, surface: pygame.Surface, now: float) -> None:
        if self.scanline_overlay and self.display_cfg.get("effects", {}).get("scanlines", True):
            surface.blit(self.scanline_overlay, (0, 0))
        if self.vignette_overlay and self.display_cfg.get("effects", {}).get("vignette", True):
            surface.blit(self.vignette_overlay, (0, 0))
        if self.display_cfg.get("effects", {}).get("crt_flicker", True) and random.random() < 0.08:
            flicker = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            flicker.fill((*self._color("primary", (255, 170, 40)), random.randint(3, 9)))
            surface.blit(flicker, (0, 0))

        glitch_until = self.state.temporary_glitch_until
        if glitch_until and now < glitch_until:
            for _ in range(6):
                y = random.randint(80, 360)
                h = random.randint(2, 8)
                xoff = random.randint(-16, 16)
                pygame.draw.line(surface, self._color("primary_bright", (255, 210, 90)), (40 + xoff, y), (760 + xoff, y), 1)

    def _draw_noise(self, surface: pygame.Surface, now: float) -> None:
        if not self.display_cfg.get("effects", {}).get("noise", True):
            return
        refresh = float(self.theme.get("screen", {}).get("noise_refresh_fps", 6))
        if self.noise_surface is None or now - self.last_noise_update > 1.0 / max(1.0, refresh):
            self.noise_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            for _ in range(350):
                x = random.randrange(0, self.width)
                y = random.randrange(0, self.height)
                shade = random.randrange(20, 60)
                self.noise_surface.set_at((x, y), (shade, shade // 2, 0, 60))
            self.last_noise_update = now
        surface.blit(self.noise_surface, (0, 0))

    def _build_static_overlays(self) -> None:
        self.scanline_overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        spacing = int(self.theme.get("screen", {}).get("scanline_spacing", 4))
        opacity = int(self.theme.get("screen", {}).get("scanline_opacity", 36))
        for y in range(0, self.height, spacing):
            pygame.draw.line(self.scanline_overlay, (0, 0, 0, opacity), (0, y), (self.width, y))

        self.vignette_overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        strength = int(self.theme.get("screen", {}).get("vignette_strength", 90))
        # Cheap rectangular vignette approximation.
        for i in range(32):
            alpha = int(strength * (1 - i / 32) / 8)
            pygame.draw.rect(self.vignette_overlay, (0, 0, 0, alpha), (i, i, self.width - i * 2, self.height - i * 2), 1)

    def _blink_amount(self, now: float) -> float:
        if now < self.blink_until:
            phase = 1.0 - ((self.blink_until - now) / 0.14)
            return math.sin(phase * math.pi)
        return 0.0

    def _pupil_drift(self, mode: str, t: float) -> tuple[float, float]:
        if mode == "thinking":
            return 0.0, 0.0
        if mode == "error":
            return float(random.randint(-3, 3)), float(random.randint(-2, 2))
        if mode == "sleep":
            return 0.0, 0.0
        if mode == "annoyed":
            return math.sin(t * 0.55) * 10, -3.0
        if mode == "bored":
            return math.sin(t * 0.2) * 8, 7.0 + math.sin(t * 0.3) * 2
        if mode == "worried":
            return math.sin(t * 2.2) * 18, math.sin(t * 1.7) * 6
        return math.sin(t * 0.35) * 32 + math.sin(t * 0.17) * 10, math.sin(t * 0.42) * 8

    def _draw_glow_rect(self, surface: pygame.Surface, rect: pygame.Rect, color: Color, radius: int = 18, passes: int = 3) -> None:
        x, y, w, h = rect
        for i in range(passes, 0, -1):
            grow = i * 5
            alpha = max(6, 24 // i)
            glow = pygame.Surface((w + grow * 2, h + grow * 2), pygame.SRCALPHA)
            pygame.draw.rect(glow, (*color, alpha), (0, 0, w + grow * 2, h + grow * 2), border_radius=radius + grow)
            surface.blit(glow, (x - grow, y - grow))

    def _text(self, surface: pygame.Surface, font: pygame.font.Font, text: str, x: int, y: int, color: Color) -> None:
        surface.blit(font.render(str(text), True, color), (x, y))

    def _text_center(self, surface: pygame.Surface, font: pygame.font.Font, text: str, center_x: int, y: int, color: Color) -> None:
        img = font.render(str(text), True, color)
        surface.blit(img, (center_x - img.get_width() // 2, y))

    def _color(self, key: str, default: Color) -> Color:
        value = self.colors.get(key, default)
        return tuple(value)  # type: ignore

    @staticmethod
    def _rect_from_config(block: Any, default: tuple[int, int, int, int]) -> pygame.Rect:
        if isinstance(block, dict):
            return pygame.Rect(int(block.get("x", default[0])), int(block.get("y", default[1])), int(block.get("w", default[2])), int(block.get("h", default[3])))
        return pygame.Rect(*default)
