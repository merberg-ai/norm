from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_boot_once():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "app.py", "--once", "--json-health"],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "plugin_manager" in result.stdout
    assert "hello_norm" in result.stdout
