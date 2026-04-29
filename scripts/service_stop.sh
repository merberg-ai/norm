#!/usr/bin/env bash
set -euo pipefail
sudo systemctl stop norm-face.service
systemctl status norm-face.service --no-pager || true
