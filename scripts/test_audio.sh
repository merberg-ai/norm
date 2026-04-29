#!/usr/bin/env bash
set -euo pipefail
REC_DEVICE="${1:-plughw:0,0}"
PLAY_DEVICE="${2:-}"
OUT="/tmp/norm_mic_test.wav"

echo "[N.O.R.M.] Recording from: $REC_DEVICE"
arecord -D "$REC_DEVICE" -f S16_LE -r 16000 -c 1 -d 5 "$OUT"
ls -lh "$OUT"

if [ -n "$PLAY_DEVICE" ]; then
  echo "[N.O.R.M.] Playing through: $PLAY_DEVICE"
  aplay -D "$PLAY_DEVICE" "$OUT"
else
  echo "[N.O.R.M.] No playback device specified. Copy/download $OUT to verify recording."
fi
