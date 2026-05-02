# N.O.R.M. beta2-pre4.5 — Face Designer Visual Controls

Adds practical visual controls to the Face Designer plugin.

## Added

- Colors tab for procedural face pack colors.
- Geometry tab for eye and mouth placement/size.
- State tab for label, mood, mouth, brow, pupils, blink, and glitch.
- New API route: `POST /api/plugins/face_designer/packs/{pack_id}/style`.
- Built-in packs remain read-only; duplicate first, then edit the copy.
- Visual saves still create backups under `data/backups/face_designer/`.
- YAML editor remains available for advanced edits.

## Notes

This is still intentionally procedural-pack-only. Sprite/hybrid face designer support comes later.
