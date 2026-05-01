# N.O.R.M. beta2-pre4 — Face Designer Plugin Shell

Adds the first plugin-driven Face Designer.

## New route

- `/face-designer`

## New plugin API namespace

- `GET  /api/plugins/face_designer/packs`
- `GET  /api/plugins/face_designer/packs/{pack_id}`
- `POST /api/plugins/face_designer/packs/{pack_id}/duplicate`
- `POST /api/plugins/face_designer/packs/{pack_id}/save`
- `POST /api/plugins/face_designer/packs/{pack_id}/activate`
- `GET  /api/plugins/face_designer/packs/{pack_id}/preview?state=idle`

## Important behavior

Built-in packs under `face/packs/` are read-only. Duplicate a pack first, then edit the copy under `data/face_packs/`.

Saving creates a backup under `data/backups/face_designer/` before writing.

The editor is intentionally simple in pre4: pack selector, preview, duplicate, activate, and advanced YAML editing. Pretty sliders come next.
