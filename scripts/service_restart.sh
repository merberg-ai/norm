#!/usr/bin/env bash
set -euo pipefail
SERVICE_NAME="${NORM_SERVICE_NAME:-norm-beta2.service}"
sudo systemctl restart "$SERVICE_NAME"
systemctl status "$SERVICE_NAME" --no-pager --lines 25
