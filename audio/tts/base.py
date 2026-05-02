from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class TTSResult:
    ok: bool
    engine: str
    output_path: Path | None = None
    error: str | None = None
    details: dict[str, Any] | None = None


class TTSEngine(Protocol):
    engine_id: str

    def available(self) -> tuple[bool, str]:
        ...

    def synthesize_to_file(self, text: str, output_path: Path) -> TTSResult:
        ...
