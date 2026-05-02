from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from audio.tts.base import TTSResult


class EspeakEngine:
    engine_id = "espeak"

    def __init__(self, config: dict[str, Any]):
        self.config = config or {}
        self.executable = self._find_executable()

    def _find_executable(self) -> str | None:
        for candidate in self.config.get("executable_preference", ["espeak-ng", "espeak"]):
            found = shutil.which(str(candidate))
            if found:
                return found
        return None

    def available(self) -> tuple[bool, str]:
        if self.executable:
            return True, self.executable
        return False, "espeak-ng/espeak not found"

    def synthesize_to_file(self, text: str, output_path: Path) -> TTSResult:
        ok, reason = self.available()
        if not ok:
            return TTSResult(ok=False, engine=self.engine_id, error=reason)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        voice = str(self.config.get("voice", "en-us"))
        variant = str(self.config.get("variant") or "").strip()
        if variant and not voice.endswith(variant):
            voice = f"{voice}+{variant}"
        cmd = [
            self.executable or "espeak-ng",
            "-w", str(output_path),
            "-v", voice,
            "-s", str(int(self.config.get("speed", 150))),
            "-p", str(int(self.config.get("pitch", 45))),
            "-a", str(int(self.config.get("amplitude", 120))),
            "-g", str(int(self.config.get("word_gap", 10))),
            text,
        ]
        try:
            proc = subprocess.run(cmd, check=False, text=True, capture_output=True, timeout=60)
        except Exception as exc:  # noqa: BLE001
            return TTSResult(ok=False, engine=self.engine_id, error=str(exc))
        if proc.returncode != 0:
            return TTSResult(ok=False, engine=self.engine_id, error=(proc.stderr or proc.stdout or "espeak failed").strip())
        return TTSResult(ok=True, engine=self.engine_id, output_path=output_path, details={"command": cmd})
