from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class AudioDevice:
    id: str
    label: str
    direction: str
    card: str | None = None
    device: str | None = None
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CARD_RE = re.compile(r"card\s+(?P<card>\d+):\s*(?P<card_name>[^,]+),\s*device\s+(?P<dev>\d+):\s*(?P<dev_name>.+)")


def _run_lines(command: list[str]) -> list[str]:
    if not shutil.which(command[0]):
        return []
    try:
        proc = subprocess.run(command, check=False, text=True, capture_output=True, timeout=6)
    except Exception:
        return []
    return (proc.stdout or "").splitlines()


def _parse_alsa_listing(lines: list[str], direction: str) -> list[AudioDevice]:
    devices: list[AudioDevice] = []
    for line in lines:
        match = _CARD_RE.search(line)
        if not match:
            continue
        card = match.group("card")
        dev = match.group("dev")
        card_name = match.group("card_name").strip()
        dev_name = match.group("dev_name").strip()
        # plughw is friendlier for format conversion than raw hw.
        device_id = f"plughw:{card},{dev}"
        devices.append(
            AudioDevice(
                id=device_id,
                label=f"{card_name} / {dev_name} ({device_id})",
                direction=direction,
                card=card,
                device=dev,
                raw=line.strip(),
            )
        )
    return devices


def scan_audio_devices() -> dict[str, list[dict[str, Any]]]:
    outputs = [AudioDevice(id="default", label="ALSA default output", direction="output")]
    inputs = [AudioDevice(id="default", label="ALSA default input", direction="input")]

    outputs.extend(_parse_alsa_listing(_run_lines(["aplay", "-l"]), "output"))
    inputs.extend(_parse_alsa_listing(_run_lines(["arecord", "-l"]), "input"))

    # De-dupe while preserving order.
    def dedupe(items: list[AudioDevice]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for item in items:
            key = f"{item.direction}:{item.id}"
            if key in seen:
                continue
            seen.add(key)
            result.append(item.to_dict())
        return result

    return {"inputs": dedupe(inputs), "outputs": dedupe(outputs)}
