# N.O.R.M. beta2-pre6 Brain Service

Adds a modular Ollama-backed BrainService.

Default Ollama host:

```yaml
ollama:
  host: "http://192.168.1.24:11434"
```

New Web UI pages/routes:

- `/brain`
- `/api/core/brain/status`
- `/api/core/brain/models`
- `/api/core/brain/chat`
- `/api/core/brain/actions`

The brain service emits:

- `brain.ready`
- `brain.thinking`
- `brain.response.ready`
- `brain.error`

When enabled, brain requests also drive face states and send responses to AudioService/TTS.
