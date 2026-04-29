#!/usr/bin/env python3
import os
import math
import random
import time
import threading
from dataclasses import dataclass

# Helps on Raspberry Pi OS Lite / direct console.
# Audio is not needed for this face smoke test.
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

try:
    from evdev import InputDevice, ecodes
    EVDEV_AVAILABLE = True
except Exception:
    EVDEV_AVAILABLE = False


WIDTH = 800
HEIGHT = 480
FPS = 24

BG = (8, 6, 4)
PANEL_BG = (12, 9, 6)

AMBER = (255, 170, 40)
AMBER_BRIGHT = (255, 220, 95)
AMBER_DIM = (150, 95, 30)

TEXT = (255, 185, 70)
TEXT_DIM = (175, 115, 45)

WARNING = (255, 75, 45)


@dataclass
class TouchState:
    x: int = WIDTH // 2
    y: int = HEIGHT // 2
    active: bool = False
    tap_count: int = 0
    last_tap_time: float = 0.0
    last_event: str = "NONE"
    device_name: str = "UNKNOWN"
    error: str = ""


touch = TouchState()


def scale(value, src_min, src_max, dst_max):
    if src_max == src_min:
        return 0
    value = max(src_min, min(src_max, value))
    return int((value - src_min) / (src_max - src_min) * dst_max)


def touch_thread(device_path="/dev/input/event0"):
    """
    Direct evdev touchscreen reader.

    This does NOT rely on Pygame mouse events.
    It updates the global touch state directly.
    """
    global touch

    if not EVDEV_AVAILABLE:
        touch.error = "python3-evdev not available"
        print(touch.error, flush=True)
        return

    try:
        dev = InputDevice(device_path)
        touch.device_name = dev.name
        touch.last_event = f"OPENED {device_path}"

        print(f"Touch device: {device_path} / {dev.name}", flush=True)

        # Prefer multitouch axes, fallback to classic axes.
        x_code = None
        y_code = None
        x_info = None
        y_info = None

        for candidate in (ecodes.ABS_MT_POSITION_X, ecodes.ABS_X):
            try:
                x_info = dev.absinfo(candidate)
                x_code = candidate
                break
            except Exception:
                pass

        for candidate in (ecodes.ABS_MT_POSITION_Y, ecodes.ABS_Y):
            try:
                y_info = dev.absinfo(candidate)
                y_code = candidate
                break
            except Exception:
                pass

        print(f"Using X code: {ecodes.ABS.get(x_code, x_code)} {x_info}", flush=True)
        print(f"Using Y code: {ecodes.ABS.get(y_code, y_code)} {y_info}", flush=True)

        down = False
        last_trigger = 0.0

        def trigger_tap(reason):
            nonlocal last_trigger
            now = time.time()

            # Debounce so one physical tap does not become 20 taps.
            if now - last_trigger > 0.25:
                touch.tap_count += 1
                touch.last_tap_time = now
                touch.last_event = f"TAP {touch.tap_count}: {reason} @ {touch.x},{touch.y}"
                print(touch.last_event, flush=True)
                last_trigger = now

        for event in dev.read_loop():
            if event.type == ecodes.EV_ABS:
                code_name = ecodes.ABS.get(event.code, str(event.code))
            elif event.type == ecodes.EV_KEY:
                code_name = ecodes.KEY.get(event.code, str(event.code))
            elif event.type == ecodes.EV_SYN:
                code_name = ecodes.SYN.get(event.code, str(event.code))
            else:
                code_name = str(event.code)

            touch.last_event = f"{code_name}={event.value}"

            if event.type == ecodes.EV_ABS:
                if event.code == x_code and x_info:
                    touch.x = scale(event.value, x_info.min, x_info.max, WIDTH - 1)

                elif event.code == y_code and y_info:
                    touch.y = scale(event.value, y_info.min, y_info.max, HEIGHT - 1)

                elif event.code == ecodes.ABS_MT_TRACKING_ID:
                    # Multitouch press/release marker.
                    if event.value >= 0:
                        down = True
                        touch.active = True
                        trigger_tap("TRACKING_ID DOWN")
                    else:
                        down = False
                        touch.active = False
                        touch.last_event = "TRACKING_ID UP"

                elif event.code == ecodes.ABS_PRESSURE:
                    if event.value > 0 and not down:
                        down = True
                        touch.active = True
                        trigger_tap("PRESSURE DOWN")
                    elif event.value == 0:
                        down = False
                        touch.active = False

            elif event.type == ecodes.EV_KEY:
                if event.code in (ecodes.BTN_TOUCH, ecodes.BTN_LEFT, ecodes.BTN_TOOL_FINGER):
                    if event.value == 1:
                        down = True
                        touch.active = True
                        trigger_tap(f"{code_name} DOWN")
                    elif event.value == 0:
                        down = False
                        touch.active = False

    except PermissionError:
        touch.error = "TOUCH PERMISSION DENIED. TRY SUDO OR ADD USER TO input GROUP."
        print(touch.error, flush=True)

    except Exception as e:
        touch.error = f"TOUCH ERROR: {e}"
        print(touch.error, flush=True)


