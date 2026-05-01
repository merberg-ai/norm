from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Iterable

from core.service import BaseService, ServiceHealth


class ServiceManager:
    """Starts and stops core services in a predictable order."""

    def __init__(self, context):
        self.context = context
        self.services: OrderedDict[str, BaseService] = OrderedDict()

    def register(self, service: BaseService) -> None:
        if service.name in self.services:
            raise ValueError(f"Service already registered: {service.name}")
        self.services[service.name] = service

    async def start_all(self) -> None:
        for service in self.services.values():
            self.context.logger.info("Starting service: %s", service.name)
            await service.start()
            await self.context.events.publish(
                "service.started",
                {"service": service.name},
                source="service_manager",
            )

    async def stop_all(self) -> None:
        stop_timeout = int(self.context.config.get("runtime.service_stop_timeout_seconds", 5))
        event_timeout = int(self.context.config.get("runtime.event_publish_timeout_seconds", 2))
        for service in reversed(list(self.services.values())):
            self.context.logger.info("Stopping service: %s", service.name)
            try:
                await asyncio.wait_for(service.stop(), timeout=max(1, stop_timeout))
                try:
                    await asyncio.wait_for(
                        self.context.events.publish(
                            "service.stopped",
                            {"service": service.name},
                            source="service_manager",
                        ),
                        timeout=max(1, event_timeout),
                    )
                except asyncio.TimeoutError:
                    self.context.logger.warning("Timed out publishing service.stopped for %s", service.name)
            except asyncio.TimeoutError:
                self.context.logger.warning("Timed out stopping service: %s", service.name)
            except Exception as exc:  # noqa: BLE001
                self.context.logger.exception("Service failed during stop: %s", exc)

    async def health(self) -> dict[str, ServiceHealth]:
        result: dict[str, ServiceHealth] = {}
        for name, service in self.services.items():
            try:
                result[name] = await service.health()
            except Exception as exc:  # noqa: BLE001
                result[name] = ServiceHealth(ok=False, status="health_failed", details={"error": str(exc)})
        return result

    def names(self) -> Iterable[str]:
        return self.services.keys()
