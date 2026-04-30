# N.O.R.M. beta2-pre1 migration notes

This package is intentionally separate from the current deployed N.O.R.M. install.

Recommended Pi location:

```bash
~/norm-beta2/
```

Do not copy this over `~/norm/` yet.

## Current alpha code worth porting later

- `web/static/norm.css` and `web/static/norm.js` for the dark amber cockpit style
- `web/templates/` as inspiration for beta2 web UI shell
- `face/renderer.py` as the first procedural face renderer
- `speech/tts.py` as reference for eSpeak settings/presets
- `brain/ollama.py` and `brain/prompt_builder.py` for BrainService
- `brain/memory_store.py` for the memory migration path
- `hardware/audio.py`, `hardware/camera.py`, and `hardware/touch.py` for diagnostics/services

## Why pre1 is boring

Pre1 proves the core runtime can boot, load versioned config, start services, discover plugins, run plugin lifecycle hooks, and survive plugin failure.

That foundation comes before face designer, Piper, wake word, memory, identity, or body hardware.
