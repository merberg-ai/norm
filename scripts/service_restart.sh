#!/usr/bin/env bash
set -euo pipefail
sudo systemctl restart norm-face.service
systemctl status norm-face.service --no-pager
