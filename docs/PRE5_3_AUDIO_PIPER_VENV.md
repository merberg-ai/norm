# N.O.R.M. beta2-pre5.3 Audio Piper venv fix

This patch makes `.venv/bin/piper` the trusted Piper TTS executable.

Why:
- Raspberry Pi OS may expose an unrelated `/usr/bin/piper` package.
- That binary can crash with GTK/gi errors and is not Piper TTS.
- N.O.R.M. now prefers `./.venv/bin/piper` and disables blind PATH lookup by default.

Also included:
- Piper voice catalog with Lessac and Norman medium voices.
- Per-voice download buttons.
- More compact `/audio` layout.
- Button busy/progress feedback during download, TTS, record, and playback actions.
- `scripts/check_piper_tts.sh` diagnostic helper.
