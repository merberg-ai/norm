# N.O.R.M. beta2-pre3 — Face Core

pre3 adds the first real face core layer without starting the fullscreen screen renderer yet.

## Added

- `config/face.yaml` with `config_version: 2`
- `FaceService`
- face pack loader and validation
- renderer interface
- procedural SVG preview renderer
- built-in face packs:
  - `norm_default`
  - `norm_crt`
  - `norm_void`
- face states:
  - sleeping
  - idle
  - wake_detected
  - listening
  - thinking
  - speaking
  - happy
  - annoyed
  - confused
  - error
  - emergency
- Web UI `/face` page
- preview endpoint `/api/core/face/preview.svg`
- status endpoint `/api/core/face/status`
- state change endpoint `/api/core/face/state/{state}`
- pack change endpoint `/api/core/face/pack/{pack_id}`

## Notes

This release intentionally uses server-rendered SVG previews. The real fullscreen Raspberry Pi display renderer should come after the face pack/state APIs are stable.

This keeps the migration clean:

1. prove swappable face packs
2. prove web/API control
3. then graft the Pygame display loop back in as a screen renderer/service

## Test URLs

```text
http://<pi-ip>:8090/face
http://<pi-ip>:8090/api/core/face/status
http://<pi-ip>:8090/api/core/face/preview.svg?pack=norm_default&state=annoyed
```
