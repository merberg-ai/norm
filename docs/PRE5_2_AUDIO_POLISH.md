# N.O.R.M. beta2-pre5.2 Audio Polish

This overlay cleans up the Audio/TTS lab and fixes a bad Piper executable case.

## Fixes

- Adds Piper voice catalog with:
  - `en_US-lessac-medium`
  - `en_US-norman-medium`
- Adds per-voice download buttons and selected-voice dropdown.
- Adds busy button feedback while downloads, recording, playback, and TTS actions are running.
- Makes the Audio page more compact and cleaner.
- Passes selected Piper voice into TTS requests.
- Validates the Piper executable before using it.
- Prefers `./.venv/bin/piper` over `/usr/bin/piper`.
- Updates `install_audio_deps.sh` so it avoids apt's unrelated `piper` package and installs Piper TTS into the venv.

## Important

On some Raspberry Pi OS installs, `/usr/bin/piper` is not Piper TTS. It can be an unrelated GTK program and produce:

```text
ValueError: Namespace Gtk not available
```

This overlay prevents N.O.R.M. from using that binary as a TTS engine.
