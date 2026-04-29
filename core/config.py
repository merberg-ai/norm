from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class ConfigError(RuntimeError):
    pass


def load_json(path: str | Path) -> Dict[str, Any]:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ConfigError(f"JSON file not found: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {p}: {exc}") from exc


def load_config(path: str | Path) -> Dict[str, Any]:
    cfg = load_json(path)
    cfg["_config_path"] = str(Path(path).expanduser().resolve())
    cfg["_base_dir"] = str(Path(path).expanduser().resolve().parent.parent)
    return cfg


def load_theme(config: Dict[str, Any]) -> Dict[str, Any]:
    base_dir = Path(config.get("_base_dir", ".")).resolve()
    theme_block = config.get("theme", {})
    theme_name = config.get("face", {}).get("theme") or theme_block.get("default") or theme_block.get("fallback")
    theme_dir = base_dir / theme_block.get("theme_dir", "themes")
    theme_path = theme_dir / f"{theme_name}.json"

    if not theme_path.exists():
        fallback = theme_block.get("fallback", "norm_terminal_amber")
        theme_path = theme_dir / f"{fallback}.json"

    theme = load_json(theme_path)
    theme["_theme_path"] = str(theme_path)
    return theme


def deep_get(d: Dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur
