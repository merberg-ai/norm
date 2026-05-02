# N.O.R.M. beta2-pre5 Audio + TTS Manager

Adds a core AudioService, ALSA device scanning, test recording/playback, Piper/eSpeak TTS engines, and a Web UI model manager for Piper voice files.

## New UI

Open:

```text
/audio
```

## Install audio tools

```bash
./scripts/install_audio_deps.sh
```

## Piper voices

The Web UI can download the configured Piper voice files into:

```text
models/piper/
```

A Piper voice needs at least the `.onnx` model and `.onnx.json` config file. The MODEL_CARD is downloaded when possible for license/reference info.

## Notes

Piper is preferred, but eSpeak remains the fallback. Missing Piper models should not stop N.O.R.M. from booting.
