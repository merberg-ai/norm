from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from brain.ollama_client import OllamaClient
from core.service import BaseService, ServiceHealth


@dataclass
class BrainAction:
    id: str
    kind: str
    status: str = "queued"
    progress: float = 0.0
    message: str = "Queued"
    prompt: str = ""
    response: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": round(float(self.progress), 2),
            "message": self.message,
            "prompt": self.prompt,
            "response": self.response,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "result": self.result,
        }


class BrainService(BaseService):
    """Ollama-backed brain loop for N.O.R.M. beta2."""

    name = "brain"

    def __init__(self, context):
        super().__init__(context)
        self.brain_config: dict[str, Any] = getattr(context.config, "brain", {}) or {}
        self.actions: dict[str, BrainAction] = {}
        self.models_cache: dict[str, Any] | None = None
        self.models_checked_at: float | None = None
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        await super().start()
        self._cleanup_task = asyncio.create_task(self._cleanup_actions_loop())
        await self.context.events.publish("brain.ready", self.status_payload(), source="brain")

    async def stop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
        await super().stop()

    def _cfg(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.brain_config
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def _ollama_host(self) -> str:
        return str(self._cfg("ollama.host", "http://192.168.1.24:11434") or "http://192.168.1.24:11434")

    def _ollama_model(self) -> str:
        return str(self._cfg("ollama.model", "llama3.1:8b") or "llama3.1:8b")

    def _client(self) -> OllamaClient:
        return OllamaClient(self._ollama_host(), timeout=int(self._cfg("ollama.request_timeout_seconds", 120)))

    def _options(self) -> dict[str, Any]:
        options = self._cfg("ollama.options", {}) or {}
        return options if isinstance(options, dict) else {}

    def _system_prompt(self) -> str:
        return str(self._cfg("behavior.system_prompt", "") or "")

    def _speak_enabled(self) -> bool:
        return bool(self._cfg("behavior.speak_responses", True))

    def _browser_only_tts(self) -> bool:
        return bool(self._cfg("behavior.browser_only_tts", False))

    def _face_reactions_enabled(self) -> bool:
        return bool(self._cfg("behavior.face_reactions", True))

    async def _cleanup_actions_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            cutoff = time.time() - 1800
            for action_id in list(self.actions.keys()):
                action = self.actions[action_id]
                if action.finished_at and action.finished_at < cutoff:
                    self.actions.pop(action_id, None)

    def _new_action(self, kind: str, message: str, prompt: str = "") -> BrainAction:
        action = BrainAction(id=uuid.uuid4().hex[:12], kind=kind, message=message, prompt=prompt)
        self.actions[action.id] = action
        return action

    def action_payload(self, action_id: str) -> dict[str, Any] | None:
        action = self.actions.get(action_id)
        return action.to_dict() if action else None

    def actions_payload(self) -> dict[str, Any]:
        return {action_id: action.to_dict() for action_id, action in sorted(self.actions.items(), key=lambda kv: kv[1].started_at, reverse=True)}

    async def list_models(self, *, refresh: bool = False) -> dict[str, Any]:
        ttl = int(self._cfg("ollama.models_cache_seconds", 30))
        if self.models_cache is not None and not refresh and self.models_checked_at and (time.time() - self.models_checked_at) < ttl:
            return self.models_cache
        timeout = int(self._cfg("ollama.models_timeout_seconds", 8))
        payload = await asyncio.to_thread(self._client().tags, timeout=timeout)
        self.models_cache = payload
        self.models_checked_at = time.time()
        return payload

    def status_payload(self) -> dict[str, Any]:
        return {
            "enabled": bool(self._cfg("enabled", True)),
            "provider": str(self._cfg("provider", "ollama")),
            "ollama": {
                "host": self._ollama_host(),
                "model": self._ollama_model(),
                "request_timeout_seconds": int(self._cfg("ollama.request_timeout_seconds", 120)),
                "models_checked_at": self.models_checked_at,
                "models_cache": self.models_cache,
            },
            "behavior": {
                "speak_responses": self._speak_enabled(),
                "browser_only_tts": self._browser_only_tts(),
                "face_reactions": self._face_reactions_enabled(),
            },
            "actions": self.actions_payload(),
        }

    async def start_chat(self, message: str, *, speak: bool | None = None, model: str | None = None) -> dict[str, Any]:
        message = str(message or "").strip()
        if not message:
            raise ValueError("Message is empty")
        action = self._new_action("chat", "Queued brain request", prompt=message)
        asyncio.create_task(self._run_chat_action(action, speak=speak, model=model))
        return action.to_dict()

    async def _set_face_state(self, state: str) -> None:
        if not self._face_reactions_enabled():
            return
        await self.context.events.publish("face.state.set", {"state": state}, source="brain")

    async def _run_chat_action(self, action: BrainAction, *, speak: bool | None = None, model: str | None = None) -> None:
        action.status = "running"
        action.progress = 5
        action.message = "Thinking"
        await self.context.events.publish("brain.thinking", {"action_id": action.id, "prompt": action.prompt}, source="brain")
        await self._set_face_state("thinking")
        try:
            chosen_model = str(model or self._ollama_model())
            keep_alive = self._cfg("ollama.keep_alive", "5m")
            action.progress = 15
            action.message = f"Calling Ollama {self._ollama_host()}"
            result = await asyncio.to_thread(
                self._client().generate,
                model=chosen_model,
                prompt=action.prompt,
                system=self._system_prompt(),
                options=self._options(),
                keep_alive=str(keep_alive) if keep_alive else None,
            )
            action.progress = 80
            if not result.ok:
                raise RuntimeError(result.error or "Ollama request failed")
            text = result.text.strip()
            action.response = text
            action.result = {
                "model": result.model or chosen_model,
                "host": self._ollama_host(),
                "raw": result.raw,
            }
            await self.context.events.publish(
                "brain.response.ready",
                {"action_id": action.id, "response": text, "model": result.model or chosen_model},
                source="brain",
            )
            should_speak = self._speak_enabled() if speak is None else bool(speak)
            if should_speak and text:
                audio = self.context.get_service("audio") if hasattr(self.context, "get_service") else self.context.services.services.get("audio")
                if audio is not None and hasattr(audio, "start_speak"):
                    action.message = "Response ready; sending to TTS"
                    action.progress = 90
                    audio_action = await audio.start_speak(text, browser_only=self._browser_only_tts())
                    action.result["audio_action"] = audio_action
                else:
                    action.result["audio_warning"] = "Audio service unavailable"
                    await self._set_face_state("idle")
            else:
                await self._set_face_state("idle")
            action.status = "success"
            action.progress = 100
            action.message = "Response ready"
        except Exception as exc:  # noqa: BLE001
            action.status = "error"
            action.error = str(exc)
            action.message = f"Error: {exc}"
            action.progress = max(action.progress, 100 if action.progress >= 99 else action.progress)
            self.context.logger.exception("Brain action failed: %s", action.kind)
            await self.context.events.publish("brain.error", {"action_id": action.id, "error": str(exc)}, source="brain")
            await self._set_face_state("error")
        finally:
            action.finished_at = time.time()

    async def health(self) -> ServiceHealth:
        return ServiceHealth(ok=self.started, status="running" if self.started else "stopped", details=self.status_payload())
