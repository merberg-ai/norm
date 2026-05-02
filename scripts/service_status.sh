#!/usr/bin/env bash
set -euo pipefail
SERVICE_NAME="${NORM_SERVICE_NAME:-norm-beta2.service}"
systemctl status "$SERVICE_NAME" --no-pager --lines 40
