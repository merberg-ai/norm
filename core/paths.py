from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NormPaths:
    """Resolved project paths for the beta2 runtime."""

    root: Path
    config_dir: Path
    data_dir: Path
    logs_dir: Path
    plugins_dir: Path

    @classmethod
    def from_root(
        cls,
        root: Path,
        config_dir: str | Path = "config",
        data_dir: str | Path = "data",
        logs_dir: str | Path = "data/logs",
        plugins_dir: str | Path = "plugins",
    ) -> "NormPaths":
        root = root.resolve()
        return cls(
            root=root,
            config_dir=(root / config_dir).resolve(),
            data_dir=(root / data_dir).resolve(),
            logs_dir=(root / logs_dir).resolve(),
            plugins_dir=(root / plugins_dir).resolve(),
        )

    def ensure(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
