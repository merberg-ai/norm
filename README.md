<div align="center">

# N.O.R.M.
### Neural Overseer for Routine Management

**A creepy-but-useful Raspberry Pi robot assistant with an amber CRT face, local web cockpit, camera/audio diagnostics, espeak-ng speech, and an Ollama-powered brain.**

<br>

![Status](https://img.shields.io/badge/status-alpha-orange)
![Target](https://img.shields.io/badge/target-Raspberry%20Pi%205-red)
![Python](https://img.shields.io/badge/python-3.x-blue)
![UI](https://img.shields.io/badge/UI-Pygame%20%2B%20FastAPI-ffb000)
![Brain](https://img.shields.io/badge/brain-Ollama-black)
![Vibe](https://img.shields.io/badge/vibe-helpful%20%2F%20ominous-8b0000)

</div>

---

## What is N.O.R.M.?

**N.O.R.M.** is a Raspberry Pi robot-assistant project built around a 5-inch touchscreen face, camera, microphone, speaker, and local AI control layer.

This version is the early **Pi 5 alpha**: it boots into a full-screen animated amber terminal face, exposes a mobile-friendly web cockpit, checks camera/audio/brain/speech health, talks through `espeak-ng`, and can send prompts to an Ollama model called `norm-alpha`.

N.O.R.M. is helpful.

N.O.R.M. is watching.

Mostly helpful.

---

## Current version

```text
0.02-alpha-r4-memory
```

Default config:

```text
configs/norm-alpha.json
```

Default web cockpit:

```text
http://<pi-ip>:8088
```

---

## Features

### Animated face

- Full-screen Pygame renderer
- Amber CRT/terminal theme
- Eye, brow, mouth, and status text geometry
- Idle drift and blinking
- Scanlines, glow, vignette, noise, flicker, and glitch effects
- Face modes:
  - `idle`
  - `listening`
  - `thinking`
  - `speaking`
  - `error`
  - `sleep`
  - `glitch`
  - `annoyed`
  - `bored`
  - `worried`

### Touchscreen support

- Uses `evdev`
- Configurable touchscreen device path
- Axis inversion and XY swap support
- Touch input feeds the local UI
- Designed around QDtech MPI5001-style 5-inch displays

### Web cockpit

FastAPI-powered local cockpit with mobile-friendly amber terminal styling.

Pages include:

- Dashboard
- Face controls
- Camera testing
- Audio testing
- Brain prompt testing
- Memory core
- Config editor
- Diagnostics
- Logs

### REST API

Useful endpoints include:

```text
GET  /api/health
GET  /api/status
GET  /api/config
GET  /api/config/options
POST /api/config/device-settings
POST /api/config/raw
POST /api/config/reload

GET  /api/display/mode
POST /api/display/mode

GET  /api/face/state
POST /api/face/state
POST /api/face/text
POST /api/face/blink
POST /api/face/glitch

GET  /api/brain/status
POST /api/brain/ask

GET  /api/memory/status
GET  /api/memory/recent
GET  /api/memory/long-term
POST /api/memory/remember
POST /api/memory/clear-session

GET  /api/camera/status
GET  /api/camera/devices
GET  /api/camera/formats
POST /api/camera/snapshot
GET  /api/camera/latest.jpg

GET  /api/audio/status
GET  /api/audio/devices
POST /api/audio/record-test
POST /api/audio/play-recording
POST /api/audio/play-test
GET  /api/audio/latest-recording.wav

GET  /api/speech/status
POST /api/speech/speak
POST /api/speech/speak-test
GET  /api/speech/latest.wav

GET  /api/diagnostics
GET  /api/diagnostics/full
```

### Camera diagnostics

- USB camera support
- Default device: `/dev/video0`
- Default resolution: `640x480`
- Uses `fswebcam` for snapshots
- Device discovery through `v4l2-ctl`
- Snapshot endpoint available through the web cockpit/API

### Audio diagnostics

- ALSA input/output device scanning
- Microphone test recording through `arecord`
- Playback through `aplay`
- Configurable input/output devices
- Test recording stored by default at:

```text
/tmp/norm_mic_test.wav
```

### Speech / TTS

N.O.R.M. currently uses `espeak-ng`.

Default voice preset:

```text
creepy_terminal
```

Included presets:

| Preset | Mood |
|---|---|
| `creepy_terminal` | Slow, low, machine-like default |
| `deep_overseer` | Deeper, slower, more ominous |
| `clear_assistant` | More understandable assistant voice |
| `fast_diagnostic` | Quick system-report voice |
| `speak_spell_goblin` | Full cursed 1980s computer energy |

Configurable TTS settings include:

- Voice
- Speed
- Pitch
- Amplitude
- Word gap
- Max spoken characters
- Speak brain responses by default

Generated speech is written by default to:

```text
/tmp/norm_tts.wav
```



### SQLite memory core

N.O.R.M. now has Phase 1 conversation memory.

This uses Python's built-in `sqlite3` module, so there are no new package dependencies yet. Every successful `/brain` exchange can be stored in:

```text
data/norm_memory.sqlite3
```

The prompt builder can inject recent conversation turns into future Ollama requests, giving N.O.R.M. short-term continuity instead of treating every typed prompt like a fresh boot from the void.

Memory controls live at:

```text
http://<pi-ip>:8088/memory
```

Current memory features:

- SQLite schema bootstrap
- Conversation sessions
- Recent user/assistant turn recall
- Manual long-term memories
- Memory status API
- Clear current session API
- Config flags for enabling/disabling memory

Planned next memory phases:

- Rolling conversation summaries
- sqlite-vec semantic recall
- People database
- Camera/voice identity recognition
- Optional OMEN LAN offload service for heavy recognition

### Ollama brain

N.O.R.M. talks to an Ollama server using the `/api/chat` endpoint.

Default configured model:

```text
norm-alpha
```

The included model file lives at:

```text
models/Modelfile
```

Create the model with:

```bash
ollama create norm-alpha -f models/Modelfile
```

The current `Modelfile` is based on:

```text
llama3.1:8b
```

The default config points at a LAN Ollama host:

```text
http://192.168.1.24:11434
```

Change this in `configs/norm-alpha.json`:

```json
{
  "brain": {
    "host": "http://YOUR-OLLAMA-HOST:11434",
    "chat_model": "norm-alpha"
  }
}
```

---

## Hardware target

This alpha is aimed at a Raspberry Pi 5 build.

Known/default hardware assumptions from the config:

| Part | Default / expected |
|---|---|
| Platform | Raspberry Pi 5 |
| Display | 800x480 touchscreen |
| Touch input | `/dev/input/event0` |
| Camera | USB camera, `/dev/video0` |
| Microphone | ALSA capture device |
| Speaker | ALSA playback device |
| Brain | Ollama on LAN or local host |
| Motors | Disabled |
| Movement | Disabled by default |

N.O.R.M. has safety defaults baked in:

```json
{
  "safety": {
    "movement_allowed": false,
    "require_manual_enable_for_motors": true,
    "emergency_stop_enabled": true
  }
}
```

No movement is enabled in this alpha. N.O.R.M. can look ominous, but he should not roll into your ankles yet.

---

## Project structure

```text
norm/
├── app.py                     # Main entry point
├── brain/
│   └── ollama.py              # Ollama status + chat requests
├── configs/
│   └── norm-alpha.json        # Main runtime config
├── core/
│   ├── config.py              # Config/theme loading
│   ├── diagnostics.py         # System/hardware diagnostics
│   ├── logging.py             # Logging setup
│   └── state.py               # Shared runtime state
├── face/
│   └── renderer.py            # Pygame face renderer
├── hardware/
│   ├── audio.py               # ALSA recording/playback helpers
│   ├── camera.py              # Camera snapshot helpers
│   └── touch.py               # evdev touchscreen reader
├── models/
│   └── Modelfile              # Ollama model personality
├── scripts/
│   ├── install_deps.sh        # System + Python dependency setup
│   ├── install_service.sh     # systemd service installer
│   ├── run_dev.sh             # Main development runner
│   ├── run_api_only.sh        # Run web/API without display/touch
│   ├── test_audio.sh          # ALSA mic/speaker test
│   └── test_camera.sh         # Webcam snapshot test
├── services/
│   └── norm-face.service.example
├── sounds/
│   ├── startup.wav
│   ├── error.wav
│   └── beep.wav
├── speech/
│   └── tts.py                 # espeak-ng TTS support
├── tests/
│   ├── norm_face_smoke.py
│   └── norm_touch_probe.py
├── themes/
│   └── norm_terminal_amber.json
├── ui/
│   ├── components.py
│   └── local.py               # Touchscreen/local UI
└── web/
    ├── server.py              # FastAPI app
    ├── static/
    │   ├── norm.css
    │   └── norm.js
    └── templates/
        ├── dashboard.html
        ├── face.html
        ├── camera.html
        ├── audio.html
        ├── brain.html
        ├── config.html
        ├── diagnostics.html
        └── logs.html
```

---

## Install on Raspberry Pi

Clone the repo:

```bash
git clone https://github.com/YOUR-USERNAME/norm.git
cd norm
```

Install system and Python dependencies:

```bash
chmod +x scripts/*.sh
./scripts/install_deps.sh
```

The install script will:

- Install Raspberry Pi system packages
- Install Pygame, NumPy, evdev, camera/audio tools, FastAPI dependencies, and `espeak-ng`
- Create a Python virtual environment at `.venv`
- Add your user to common hardware groups:
  - `input`
  - `video`
  - `render`
  - `audio`

If this is the first time your user has been added to those groups, reboot:

```bash
sudo reboot
```

---

## Run in development mode

From the project folder:

```bash
./scripts/run_dev.sh
```

That starts:

- Pygame face renderer
- Touch reader
- FastAPI web cockpit
- Hardware status checks
- Ollama brain status check
- TTS status check

---

## Run API/cockpit only

Useful when testing remotely over SSH or when no display is attached:

```bash
./scripts/run_api_only.sh
```

Then open:

```text
http://<pi-ip>:8088
```

---

## Run manually with options

```bash
source .venv/bin/activate
python app.py --config configs/norm-alpha.json
```

Disable web/API:

```bash
python app.py --config configs/norm-alpha.json --no-web
```

Disable display:

```bash
python app.py --config configs/norm-alpha.json --no-display
```

Disable touch:

```bash
python app.py --config configs/norm-alpha.json --no-touch
```

Run cockpit only:

```bash
python app.py --config configs/norm-alpha.json --no-display --no-touch
```

---

## Install as a systemd service

Install and enable the service:

```bash
./scripts/install_service.sh
```

Start it:

```bash
sudo systemctl start norm-face.service
```

Check status:

```bash
./scripts/service_status.sh
```

Follow logs:

```bash
./scripts/service_logs.sh
```

Restart:

```bash
./scripts/service_restart.sh
```

Stop:

```bash
./scripts/service_stop.sh
```

Uninstall:

```bash
./scripts/uninstall_service.sh
```

---

## Hardware test helpers

### Test camera

```bash
./scripts/test_camera.sh
```

Custom camera device and output path:

```bash
./scripts/test_camera.sh /dev/video0 /tmp/norm-webcam-test.jpg
```

### Test audio

Record from a mic:

```bash
./scripts/test_audio.sh plughw:2,0
```

Record and play back:

```bash
./scripts/test_audio.sh plughw:2,0 plughw:3,0
```

### Find ALSA devices

```bash
arecord -l
aplay -l
```

### Find camera devices

```bash
v4l2-ctl --list-devices
```

### Find touch devices

```bash
cat /proc/bus/input/devices
```

---

## Configuration

Primary config file:

```text
configs/norm-alpha.json
```

Important sections:

| Section | Purpose |
|---|---|
| `system` | Name, version, profile, debug/log settings |
| `display` | Pygame display size, fullscreen, FPS, CRT effects |
| `theme` | Theme selection |
| `touch` | Touch device, axis transforms, tap behavior |
| `face` | Face geometry, modes, idle behavior, animations |
| `local_ui` | On-screen control UI |
| `web_ui` | Web cockpit options |
| `api` | Host/port/auth settings |
| `camera` | USB camera config |
| `audio` | ALSA mic/speaker config |
| `brain` | Ollama host/model settings |
| `speech` | TTS provider and voice settings |
| `hardware` | Platform and attached hardware notes |
| `safety` | Movement/motor safety settings |
| `service` | systemd service metadata |

The web cockpit also includes a config editor and device selectors.

When saving config through the app, backups are created automatically beside the config file.

---

## Theme

Current theme:

```text
themes/norm_terminal_amber.json
```

The web cockpit also uses matching amber terminal styling:

```text
web/static/norm.css
```

The intended vibe is:

```text
amber monochrome terminal
CRT scanlines
slightly haunted diagnostic console
helpful machine with suspicious motives
```

---

## Development notes

### Repository hygiene

Do not commit generated/runtime files:

```text
.venv/
__pycache__/
*.pyc
logs/*.log
*.zip
*.tar.gz
configs/*.bak-*
```

The included `.gitignore` already covers most of this. If your local tree has config backup files, remove them before publishing or add this line:

```gitignore
configs/*.bak-*
```

### Current alpha notes

- `configs/norm-alpha.json` is the active config.
- `scripts/run_dev.sh` is the preferred development launcher.
- `scripts/run_api_only.sh` is the clean remote-testing launcher.
- `scripts/run_dev_pi5.sh` references `configs/norm-pi5-alpha.json`; only use it if that config exists in your local tree.
- The configured vision model is present in config, but camera-based recognition/vision reasoning is not implemented yet.
- Motors and movement are intentionally disabled.
- Auth is disabled by default because this is assumed to run on a trusted LAN.

---

## Roadmap ideas

Planned or obvious next upgrades:

- Wake word support
- Speech-to-text
- Camera-assisted context for prompts
- Face/person recognition
- Voice recognition
- SQLite + sqlite-vec memory
- Identity confidence system using face/body/voice clues
- Piper or remote TTS support
- Better local UI config flow
- Optional LAN offload to a stronger desktop
- Future robot body/movement integration, gated behind safety config

---

## Suggested repo description

```text
An ominous Raspberry Pi robot assistant with an amber CRT face, FastAPI cockpit, camera/audio diagnostics, espeak-ng TTS, and an Ollama-powered local brain.
```

Suggested topics:

```text
raspberry-pi
raspberry-pi-5
ollama
fastapi
pygame
robot-assistant
ai-assistant
tts
espeak-ng
hardware-ui
creepy-ai
```

---

## License

Add your preferred license here.

Until then: all rights reserved by default.

---

<div align="center">

**N.O.R.M. is online. Routine oversight has begun.**

</div>
