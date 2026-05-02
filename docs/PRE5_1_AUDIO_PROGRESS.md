# N.O.R.M. beta2-pre5.1 Audio Progress Hotfix

Adds the AudioService, /audio Web UI page, TTS manager, Piper/eSpeak engines,
Piper model downloading with progress, and microphone record/playback actions
with progress polling.

Install:

```bash
cd ~/norm
unzip -o norm-beta2-pre5.1-audio-progress-overlay.zip
./scripts/fix_permissions.sh
./scripts/install_deps.sh
./scripts/install_audio_deps.sh
./scripts/run_web.sh
```

Open:

```text
http://<pi-ip>:8090/audio
```

Long-running actions create an action id, return immediately, and are polled by
/static/audio.js. This keeps the UI responsive and gives feedback for downloads,
recording, speaker playback, and browser playback generation.
