from __future__ import annotations

import html
import math
from typing import Any

from face.face_pack import FacePack
from face.renderer_base import FaceRenderer


def _get(data: dict[str, Any], path: str, default: Any) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _color(pack: FacePack, key: str, default: str) -> str:
    value = _get(pack.config, f"colors.{key}", default)
    return str(value)


def _num(pack: FacePack, key: str, default: float) -> float:
    try:
        return float(_get(pack.config, key, default))
    except (TypeError, ValueError):
        return float(default)


class ProceduralRenderer(FaceRenderer):
    """Small SVG renderer for the first swappable face packs.

    This is not the final fullscreen renderer. It is the shared preview renderer
    used by the web UI, API, and later Face Designer plugin.
    """

    renderer_id = "procedural"

    def render_svg(self, pack: FacePack, state: str, *, width: int, height: int) -> str:
        state = state if state in pack.states else "idle"
        cfg = pack.state_config(state)

        bg = _color(pack, "background", "#090604")
        frame = _color(pack, "frame", "#ffae28")
        primary = str(cfg.get("primary") or _color(pack, "primary", "#ffae28"))
        bright = str(cfg.get("bright") or _color(pack, "bright", "#ffe5a8"))
        dim = str(cfg.get("dim") or _color(pack, "dim", "#9b6422"))
        warning = str(cfg.get("warning") or _color(pack, "warning", "#ff5038"))
        label = str(cfg.get("label") or state.upper())
        mood = str(cfg.get("mood") or state)

        eye_w = int(_num(pack, "geometry.eye_w", 170))
        eye_h = int(_num(pack, "geometry.eye_h", 92))
        eye_y = int(_num(pack, "geometry.eye_y", 150))
        gap = int(_num(pack, "geometry.eye_gap", 95))
        mouth_w = int(_num(pack, "geometry.mouth_w", 330))
        mouth_y = int(_num(pack, "geometry.mouth_y", 325))
        cx = width // 2
        left_x = cx - gap // 2 - eye_w
        right_x = cx + gap // 2

        blink = float(cfg.get("blink", 0.0) or 0.0)
        pupil_dx = float(cfg.get("pupil_dx", 0.0) or 0.0)
        pupil_dy = float(cfg.get("pupil_dy", 0.0) or 0.0)
        brow = str(cfg.get("brow") or "flat")
        mouth = str(cfg.get("mouth") or "idle")
        glitch = bool(cfg.get("glitch", False))

        parts: list[str] = []
        parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(pack.name)} {html.escape(state)}">')
        parts.append("<defs>")
        parts.append(f'<radialGradient id="crtGlow" cx="50%" cy="45%" r="65%"><stop offset="0%" stop-color="{bright}" stop-opacity="0.18"/><stop offset="48%" stop-color="{primary}" stop-opacity="0.07"/><stop offset="100%" stop-color="{bg}" stop-opacity="0"/></radialGradient>')
        parts.append(f'<filter id="softGlow"><feGaussianBlur stdDeviation="4" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>')
        parts.append("</defs>")
        parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="{bg}"/>')
        parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="url(#crtGlow)"/>')

        # CRT frame and scanlines.
        parts.append(f'<rect x="28" y="24" width="{width-56}" height="{height-48}" rx="30" fill="none" stroke="{frame}" stroke-opacity="0.55" stroke-width="2"/>')
        parts.append(f'<rect x="45" y="43" width="{width-90}" height="{height-86}" rx="22" fill="none" stroke="{dim}" stroke-opacity="0.45" stroke-width="1"/>')
        for y in range(0, height, 8):
            parts.append(f'<line x1="0" y1="{y}" x2="{width}" y2="{y}" stroke="#000" stroke-opacity="0.18" stroke-width="2"/>')

        # Label strip.
        parts.append(f'<text x="52" y="68" fill="{dim}" font-family="monospace" font-size="15" letter-spacing="3">N.O.R.M. / {html.escape(pack.pack_id)}</text>')
        parts.append(f'<text x="{width-52}" y="68" text-anchor="end" fill="{primary}" font-family="monospace" font-size="15" letter-spacing="3">{html.escape(label)}</text>')

        def eye(x: int, side: str) -> None:
            parts.append(f'<g filter="url(#softGlow)">')
            parts.append(f'<rect x="{x}" y="{eye_y}" width="{eye_w}" height="{eye_h}" rx="24" fill="#120b04" stroke="{primary}" stroke-width="3"/>')
            parts.append(f'<rect x="{x+10}" y="{eye_y+10}" width="{eye_w-20}" height="{eye_h-20}" rx="18" fill="none" stroke="{dim}" stroke-opacity="0.7"/>')
            if blink >= 0.85 or mood == "sleeping":
                mid = eye_y + eye_h // 2
                parts.append(f'<line x1="{x+20}" y1="{mid}" x2="{x+eye_w-20}" y2="{mid}" stroke="{primary}" stroke-width="4" stroke-linecap="round"/>')
            else:
                px = x + eye_w / 2 + pupil_dx + (-5 if side == "left" and mood == "annoyed" else 0)
                py = eye_y + eye_h / 2 + pupil_dy
                parts.append(f'<ellipse cx="{px:.1f}" cy="{py:.1f}" rx="22" ry="24" fill="{primary}"/>')
                parts.append(f'<circle cx="{px-4:.1f}" cy="{py-5:.1f}" r="8" fill="{bright}"/>')
                parts.append(f'<circle cx="{px+5:.1f}" cy="{py+5:.1f}" r="4" fill="#2a1606" opacity="0.7"/>')
            parts.append("</g>")

        def brow_line(x: int, flip: int = 1) -> None:
            by = eye_y - 25
            if brow == "angry":
                y1, y2 = by + (12 * flip), by - (5 * flip)
            elif brow == "worried":
                y1, y2 = by - (8 * flip), by + (10 * flip)
            elif brow == "bored":
                y1, y2 = by + 12, by + 12
            else:
                y1, y2 = by, by
            parts.append(f'<line x1="{x+18}" y1="{y1}" x2="{x+eye_w-18}" y2="{y2}" stroke="{primary}" stroke-width="4" stroke-linecap="round" opacity="0.88"/>')

        brow_line(left_x, 1)
        brow_line(right_x, -1)
        eye(left_x, "left")
        eye(right_x, "right")

        mx = cx - mouth_w // 2
        my = mouth_y
        if mouth == "speaking":
            points = []
            for i in range(25):
                x = mx + i * (mouth_w / 24)
                amp = math.sin(i * 0.75) * 18
                points.append(f"{x:.1f},{my + amp:.1f}")
            parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{bright}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" filter="url(#softGlow)"/>')
        elif mouth == "thinking":
            for i in range(3):
                parts.append(f'<circle cx="{cx - 34 + i*34}" cy="{my}" r="{7+i}" fill="{bright}" opacity="{0.55 + i*0.15}"/>')
        elif mouth == "error":
            points = []
            for i in range(13):
                x = mx + i * (mouth_w / 12)
                y = my + (-12 if i % 2 == 0 else 12)
                points.append(f"{x:.1f},{y:.1f}")
            parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{warning}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')
        elif mouth == "frown":
            parts.append(f'<path d="M {mx+40} {my+10} Q {cx} {my-18} {mx+mouth_w-40} {my+10}" fill="none" stroke="{primary}" stroke-width="4" stroke-linecap="round"/>')
        elif mouth == "flat":
            parts.append(f'<line x1="{mx+60}" y1="{my}" x2="{mx+mouth_w-60}" y2="{my}" stroke="{dim}" stroke-width="4" stroke-linecap="round"/>')
        else:
            parts.append(f'<line x1="{mx+35}" y1="{my}" x2="{mx+mouth_w-35}" y2="{my}" stroke="{primary}" stroke-width="4" stroke-linecap="round" filter="url(#softGlow)"/>')
            parts.append(f'<line x1="{mx+95}" y1="{my+13}" x2="{mx+mouth_w-95}" y2="{my+13}" stroke="{dim}" stroke-width="2" stroke-linecap="round"/>')

        if glitch:
            for i, gy in enumerate([112, 211, 284, 391]):
                off = [-14, 8, -5, 18][i]
                parts.append(f'<line x1="{58+off}" y1="{gy}" x2="{width-58+off}" y2="{gy}" stroke="{bright}" stroke-opacity="0.62" stroke-width="2"/>')

        parts.append(f'<text x="{cx}" y="{height-52}" text-anchor="middle" fill="{dim}" font-family="monospace" font-size="14" letter-spacing="2">{html.escape(pack.description[:82])}</text>')
        parts.append("</svg>")
        return "\n".join(parts)