def draw_glow_rect(surface, rect, color, radius=18, passes=3):
    x, y, w, h = rect

    for i in range(passes, 0, -1):
        grow = i * 5
        alpha = max(6, 24 // i)

        glow = pygame.Surface((w + grow * 2, h + grow * 2), pygame.SRCALPHA)
        pygame.draw.rect(
            glow,
            (*color, alpha),
            (0, 0, w + grow * 2, h + grow * 2),
            border_radius=radius + grow,
        )
        surface.blit(glow, (x - grow, y - grow))


def draw_text(surface, font, text, x, y, color=TEXT):
    img = font.render(text, True, color)
    surface.blit(img, (x, y))


def draw_scanlines(surface):
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

    for y in range(0, HEIGHT, 4):
        pygame.draw.line(overlay, (0, 0, 0, 45), (0, y), (WIDTH, y))

    surface.blit(overlay, (0, 0))


def draw_noise(surface):
    # Light cheap noise. Not every pixel. Pi Zero friendly-ish.
    for _ in range(350):
        x = random.randrange(0, WIDTH)
        y = random.randrange(0, HEIGHT)
        shade = random.randrange(20, 60)
        surface.set_at((x, y), (shade, shade // 2, 0))


def draw_terminal_frame(surface, small_font):
    margin = 24
    rect = pygame.Rect(margin, 20, WIDTH - margin * 2, HEIGHT - 44)

    pygame.draw.rect(surface, AMBER_DIM, rect, 1)

    # Corner ticks
    tick = 24
    x, y, w, h = rect

    pygame.draw.line(surface, AMBER, (x, y), (x + tick, y), 2)
    pygame.draw.line(surface, AMBER, (x, y), (x, y + tick), 2)

    pygame.draw.line(surface, AMBER, (x + w, y), (x + w - tick, y), 2)
    pygame.draw.line(surface, AMBER, (x + w, y), (x + w, y + tick), 2)

    pygame.draw.line(surface, AMBER, (x, y + h), (x + tick, y + h), 2)
    pygame.draw.line(surface, AMBER, (x, y + h), (x, y + h - tick), 2)

    pygame.draw.line(surface, AMBER, (x + w, y + h), (x + w - tick, y + h), 2)
    pygame.draw.line(surface, AMBER, (x + w, y + h), (x + w, y + h - tick), 2)

    pygame.draw.line(surface, AMBER_DIM, (32, 68), (768, 68), 1)
    pygame.draw.line(surface, AMBER_DIM, (32, 392), (768, 392), 1)

    draw_text(surface, small_font, "N.O.R.M. / ROUTINE MONITORING", 42, 36, TEXT)
    draw_text(surface, small_font, "v0.01-alpha", 635, 36, TEXT_DIM)


def draw_eye(surface, rect, pupil_offset, blink_amount=0.0, brightness=1.0):
    x, y, w, h = rect

    color = AMBER_BRIGHT if brightness > 1.1 else AMBER
    dim = AMBER_DIM

    draw_glow_rect(surface, rect, color, radius=28, passes=3)

    pygame.draw.rect(surface, PANEL_BG, rect, border_radius=28)
    pygame.draw.rect(surface, color, rect, 2, border_radius=28)

    inner = pygame.Rect(x + 10, y + 10, w - 20, h - 20)
    pygame.draw.rect(surface, dim, inner, 1, border_radius=20)

    # Small terminal detail ticks
    pygame.draw.line(surface, dim, (x + 18, y + h // 2), (x + 42, y + h // 2), 1)
    pygame.draw.line(surface, dim, (x + w - 42, y + h // 2), (x + w - 18, y + h // 2), 1)

    # Blink mask closes from top/bottom.
    if blink_amount > 0:
        cover = int((h / 2) * blink_amount)

        pygame.draw.rect(surface, BG, (x - 2, y - 2, w + 4, cover + 2))
        pygame.draw.rect(surface, BG, (x - 2, y + h - cover, w + 4, cover + 4))

        pygame.draw.line(surface, color, (x + 12, y + h // 2), (x + w - 12, y + h // 2), 2)
        return

    px = x + w // 2 + int(pupil_offset[0])
    py = y + h // 2 + int(pupil_offset[1])

    pygame.draw.circle(surface, AMBER, (px, py), 15)
    pygame.draw.circle(surface, AMBER_BRIGHT, (px, py), 9)
    pygame.draw.circle(surface, (255, 245, 180), (px - 3, py - 3), 3)


def draw_brow(surface, rect, mode="idle"):
    x, y, w, h = rect

    if mode == "thinking":
        y += 8
    elif mode == "listening":
        y -= 4
    elif mode == "error":
        y += 4
    elif mode == "sleep":
        y += 14

    pygame.draw.rect(surface, AMBER_DIM, (x, y, w, 2))
    pygame.draw.line(surface, AMBER, (x + 10, y), (x + w - 10, y), 2)


def draw_mouth(surface, rect, t, mode="idle"):
    x, y, w, h = rect
    cy = y + h // 2

    if mode == "speaking":
        segments = 24
        seg_w = w // segments

        for i in range(segments):
            wave = math.sin(t * 9 + i * 0.7)
            jitter = random.uniform(-0.25, 0.25)
            amp = int((wave + 1.3 + jitter) * 7)

            sx = x + i * seg_w
            pygame.draw.line(surface, AMBER_BRIGHT, (sx, cy - amp), (sx, cy + amp), 2)

    elif mode == "thinking":
        for i in range(3):
            pulse = (math.sin(t * 4 + i * 1.2) + 1) / 2
            radius = int(4 + pulse * 4)
            pygame.draw.circle(surface, AMBER_BRIGHT, (x + 120 + i * 32, cy), radius)

    elif mode == "listening":
        pulse = int((math.sin(t * 6) + 1) * 8)

        pygame.draw.line(surface, AMBER_BRIGHT, (x + 80, cy), (x + w - 80, cy), 2)
        pygame.draw.rect(
            surface,
            AMBER,
            (x + w // 2 - 35, cy - pulse // 2, 70, max(2, pulse)),
            1,
        )

    elif mode == "error":
        points = []

        for i in range(12):
            px = x + i * (w // 11)
            py = cy + random.choice([-8, -4, 0, 4, 8])
            points.append((px, py))

        pygame.draw.lines(surface, WARNING, False, points, 2)

    elif mode == "sleep":
        pygame.draw.line(surface, AMBER_DIM, (x + 120, cy), (x + w - 120, cy), 1)

    else:
        pulse = int((math.sin(t * 1.7) + 1) * 20)
        color = AMBER if pulse > 15 else AMBER_DIM

        pygame.draw.line(surface, color, (x + 35, cy), (x + w - 35, cy), 2)
        pygame.draw.line(surface, AMBER_DIM, (x + 90, cy + 8), (x + w - 90, cy + 8), 1)


def draw_touch_feedback(surface, now):
    if time.time() - touch.last_tap_time < 0.35:
        pygame.draw.circle(surface, AMBER_BRIGHT, (touch.x, touch.y), 14, 1)
        pygame.draw.circle(surface, AMBER_DIM, (touch.x, touch.y), 24, 1)

    if touch.active:
        pygame.draw.circle(surface, AMBER_DIM, (touch.x, touch.y), 8, 1)


def main():
    pygame.init()
    pygame.mouse.set_visible(False)

    device_path = os.environ.get("NORM_TOUCH_DEVICE", "/dev/input/event0")
    threading.Thread(target=touch_thread, args=(device_path,), daemon=True).start()

    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    pygame.display.set_caption("N.O.R.M. Face Smoke Test")

    clock = pygame.time.Clock()

    small_font = pygame.font.SysFont("DejaVu Sans Mono", 16)
    font = pygame.font.SysFont("DejaVu Sans Mono", 20)
    big_font = pygame.font.SysFont("DejaVu Sans Mono", 24)

    start = time.time()

    last_blink = time.time()
    next_blink = random.uniform(4, 9)
    blink_until = 0

    modes = ["idle", "listening", "thinking", "speaking", "error", "sleep"]
    mode_index = 0
    mode = modes[mode_index]

    last_seen_tap = 0

    running = True

    while running:
        now = time.time()
        t = now - start

        # Still process pygame events so quitting works if a keyboard is attached later.
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False

                elif event.key == pygame.K_SPACE:
                    mode_index = (mode_index + 1) % len(modes)
                    mode = modes[mode_index]
                    print(f"Mode changed by keyboard: {mode}", flush=True)

                elif event.key == pygame.K_b:
                    blink_until = now + 0.14
                    print("Manual blink requested.", flush=True)

        # Direct touch handling.
        if touch.tap_count != last_seen_tap:
            last_seen_tap = touch.tap_count
            mode_index = (mode_index + 1) % len(modes)
            mode = modes[mode_index]
            print(f"Mode changed by touch: {mode}", flush=True)

        if now - last_blink > next_blink and mode not in ("sleep",):
            blink_until = now + 0.14
            last_blink = now
            next_blink = random.uniform(4, 9)

        blink_amount = 0.0
        if now < blink_until:
            phase = 1.0 - ((blink_until - now) / 0.14)
            blink_amount = math.sin(phase * math.pi)

        drift_x = math.sin(t * 0.35) * 32 + math.sin(t * 0.17) * 10
        drift_y = math.sin(t * 0.42) * 8

        if mode == "thinking":
            drift_x, drift_y = 0, 0
        elif mode == "error":
            drift_x, drift_y = random.randint(-3, 3), random.randint(-2, 2)
        elif mode == "sleep":
            drift_x, drift_y = 0, 0

        screen.fill(BG)

        draw_noise(screen)
        draw_terminal_frame(screen, small_font)

        draw_brow(screen, (165, 125, 195, 12), mode)
        draw_brow(screen, (440, 125, 195, 12), mode)

        brightness = 1.2 if mode in ("listening", "speaking") else 1.0

        if mode == "sleep":
            blink_amount = 1.0

        draw_eye(screen, (170, 145, 185, 70), (drift_x, drift_y), blink_amount, brightness)
        draw_eye(screen, (445, 145, 185, 70), (drift_x, drift_y), blink_amount, brightness)

        draw_mouth(screen, (250, 285, 300, 36), t, mode)

        status_map = {
            "idle": "INPUT AWAITED",
            "listening": "LISTENING",
            "thinking": "PROCESSING",
            "speaking": "RESPONSE ACTIVE",
            "error": "ERROR DETECTED",
            "sleep": "STANDBY",
        }

        status = status_map.get(mode, "INPUT AWAITED")
        status_color = WARNING if mode == "error" else TEXT

        draw_text(screen, big_font, status, 295, 338, status_color)
        draw_text(screen, small_font, f"STATUS: {status}", 42, 410, status_color)
        draw_text(screen, small_font, f"MODE: {mode.upper()}", 300, 410, TEXT_DIM)
        draw_text(screen, small_font, "BRAIN: OFFLINE", 585, 410, TEXT_DIM)

        cursor_on = int(t / 0.55) % 2 == 0
        draw_text(screen, font, ">>>", 48, 438, TEXT)

        if cursor_on:
            pygame.draw.rect(screen, AMBER_BRIGHT, (92, 442, 12, 16))

        # Tiny debug line so we can see touch status on the face test.
        draw_text(
            screen,
            small_font,
            f"TOUCH: {touch.device_name}  TAPS:{touch.tap_count}",
            42,
            452,
            TEXT_DIM,
        )

        if touch.error:
            draw_text(screen, small_font, touch.error[:70], 42, 452, WARNING)

        draw_touch_feedback(screen, now)
        draw_scanlines(screen)

        # Mild flicker overlay
        if random.random() < 0.08:
            flicker = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            flicker.fill((255, 170, 40, random.randint(4, 10)))
            screen.blit(flicker, (0, 0))

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()


if __name__ == "__main__":
    main()