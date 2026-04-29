from __future__ import annotations

import logging
import time
from typing import Any, Dict, Tuple

import requests

from core.state import NormState
from brain import memory_store, prompt_builder

log = logging.getLogger("norm.brain.ollama")


def _host(config: Dict[str, Any]) -> str:
    host = str(config.get("brain", {}).get("host", "http://127.0.0.1:11434")).rstrip("/")
    return host


def _timeout(config: Dict[str, Any]) -> float:
    try:
        return float(config.get("brain", {}).get("timeout_seconds", 60))
    except Exception:
        return 60.0


def brain_status(config: Dict[str, Any], state: NormState | None = None) -> Dict[str, Any]:
    """Check whether the configured Ollama brain endpoint is reachable."""
    cfg = config.get("brain", {})
    enabled = bool(cfg.get("enabled", False))
    host = _host(config)
    model = cfg.get("chat_model", "norm-alpha")

    if not enabled:
        if state is not None:
            state.brain_status = "disabled"
        return {
            "ok": True,
            "enabled": False,
            "status": "disabled",
            "provider": cfg.get("provider", "ollama"),
            "host": host,
            "model": model,
            "message": "Brain disabled in config",
        }

    try:
        started = time.time()
        res = requests.get(f"{host}/api/tags", timeout=min(_timeout(config), 10.0))
        latency_ms = int((time.time() - started) * 1000)
        res.raise_for_status()
        payload = res.json()
        models = [m.get("name") for m in payload.get("models", []) if isinstance(m, dict)]
        model_present = model in models or any(str(name).split(":", 1)[0] == str(model).split(":", 1)[0] for name in models)
        status = "ready" if model_present else "model_missing"
        if state is not None:
            state.brain_status = status
            state.last_brain_error = None if model_present else f"Model not listed by Ollama: {model}"
        return {
            "ok": model_present,
            "enabled": True,
            "status": status,
            "provider": cfg.get("provider", "ollama"),
            "host": host,
            "model": model,
            "model_present": model_present,
            "models": models,
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        msg = str(exc)
        if state is not None:
            state.brain_status = "offline"
            state.last_brain_error = msg
        return {
            "ok": False,
            "enabled": True,
            "status": "offline",
            "provider": cfg.get("provider", "ollama"),
            "host": host,
            "model": model,
            "error": msg,
        }


def ask(config: Dict[str, Any], state: NormState, prompt: str, context: str | None = None) -> Tuple[bool, str, Dict[str, Any]]:
    """Send a typed prompt to Ollama and return (ok, response_or_error, metadata)."""
    cfg = config.get("brain", {})
    if not cfg.get("enabled", False):
        state.brain_status = "disabled"
        state.last_action = "BRAIN DISABLED"
        return False, "Brain disabled in config", {"status": "disabled"}

    provider = cfg.get("provider", "ollama")
    if provider != "ollama":
        msg = f"Unsupported brain provider: {provider}"
        state.brain_status = "error"
        state.set_error(msg)
        return False, msg, {"status": "error", "provider": provider}

    prompt = (prompt or "").strip()
    if not prompt:
        return False, "Prompt is empty", {"status": "empty_prompt"}

    host = _host(config)
    model = cfg.get("chat_model", "norm-alpha")
    timeout = _timeout(config)
    stream = bool(cfg.get("stream", False))
    max_prompt_chars = int(cfg.get("max_prompt_chars", 2000))
    prompt = prompt[:max_prompt_chars]

    mem_store = None
    mem_session_id = None
    prompt_meta: Dict[str, Any] = {"memory_enabled": False}
    try:
        if memory_store.memory_enabled(config):
            mem_store = memory_store.MemoryStore.from_config(config)
            mem_session_id = memory_store.session_id(config)
    except Exception as exc:
        # Memory must never break the live brain. Log it and continue stateless.
        log.warning("Memory initialization failed; continuing without memory: %s", exc)
        prompt_meta = {"memory_enabled": False, "memory_error": str(exc)}
        mem_store = None
        mem_session_id = None

    messages, built_meta = prompt_builder.build_messages(
        config=config,
        prompt=prompt,
        runtime_context=context,
        store=mem_store,
        session_id=mem_session_id,
    )
    prompt_meta.update(built_meta)

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }

    options = cfg.get("options")
    if isinstance(options, dict) and options:
        payload["options"] = options

    started = time.time()
    state.brain_status = "thinking"
    state.last_brain_prompt = prompt
    state.last_brain_error = None
    state.set_face_mode("thinking")
    state.last_action = "BRAIN REQUEST ACTIVE"

    try:
        log.info("Sending brain request to %s model=%s", host, model)
        res = requests.post(f"{host}/api/chat", json=payload, timeout=timeout)
        latency_ms = int((time.time() - started) * 1000)
        if res.status_code >= 400:
            msg = f"Ollama HTTP {res.status_code}: {res.text[:300]}"
            state.brain_status = "error"
            state.last_brain_error = msg
            state.set_error(f"Brain error: {msg[:100]}")
            return False, msg, {"status": "error", "latency_ms": latency_ms, "http_status": res.status_code, "memory": prompt_meta}

        data = res.json()
        if stream:
            # Stream mode is reserved for later. Keep alpha deterministic.
            text = str(data)
        else:
            text = data.get("message", {}).get("content", "").strip()

        if not text:
            text = "No response content returned. The brain stared into the void and blinked."

        state.brain_status = "ready"
        state.last_brain_response = text
        state.last_brain_at = time.time()
        state.last_brain_latency_ms = latency_ms
        state.last_error = None
        state.set_face_mode("speaking")
        state.last_action = f"BRAIN RESPONSE {time.strftime('%H:%M:%S')}"
        if mem_store is not None and mem_session_id and bool(memory_store.memory_config(config).get("auto_save_messages", True)):
            try:
                mem_store.add_message(mem_session_id, "user", prompt)
                mem_store.add_message(mem_session_id, "assistant", text)
            except Exception as exc:
                log.warning("Memory save failed: %s", exc)
                prompt_meta["memory_save_error"] = str(exc)

        return True, text, {
            "status": "ready",
            "host": host,
            "model": model,
            "latency_ms": latency_ms,
            "memory": prompt_meta,
            "raw": data if bool(cfg.get("include_raw", False)) else None,
        }
    except Exception as exc:
        latency_ms = int((time.time() - started) * 1000)
        msg = str(exc)
        state.brain_status = "offline"
        state.last_brain_error = msg
        state.set_error(f"Brain offline: {msg[:100]}")
        return False, msg, {"status": "offline", "host": host, "model": model, "latency_ms": latency_ms, "memory": prompt_meta}
