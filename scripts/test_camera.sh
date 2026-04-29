#!/usr/bin/env bash
set -euo pipefail
DEVICE="${1:-/dev/video0}"
OUT="${2:-/tmp/norm-webcam-test.jpg}"
fswebcam -d "$DEVICE" -r 640x480 --no-banner "$OUT"
ls -lh "$OUT"
