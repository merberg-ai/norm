from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core import yaml_compat as yaml
from core.config import SUPPORTED_CONFIG_VERSION


class FacePackError(RuntimeError):
    """Raised when a face pack is missing, unsafe, or invalid."""


@dataclass(frozen=True)
class FacePack:
    pack_id: str
    name: str
    description: str
    renderer: str
    path: Path
    config: dict[str, Any]
    readonly: bool = True

    @property
    def states(self) -> list[str]:
        states = self.config.get("states", {})
        if isinstance(states, dict):
            return sorted(str(key) for key in states.keys())
        return []

    def state_config(self, state: str) -> dict[str, Any]:
        states = self.config.get("states", {})
        if isinstance(states, dict):
            value = states.get(state) or states.get("idle") or {}
            return value if isinstance(value, dict) else {}
        return {}


def load_face_pack(path: Path, *, readonly: bool = True) -> FacePack:
    pack_path = path / "face_pack.yaml"
    if not pack_path.exists():
        raise FacePackError(f"Missing face_pack.yaml: {path}")

    with pack_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle.read()) or {}
    if not isinstance(data, dict):
        raise FacePackError(f"Face pack YAML must be a mapping/object: {pack_path}")

    version = data.get("config_version")
    if version != SUPPORTED_CONFIG_VERSION:
        raise FacePackError(
            f"Face pack {path.name} config_version must be {SUPPORTED_CONFIG_VERSION}; got {version}"
        )

    pack_id = data.get("id")
    if not isinstance(pack_id, str) or not pack_id:
        raise FacePackError(f"Face pack {path.name} is missing string id")

    renderer = data.get("renderer", "procedural")
    if not isinstance(renderer, str) or not renderer:
        raise FacePackError(f"Face pack {pack_id} has invalid renderer")

    return FacePack(
        pack_id=pack_id,
        name=str(data.get("name") or pack_id),
        description=str(data.get("description") or ""),
        renderer=renderer,
        path=path,
        config=data,
        readonly=readonly,
    )
