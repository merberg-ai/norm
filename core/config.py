from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core import yaml_compat as yaml

SUPPORTED_CONFIG_VERSION = 2


class ConfigError(RuntimeError):
    """Raised when N.O.R.M. beta2 config is missing, unsafe, or invalid."""


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle.read()) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config file must contain a YAML mapping/object: {path}")
    return data


def _validate_version(path: Path, data: dict[str, Any]) -> None:
    version = data.get("config_version")
    if version is None:
        raise ConfigError(f"Missing config_version in {path}")
    if not isinstance(version, int):
        raise ConfigError(f"config_version must be an integer in {path}")
    if version > SUPPORTED_CONFIG_VERSION:
        raise ConfigError(
            f"{path} uses future config_version={version}; "
            f"this runtime supports up to {SUPPORTED_CONFIG_VERSION}"
        )
    if version < SUPPORTED_CONFIG_VERSION:
        raise ConfigError(
            f"{path} uses old config_version={version}; "
            f"migration support is not implemented yet"
        )


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with overlay merged into base recursively."""
    result = deepcopy(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def get_path(data: dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    """Small helper for dotted config lookups: get_path(config, 'app.name')."""
    cur: Any = data
    for part in dotted_key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


@dataclass
class ConfigBundle:
    norm: dict[str, Any]
    plugins: dict[str, Any]
    config_dir: Path
    face: dict[str, Any] | None = None
    audio: dict[str, Any] | None = None
    brain: dict[str, Any] | None = None

    def get(self, dotted_key: str, default: Any = None) -> Any:
        return get_path(self.norm, dotted_key, default)

    def face_get(self, dotted_key: str, default: Any = None) -> Any:
        return get_path(self.face or {}, dotted_key, default)

    def plugin_overrides(self, plugin_id: str) -> dict[str, Any]:
        plugins = self.plugins.get("plugins", {})
        if not isinstance(plugins, dict):
            return {}
        entry = plugins.get(plugin_id, {})
        return entry if isinstance(entry, dict) else {}


class ConfigManager:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.bundle: ConfigBundle | None = None

    def load(self) -> ConfigBundle:
        norm_path = self.config_dir / "norm.yaml"
        plugins_path = self.config_dir / "plugins.yaml"
        face_path = self.config_dir / "face.yaml"
        audio_path = self.config_dir / "audio.yaml"
        brain_path = self.config_dir / "brain.yaml"

        norm = _read_yaml(norm_path)
        plugins = _read_yaml(plugins_path)
        face = _read_yaml(face_path) if face_path.exists() else {"config_version": SUPPORTED_CONFIG_VERSION}
        audio = _read_yaml(audio_path) if audio_path.exists() else {"config_version": SUPPORTED_CONFIG_VERSION}
        brain = _read_yaml(brain_path) if brain_path.exists() else {"config_version": SUPPORTED_CONFIG_VERSION}

        _validate_version(norm_path, norm)
        _validate_version(plugins_path, plugins)
        if face_path.exists():
            _validate_version(face_path, face)
        if audio_path.exists():
            _validate_version(audio_path, audio)
        if brain_path.exists():
            _validate_version(brain_path, brain)

        self.bundle = ConfigBundle(norm=norm, plugins=plugins, face=face, audio=audio, brain=brain, config_dir=self.config_dir)
        return self.bundle
