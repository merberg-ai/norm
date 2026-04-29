from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from brain import memory_store


DEFAULT_SYSTEM_PROMPT = (
    "You are N.O.R.M. — Neural Overseer for Routine Management. "
    "You are a creepy but helpful Raspberry Pi assistant with a screen face, camera, microphone, and speakers. "
    "Use remembered conversation context when it is relevant, but do not pretend to know things that are not in memory or the current prompt."
)


def _memory_cfg(config: Dict[str, Any]) -> Dict[str, Any]:
    return config.get("memory", {}) if isinstance(config.get("memory", {}), dict) else {}


def _as_int(value: Any, fallback: int, low: int, high: int) -> int:
    try:
        n = int(value)
    except Exception:
        n = fallback
    return max(low, min(n, high))


def _trim(text: Optional[str], limit: int) -> str:
    text = (text or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[trimmed]"


def _role(row: Dict[str, Any]) -> str:
    role = str(row.get("role", "user")).strip().lower()
    return role if role in {"system", "user", "assistant"} else "user"


def _message(role: str, content: str) -> Dict[str, str]:
    return {"role": role, "content": content}


def build_messages(
    config: Dict[str, Any],
    prompt: str,
    runtime_context: Optional[str] = None,
    store: Optional[memory_store.MemoryStore] = None,
    session_id: Optional[str] = None,
) -> tuple[List[Dict[str, str]], Dict[str, Any]]:
    """Build the Ollama chat message list.

    Returns (messages, meta) so the API can show what memory was included without
    exposing a huge raw prompt unless desired.
    """

    cfg = _memory_cfg(config)
    prompt = (prompt or "").strip()
    max_block_chars = _as_int(cfg.get("max_memory_block_chars", 6000), 6000, 500, 30000)
    max_runtime_chars = _as_int(cfg.get("max_runtime_context_chars", 2000), 2000, 0, 12000)
    include_recent = bool(cfg.get("include_recent_messages", True))
    include_summary = bool(cfg.get("include_session_summary", False))
    include_long_term = bool(cfg.get("include_long_term_memories", False))
    max_recent = _as_int(cfg.get("max_recent_messages", 16), 16, 0, 80)
    max_long_term = _as_int(cfg.get("max_long_term_memories", 8), 8, 0, 40)

    messages: List[Dict[str, str]] = []
    meta: Dict[str, Any] = {
        "memory_enabled": bool(cfg.get("enabled", False)),
        "session_id": session_id,
        "recent_messages_included": 0,
        "summary_included": False,
        "long_term_memories_included": 0,
    }

    system_prompt = str(cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT).strip()
    if cfg.get("inject_system_prompt", True) and system_prompt:
        messages.append(_message("system", _trim(system_prompt, max_block_chars)))

    if runtime_context:
        messages.append(_message("system", "Runtime context from the robot controller:\n" + _trim(runtime_context, max_runtime_chars)))

    if store is not None and session_id:
        if include_summary:
            summary = store.get_summary(session_id)
            if summary:
                messages.append(_message("system", "Conversation summary memory:\n" + _trim(summary, max_block_chars)))
                meta["summary_included"] = True

        if include_long_term and max_long_term > 0:
            memories = store.list_long_term_memories(max_long_term)
            if memories:
                lines = []
                for mem in memories:
                    lines.append(f"- [{mem.get('memory_type', 'note')}, importance {mem.get('importance', 5)}] {mem.get('text', '')}")
                messages.append(_message("system", "Long-term memories that may be relevant:\n" + _trim("\n".join(lines), max_block_chars)))
                meta["long_term_memories_included"] = len(memories)

        if include_recent and max_recent > 0:
            recent = store.recent_messages(session_id, max_recent)
            for row in recent:
                content = _trim(str(row.get("content", "")), max_block_chars)
                if content:
                    messages.append(_message(_role(row), content))
            meta["recent_messages_included"] = len(recent)

    messages.append(_message("user", prompt))
    meta["message_count_sent"] = len(messages)
    return messages, meta
