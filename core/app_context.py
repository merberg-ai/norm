from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.config import ConfigBundle
from core.event_bus import EventBus
from core.paths import NormPaths
from core.plugin_manager import PluginManagerService
from core.service_manager import ServiceManager
from webui.service import WebUIService


@dataclass
class AppContext:
    root: Path
    paths: NormPaths
    config: ConfigBundle
    logger: Any
    events: EventBus
    services: ServiceManager
    safe_mode: bool = False

    @classmethod
    def create(cls, root: Path, paths: NormPaths, config: ConfigBundle, logger) -> "AppContext":
        safe_mode = bool(config.get("app.safe_mode", False))
        events = EventBus(logger=logger)
        placeholder = cls(
            root=root,
            paths=paths,
            config=config,
            logger=logger,
            events=events,
            services=None,  # type: ignore[arg-type]
            safe_mode=safe_mode,
        )
        services = ServiceManager(placeholder)
        placeholder.services = services
        return placeholder

    def register_core_services(self) -> None:
        # PluginManager starts first so WebUI can mount configurable plugin routes.
        self.services.register(PluginManagerService(self))
        if bool(self.config.get("services.webui.enabled", True)):
            self.services.register(WebUIService(self))

    async def start(self) -> None:
        await self.events.publish("system.starting", {"codename": self.config.get("app.codename")})
        self.register_core_services()
        await self.services.start_all()
        await self.events.publish("system.ready", {"services": list(self.services.names())})

    async def stop(self) -> None:
        await self.events.publish("system.shutdown", {})
        await self.services.stop_all()

    async def health_report(self) -> dict[str, Any]:
        services = await self.services.health()
        return {
            "app": {
                "name": self.config.get("app.name"),
                "codename": self.config.get("app.codename"),
                "install_id": self.config.get("app.install_id"),
                "safe_mode": self.safe_mode,
            },
            "services": {
                name: {
                    "ok": health.ok,
                    "status": health.status,
                    "details": health.details,
                }
                for name, health in services.items()
            },
            "events_seen": len(self.events.history()),
        }

    async def wait_forever(self, heartbeat_seconds: int = 30) -> None:
        while True:
            await asyncio.sleep(max(1, heartbeat_seconds))
            await self.events.publish("system.heartbeat", {}, source="core")
