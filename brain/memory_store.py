from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_SESSION_ID = "default"
VALID_ROLES = {"system", "user", "assistant"}


def utc_now() -> str:
    """Return a compact UTC timestamp string for SQLite rows."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def memory_config(config: Dict[str, Any]) -> Dict[str, Any]:
    return config.get("memory", {}) if isinstance(config.get("memory", {}), dict) else {}


def memory_enabled(config: Dict[str, Any]) -> bool:
    return bool(memory_config(config).get("enabled", False))


def _base_dir(config: Dict[str, Any]) -> Path:
    return Path(config.get("_base_dir", ".")).expanduser().resolve()


def database_path(config: Dict[str, Any]) -> Path:
    cfg = memory_config(config)
    raw = str(cfg.get("database_path", "data/norm_memory.sqlite3"))
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = _base_dir(config) / path
    return path.resolve()


def session_id(config: Dict[str, Any]) -> str:
    cfg = memory_config(config)
    sid = str(cfg.get("session_id", DEFAULT_SESSION_ID)).strip()
    return sid or DEFAULT_SESSION_ID


class MemoryStore:
    """Small SQLite-backed memory layer for N.O.R.M.

    Phase 1 intentionally uses only built-in sqlite3. sqlite-vec will slot in later
    without changing the basic conversation/session tables.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "MemoryStore":
        return cls(database_path(config))

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), timeout=15.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _init_schema(self) -> None:
        with self.connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation_sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('system', 'user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES conversation_sessions(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_conversation_messages_session_id
                    ON conversation_messages(session_id, id);

                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    session_id TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES conversation_sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS long_term_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_type TEXT NOT NULL DEFAULT 'note',
                    text TEXT NOT NULL,
                    importance INTEGER DEFAULT 5,
                    source TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT
                );

                CREATE TABLE IF NOT EXISTS memory_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    details_json TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    def ensure_session(self, session_id: str, title: Optional[str] = None) -> None:
        now = utc_now()
        clean_title = title or session_id
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO conversation_sessions(id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (session_id, clean_title, now, now),
            )

    def add_message(self, session_id: str, role: str, content: str) -> Optional[int]:
        role = (role or "").strip().lower()
        content = (content or "").strip()
        if role not in VALID_ROLES or not content:
            return None
        self.ensure_session(session_id)
        now = utc_now()
        with self.connect() as con:
            cur = con.execute(
                """
                INSERT INTO conversation_messages(session_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, now),
            )
            con.execute(
                "UPDATE conversation_sessions SET updated_at=? WHERE id=?",
                (now, session_id),
            )
            return int(cur.lastrowid)

    def recent_messages(self, session_id: str, limit: int = 16) -> List[Dict[str, Any]]:
        limit = max(0, min(int(limit or 0), 100))
        if limit <= 0:
            return []
        self.ensure_session(session_id)
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT id, role, content, created_at
                FROM conversation_messages
                WHERE session_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        out = [dict(row) for row in rows]
        out.reverse()
        return out

    def count_messages(self, session_id: Optional[str] = None) -> int:
        with self.connect() as con:
            if session_id:
                row = con.execute(
                    "SELECT COUNT(*) AS c FROM conversation_messages WHERE session_id=?",
                    (session_id,),
                ).fetchone()
            else:
                row = con.execute("SELECT COUNT(*) AS c FROM conversation_messages").fetchone()
        return int(row["c"] if row else 0)

    def count_long_term_memories(self) -> int:
        with self.connect() as con:
            row = con.execute("SELECT COUNT(*) AS c FROM long_term_memories").fetchone()
        return int(row["c"] if row else 0)

    def get_summary(self, session_id: str) -> Optional[str]:
        with self.connect() as con:
            row = con.execute(
                "SELECT summary FROM conversation_summaries WHERE session_id=?",
                (session_id,),
            ).fetchone()
        return str(row["summary"]) if row else None

    def set_summary(self, session_id: str, summary: str) -> None:
        summary = (summary or "").strip()
        if not summary:
            return
        self.ensure_session(session_id)
        now = utc_now()
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO conversation_summaries(session_id, summary, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET summary=excluded.summary, updated_at=excluded.updated_at
                """,
                (session_id, summary, now),
            )

    def add_long_term_memory(self, text: str, memory_type: str = "note", importance: int = 5, source: str = "manual") -> Optional[int]:
        text = (text or "").strip()
        if not text:
            return None
        now = utc_now()
        importance = max(1, min(int(importance or 5), 10))
        with self.connect() as con:
            cur = con.execute(
                """
                INSERT INTO long_term_memories(memory_type, text, importance, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (memory_type or "note", text, importance, source or "manual", now, now),
            )
            return int(cur.lastrowid)

    def list_long_term_memories(self, limit: int = 20) -> List[Dict[str, Any]]:
        limit = max(0, min(int(limit or 0), 200))
        if limit <= 0:
            return []
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT id, memory_type, text, importance, source, created_at, updated_at, last_used_at
                FROM long_term_memories
                ORDER BY importance DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_session(self, session_id: str) -> int:
        self.ensure_session(session_id)
        with self.connect() as con:
            row = con.execute(
                "SELECT COUNT(*) AS c FROM conversation_messages WHERE session_id=?",
                (session_id,),
            ).fetchone()
            count = int(row["c"] if row else 0)
            con.execute("DELETE FROM conversation_messages WHERE session_id=?", (session_id,))
            con.execute("DELETE FROM conversation_summaries WHERE session_id=?", (session_id,))
            con.execute(
                "UPDATE conversation_sessions SET updated_at=? WHERE id=?",
                (utc_now(), session_id),
            )
            return count

    def log_event(self, event_type: str, details: Optional[Dict[str, Any]] = None) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO memory_events(event_type, details_json, created_at) VALUES (?, ?, ?)",
                (event_type, json.dumps(details or {}, sort_keys=True), utc_now()),
            )

    def status(self, session_id: str) -> Dict[str, Any]:
        self.ensure_session(session_id)
        return {
            "ok": True,
            "enabled": True,
            "database_path": str(self.path),
            "session_id": session_id,
            "message_count": self.count_messages(session_id),
            "total_message_count": self.count_messages(None),
            "long_term_memory_count": self.count_long_term_memories(),
            "summary_exists": self.get_summary(session_id) is not None,
        }


def status_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    if not memory_enabled(config):
        return {
            "ok": True,
            "enabled": False,
            "status": "disabled",
            "message": "Memory disabled in config",
        }
    sid = session_id(config)
    store = MemoryStore.from_config(config)
    return store.status(sid)
