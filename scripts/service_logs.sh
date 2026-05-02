#!/usr/bin/env bash
set -euo pipefail
SERVICE_NAME="${NORM_SERVICE_NAME:-norm-beta2.service}"
journalctl -u "$SERVICE_NAME" -f
