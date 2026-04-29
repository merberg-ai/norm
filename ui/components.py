from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import pygame

Color = Tuple[int, int, int]


@dataclass
class TerminalButton:
    label: str
    rect: pygame.Rect
    action: str
    enabled: bool = True

    def contains(self, x: int, y: int) -> bool:
        return self.enabled and self.rect.collidepoint(x, y)

    def draw(self, surface: pygame.Surface, font: pygame.font.Font, colors: dict, active: bool = False) -> None:
        bg = colors.get("panel_background", (10, 8, 5))
        border = colors.get("border_bright", (255, 195, 70)) if active else colors.get("border", (220, 145, 35))
        text = colors.get("text_bright", (255, 220, 120)) if active else colors.get("text", (255, 185, 70))
        dim = colors.get("text_dim", (175, 115, 45))

        if not self.enabled:
            border = dim
            text = dim

        pygame.draw.rect(surface, bg, self.rect)
        pygame.draw.rect(surface, border, self.rect, 1)

        img = font.render(self.label.upper(), True, text)
        tx = self.rect.x + (self.rect.w - img.get_width()) // 2
        ty = self.rect.y + (self.rect.h - img.get_height()) // 2
        surface.blit(img, (tx, ty))


def draw_text(surface: pygame.Surface, font: pygame.font.Font, text: str, x: int, y: int, color: Color) -> None:
    surface.blit(font.render(str(text), True, color), (x, y))


def draw_panel(surface: pygame.Surface, rect: pygame.Rect, colors: dict, title: Optional[str], font: pygame.font.Font) -> None:
    bg = colors.get("panel_background", (10, 8, 5))
    border = colors.get("border_dim", (130, 80, 25))
    text = colors.get("text", (255, 185, 70))
    surface.fill(bg, rect)
    pygame.draw.rect(surface, border, rect, 1)
    if title:
        draw_text(surface, font, title.upper(), rect.x + 12, rect.y + 10, text)
        pygame.draw.line(surface, border, (rect.x + 8, rect.y + 36), (rect.x + rect.w - 8, rect.y + 36), 1)
