from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ServiceHealth:
    ok: bool
    status: str = "unknown"
    details: dict[str, Any] = field(default_factory=dict)


class BaseService:
    """Base class for beta2 core services."""

    name = "base"

    def __init__(self, context):
        self.context = context
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def health(self) -> ServiceHealth:
        return ServiceHealth(ok=self.started, status="running" if self.started else "stopped")
