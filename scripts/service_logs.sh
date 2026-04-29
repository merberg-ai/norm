#!/usr/bin/env bash
set -euo pipefail
journalctl -u norm-face.service -f
