from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from audio.tts.base import TTSResult


class PiperEngine:
    engine_id = "piper"

    def __init__(self, config: dict[str, Any], root: Path):
        self.config = config or {}
        self.root = root
        self._executable_cache: str | None | bool = False
        self._diagnostics_cache: list[dict[str, str]] | None = None

    def _resolve(self, raw: str | None) -> Path:
        path = Path(str(raw or ""))
        return path if path.is_absolute() else (self.root / path).resolve()

    def _candidate_paths(self) -> list[Path]:
        """Return Piper TTS candidates in the order N.O.R.M. should trust them.

        Important: Raspberry Pi OS can install an unrelated /usr/bin/piper GUI-ish
        package. For N.O.R.M. beta2, the venv Piper TTS executable is the source
        of truth. PATH lookup is opt-in only.
        """
        candidates: list[Path] = []

        configured = str(self.config.get("executable") or "./.venv/bin/piper").strip()
        if configured and configured.lower() not in {"auto", "path", "none"}:
            candidates.append(self._resolve(configured))

        venv_piper = self.root / ".venv" / "bin" / "piper"
        candidates.append(venv_piper.resolve())

        if bool(self.config.get("allow_path_search", False)):
            found = shutil.which("piper")
            if found:
                candidates.append(Path(found).resolve())

        unique: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate)
            if key not in seen:
                seen.add(key)
                unique.append(candidate)
        return unique

    def _validate_executable(self, candidate: Path) -> tuple[bool, str]:
        if not candidate.exists():
            return False, "missing"
        if not candidate.is_file():
            return False, "not a file"
        if not candidate.stat().st_mode & 0o111:
            return False, "not executable"
        try:
            proc = subprocess.run(
                [str(candidate), "--help"],
                check=False,
                text=True,
                capture_output=True,
                timeout=8,
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"help check failed: {exc}"

        output = f"{proc.stdout}\n{proc.stderr}".lower()
        # Real Piper TTS help includes these CLI flags. The wrong /usr/bin/piper
        # on the Pi crashes through GTK/gi and does not expose them.
        if "--model" in output and "--output_file" in output:
            return True, "ok"
        if "namespace gtk not available" in output or "gi.require_version" in output:
            return False, "wrong /usr/bin/piper package; expected Piper TTS from .venv/bin/piper"
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "non-zero exit from --help").strip().splitlines()[-1:]
            return False, tail[0] if tail else "non-zero exit from --help"
        return False, "does not look like Piper TTS CLI"

    @property
    def executable(self) -> str | None:
        if self._executable_cache is not False:
            return self._executable_cache or None
        diagnostics: list[dict[str, str]] = []
        chosen: str | None = None
        for candidate in self._candidate_paths():
            ok, reason = self._validate_executable(candidate)
            diagnostics.append({"path": str(candidate), "ok": str(ok), "reason": reason})
            if ok:
                chosen = str(candidate)
                break
        self._diagnostics_cache = diagnostics
        self._executable_cache = chosen
        return chosen

    def executable_diagnostics(self) -> list[dict[str, str]]:
        _ = self.executable
        return self._diagnostics_cache or []

    @property
    def model_path(self) -> Path:
        return self._resolve(self.config.get("model_path"))

    @property
    def config_path(self) -> Path:
        return self._resolve(self.config.get("config_path"))

    def missing_files(self) -> list[str]:
        missing: list[str] = []
        if not self.model_path.exists():
            missing.append("model")
        if not self.config_path.exists():
            missing.append("config")
        return missing

    def available(self) -> tuple[bool, str]:
        exe = self.executable
        if not exe:
            detail = "; ".join(f"{d['path']}: {d['reason']}" for d in self.executable_diagnostics())
            return False, "Piper TTS executable not available" + (f" ({detail})" if detail else "")
        missing = self.missing_files()
        if missing:
            return False, "missing " + ", ".join(missing)
        return True, exe

    def synthesize_to_file(self, text: str, output_path: Path) -> TTSResult:
        ok, reason = self.available()
        if not ok:
            return TTSResult(ok=False, engine=self.engine_id, error=reason)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.executable or "./.venv/bin/piper",
            "--model", str(self.model_path),
            "--config", str(self.config_path),
            "--output_file", str(output_path),
            "--length_scale", str(float(self.config.get("length_scale", 1.0))),
            "--noise_scale", str(float(self.config.get("noise_scale", 0.667))),
            "--noise_w", str(float(self.config.get("noise_w", 0.8))),
            "--sentence_silence", str(float(self.config.get("sentence_silence", 0.2))),
        ]
        speaker_id = self.config.get("speaker_id")
        if speaker_id is not None and str(speaker_id).strip() != "":
            cmd.extend(["--speaker", str(speaker_id)])
        try:
            proc = subprocess.run(cmd, input=text + "\n", check=False, text=True, capture_output=True, timeout=120)
        except Exception as exc:  # noqa: BLE001
            return TTSResult(ok=False, engine=self.engine_id, error=str(exc))
        if proc.returncode != 0:
            return TTSResult(ok=False, engine=self.engine_id, error=(proc.stderr or proc.stdout or "piper failed").strip())
        return TTSResult(ok=True, engine=self.engine_id, output_path=output_path, details={"command": cmd})
