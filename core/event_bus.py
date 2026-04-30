from __future__ import annotations

import asyncio
import inspect
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

EventHandler = Callable[["Event"], Any | Awaitable[Any]]


@dataclass(frozen=True)
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "core"
    timestamp: float = field(default_factory=time.time)


class EventBus:
    """Small async event bus used by core services and plugins."""

    def __init__(self, logger=None, history_limit: int = 200):
        self.logger = logger
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)
        self._history: deque[Event] = deque(maxlen=history_limit)
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe to an exact event type or '*' for all events."""
        self._subscribers[event_type].append(handler)

    def history(self) -> list[Event]:
        return list(self._history)

    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        source: str = "core",
    ) -> Event:
        event = Event(type=event_type, payload=payload or {}, source=source)
        async with self._lock:
            self._history.append(event)

        handlers = list(self._subscribers.get(event_type, []))
        handlers.extend(self._subscribers.get("*", []))

        for handler in handlers:
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # noqa: BLE001 - plugin handlers must not kill core
                if self.logger:
                    self.logger.exception(
                        "Event handler failed for %s from %s: %s",
                        event.type,
                        event.source,
                        exc,
                    )
        return event
