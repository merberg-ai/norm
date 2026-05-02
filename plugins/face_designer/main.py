from __future__ import annotations

import copy
import html
import inspect
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from core import yaml_compat as yaml_compat
from core.config import SUPPORTED_CONFIG_VERSION
from face.face_pack import FacePackError, load_face_pack

try:
    import yaml as pyyaml  # type: ignore
except Exception:  # noqa: BLE001
    pyyaml = None


_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_\-]+")


def _slug(value: str, fallback: str = "custom_face") -> str:
    value = value.strip().lower().replace(" ", "_")
    value = _SAFE_ID_RE.sub("_", value)
    value = re.sub(r"_+", "_", value).strip("_-")
    return value or fallback


def _json_response(data: dict[str, Any], *, status_code: int = 200):
    from fastapi.responses import JSONResponse

    return JSONResponse(data, status_code=status_code)


def _plain_response(text: str, *, status_code: int = 200):
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(text, status_code=status_code)


def _dump_yaml(data: dict[str, Any]) -> str:
    if pyyaml is not None:
        return pyyaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110)
    # Fallback is intentionally JSON-looking YAML. PyYAML should exist in beta2,
    # but this keeps the plugin debuggable if deps are not installed yet.
    return json.dumps(data, indent=2, ensure_ascii=False)


def _load_yaml_text(text: str) -> dict[str, Any]:
    data = yaml_compat.safe_load(text) or {}
    if not isinstance(data, dict):
        raise FacePackError("Face pack YAML must contain a mapping/object")
    return data


class Plugin:
    """Face Designer beta2-pre4 shell.

    This is intentionally practical rather than fancy: it can list packs,
    duplicate read-only built-ins into data/face_packs, edit advanced YAML,
    save with backups, validate by reloading through FaceService, preview states,
    and activate packs.
    """

    def setup(self, context, record):
        self.context = context
        self.record = record
        self.started = False
        self.route = record.webui_route or "/face-designer"
        self.plugin_api = f"/api/plugins/{record.plugin_id}"
        self.data_face_packs = context.paths.data_dir / "face_packs"
        self.backup_dir = context.paths.data_dir / "backups" / "face_designer"
        self.data_face_packs.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        context.logger.info("[%s] setup complete", record.plugin_id)

    async def start(self):
        self.started = True
        await self.context.events.publish(
            "face_designer.ready",
            {"route": self.route, "api": self.plugin_api},
            source=self.record.plugin_id,
        )

    async def stop(self):
        self.started = False

    async def health(self):
        face = self._face()
        return {
            "ok": face is not None and self.started,
            "started": self.started,
            "route": self.route,
            "api": self.plugin_api,
            "packs_seen": len(face.face_packs) if face else 0,
            "data_face_packs": str(self.data_face_packs),
        }

    def api_status(self):
        return {
            "plugin": self.record.plugin_id,
            "route": self.route,
            "api": self.plugin_api,
            "editor": self.record.config.get("editor", {}),
        }

    def get_webui_routes(self):
        return [
            {
                "path": self.route,
                "label": self.record.manifest.get("webui", {}).get("label", "Face Designer"),
                "nav_enabled": True,
            }
        ]

    def get_api_routes(self):
        return [
            {"path": "/packs", "methods": ["GET"], "handler": self.api_packs},
            {"path": "/packs/{pack_id}", "methods": ["GET"], "handler": self.api_pack},
            {"path": "/packs/{pack_id}/duplicate", "methods": ["POST"], "handler": self.api_duplicate_pack},
            {"path": "/packs/{pack_id}/save", "methods": ["POST"], "handler": self.api_save_pack},
            {"path": "/packs/{pack_id}/style", "methods": ["POST"], "handler": self.api_update_style},
            {"path": "/packs/{pack_id}/activate", "methods": ["POST"], "handler": self.api_activate_pack},
            {"path": "/packs/{pack_id}/preview", "methods": ["GET", "POST"], "handler": self.api_preview_pack},
        ]

    def get_tools(self):
        return []

    def _face(self):
        return self.context.get_service("face")

    def _pack_summary(self, pack) -> dict[str, Any]:
        return {
            "id": pack.pack_id,
            "name": pack.name,
            "description": pack.description,
            "renderer": pack.renderer,
            "readonly": pack.readonly,
            "states": pack.states,
            "path": str(pack.path),
        }

    async def _json_body(self, request) -> dict[str, Any]:
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            data = {}
        return data if isinstance(data, dict) else {}

    async def api_packs(self, request):
        face = self._face()
        if face is None:
            return _json_response({"ok": False, "error": "FaceService is not available"}, status_code=404)
        return {
            "ok": True,
            "active_pack": face.active_pack_id,
            "state": face.state,
            "packs": [self._pack_summary(pack) for pack in sorted(face.face_packs.values(), key=lambda p: p.pack_id)],
        }

    async def api_pack(self, request):
        face = self._face()
        if face is None:
            return _json_response({"ok": False, "error": "FaceService is not available"}, status_code=404)
        pack_id = request.path_params.get("pack_id")
        pack = face.face_packs.get(pack_id)
        if pack is None:
            return _json_response({"ok": False, "error": f"Face pack not found: {pack_id}"}, status_code=404)
        yaml_text = _dump_yaml(pack.config)
        return {
            "ok": True,
            "pack": self._pack_summary(pack),
            "config": pack.config,
            "yaml": yaml_text,
        }

    async def api_duplicate_pack(self, request):
        face = self._face()
        if face is None:
            return _json_response({"ok": False, "error": "FaceService is not available"}, status_code=404)
        pack_id = request.path_params.get("pack_id")
        pack = face.face_packs.get(pack_id)
        if pack is None:
            return _json_response({"ok": False, "error": f"Face pack not found: {pack_id}"}, status_code=404)

        data = await self._json_body(request)
        requested_id = str(data.get("new_id") or data.get("id") or "").strip()
        requested_name = str(data.get("name") or "").strip()
        prefix = str(self.record.config.get("editor", {}).get("default_duplicate_prefix", "custom"))
        if not requested_id:
            requested_id = f"{prefix}_{pack.pack_id}"
        new_id = _slug(requested_id, fallback=f"custom_{pack.pack_id}")
        new_name = requested_name or f"{pack.name} Custom"

        if new_id in face.face_packs:
            return _json_response({"ok": False, "error": f"Face pack already exists: {new_id}"}, status_code=409)

        dest = self.data_face_packs / new_id
        if dest.exists():
            return _json_response({"ok": False, "error": f"Destination already exists: {dest}"}, status_code=409)

        try:
            shutil.copytree(pack.path, dest)
            cfg = copy.deepcopy(pack.config)
            cfg["config_version"] = SUPPORTED_CONFIG_VERSION
            cfg["id"] = new_id
            cfg["name"] = new_name
            if "description" in cfg:
                cfg["description"] = f"Custom copy of {pack.name}. {cfg.get('description', '')}".strip()
            else:
                cfg["description"] = f"Custom copy of {pack.name}."
            self._write_pack_yaml(dest, cfg)
            face.load_face_packs()
            if new_id not in face.face_packs:
                raise FacePackError("Duplicated pack did not reload correctly")
            await self.context.events.publish(
                "face_designer.pack.duplicated",
                {"source_pack": pack_id, "new_pack": new_id},
                source=self.record.plugin_id,
            )
            return {"ok": True, "pack": self._pack_summary(face.face_packs[new_id])}
        except Exception as exc:  # noqa: BLE001
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            self.context.logger.exception("Face pack duplicate failed")
            face.load_face_packs()
            return _json_response({"ok": False, "error": str(exc)}, status_code=500)

    async def api_save_pack(self, request):
        face = self._face()
        if face is None:
            return _json_response({"ok": False, "error": "FaceService is not available"}, status_code=404)
        pack_id = request.path_params.get("pack_id")
        pack = face.face_packs.get(pack_id)
        if pack is None:
            return _json_response({"ok": False, "error": f"Face pack not found: {pack_id}"}, status_code=404)
        if pack.readonly:
            return _json_response(
                {"ok": False, "error": "Built-in face packs are read-only. Duplicate it first, then edit the copy."},
                status_code=403,
            )

        data = await self._json_body(request)
        yaml_text = str(data.get("yaml") or "")
        max_bytes = int(self.record.config.get("editor", {}).get("max_yaml_bytes", 200000))
        if not yaml_text.strip():
            return _json_response({"ok": False, "error": "No YAML supplied"}, status_code=400)
        if len(yaml_text.encode("utf-8")) > max_bytes:
            return _json_response({"ok": False, "error": f"YAML too large; max {max_bytes} bytes"}, status_code=413)

        target = pack.path / "face_pack.yaml"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.backup_dir / f"{pack_id}-{timestamp}.yaml"
        old_text = target.read_text(encoding="utf-8") if target.exists() else ""

        try:
            cfg = _load_yaml_text(yaml_text)
            cfg["config_version"] = SUPPORTED_CONFIG_VERSION
            cfg["id"] = pack_id
            if not cfg.get("renderer"):
                cfg["renderer"] = "procedural"
            if self.record.config.get("editor", {}).get("backup_before_save", True):
                backup.write_text(old_text, encoding="utf-8")
            rendered = _dump_yaml(cfg)
            target.write_text(rendered, encoding="utf-8")

            # Validate with the same loader the core uses, then reload FaceService.
            load_face_pack(pack.path, readonly=False)
            face.load_face_packs()
            if pack_id not in face.face_packs:
                raise FacePackError("Saved pack did not reload correctly")
            await self.context.events.publish(
                "face_designer.pack.saved",
                {"pack_id": pack_id, "backup": str(backup) if backup.exists() else None},
                source=self.record.plugin_id,
            )
            return {
                "ok": True,
                "pack": self._pack_summary(face.face_packs[pack_id]),
                "yaml": _dump_yaml(face.face_packs[pack_id].config),
                "backup": str(backup) if backup.exists() else None,
            }
        except Exception as exc:  # noqa: BLE001
            target.write_text(old_text, encoding="utf-8")
            face.load_face_packs()
            self.context.logger.exception("Face pack save failed; restored previous file")
            return _json_response({"ok": False, "error": str(exc), "restored": True}, status_code=400)
    async def api_update_style(self, request):
        """Patch common procedural face-pack settings from the visual controls."""
        face = self._face()
        if face is None:
            return _json_response({"ok": False, "error": "FaceService is not available"}, status_code=404)
        pack_id = request.path_params.get("pack_id")
        pack = face.face_packs.get(pack_id)
        if pack is None:
            return _json_response({"ok": False, "error": f"Face pack not found: {pack_id}"}, status_code=404)
        if pack.readonly:
            return _json_response(
                {"ok": False, "error": "Built-in face packs are read-only. Duplicate it first, then edit the copy."},
                status_code=403,
            )

        data = await self._json_body(request)
        cfg = copy.deepcopy(pack.config)
        changed: list[str] = []

        def normalize_color(value: Any) -> str | None:
            value = str(value or "").strip()
            if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                return value.lower()
            if re.fullmatch(r"#[0-9a-fA-F]{3}", value):
                return "#" + "".join(ch * 2 for ch in value[1:]).lower()
            return None

        def clean_number(value: Any, *, minimum: float, maximum: float, integer: bool = True) -> int | float | None:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            number = max(minimum, min(maximum, number))
            return int(round(number)) if integer else number

        colors_in = data.get("colors") if isinstance(data.get("colors"), dict) else {}
        if colors_in:
            colors = cfg.setdefault("colors", {})
            if not isinstance(colors, dict):
                colors = {}
                cfg["colors"] = colors
            for key in ["background", "frame", "primary", "bright", "dim", "warning"]:
                if key in colors_in:
                    color = normalize_color(colors_in.get(key))
                    if color is None:
                        return _json_response({"ok": False, "error": f"Invalid color for {key}"}, status_code=400)
                    colors[key] = color
                    changed.append(f"colors.{key}")

        geometry_in = data.get("geometry") if isinstance(data.get("geometry"), dict) else {}
        if geometry_in:
            geometry = cfg.setdefault("geometry", {})
            if not isinstance(geometry, dict):
                geometry = {}
                cfg["geometry"] = geometry
            limits = {
                "eye_w": (40, 320),
                "eye_h": (16, 180),
                "eye_y": (40, 290),
                "eye_gap": (0, 260),
                "mouth_w": (60, 620),
                "mouth_y": (210, 440),
            }
            for key, (minimum, maximum) in limits.items():
                if key in geometry_in:
                    number = clean_number(geometry_in.get(key), minimum=minimum, maximum=maximum)
                    if number is None:
                        return _json_response({"ok": False, "error": f"Invalid geometry number for {key}"}, status_code=400)
                    geometry[key] = number
                    changed.append(f"geometry.{key}")

        state_name = str(data.get("state") or "idle").strip()
        state_in = data.get("state_config") if isinstance(data.get("state_config"), dict) else {}
        if state_in:
            states = cfg.setdefault("states", {})
            if not isinstance(states, dict):
                states = {}
                cfg["states"] = states
            state_cfg = states.setdefault(state_name, {})
            if not isinstance(state_cfg, dict):
                state_cfg = {}
                states[state_name] = state_cfg

            for key in ["label", "mood"]:
                if key in state_in:
                    value = str(state_in.get(key) or "").strip()
                    if value:
                        state_cfg[key] = value[:64]
                        changed.append(f"states.{state_name}.{key}")
            if "mouth" in state_in:
                mouth = str(state_in.get("mouth") or "idle").strip()
                if mouth not in {"idle", "flat", "thinking", "speaking", "error", "frown"}:
                    return _json_response({"ok": False, "error": f"Invalid mouth value: {mouth}"}, status_code=400)
                state_cfg["mouth"] = mouth
                changed.append(f"states.{state_name}.mouth")
            if "brow" in state_in:
                brow = str(state_in.get("brow") or "flat").strip()
                if brow not in {"flat", "angry", "worried", "bored"}:
                    return _json_response({"ok": False, "error": f"Invalid brow value: {brow}"}, status_code=400)
                state_cfg["brow"] = brow
                changed.append(f"states.{state_name}.brow")
            for key in ["pupil_dx", "pupil_dy"]:
                if key in state_in:
                    number = clean_number(state_in.get(key), minimum=-60, maximum=60)
                    if number is None:
                        return _json_response({"ok": False, "error": f"Invalid state number for {key}"}, status_code=400)
                    state_cfg[key] = number
                    changed.append(f"states.{state_name}.{key}")
            if "blink" in state_in:
                number = clean_number(state_in.get("blink"), minimum=0, maximum=1, integer=False)
                if number is None:
                    return _json_response({"ok": False, "error": "Invalid blink value"}, status_code=400)
                state_cfg["blink"] = round(float(number), 2)
                changed.append(f"states.{state_name}.blink")
            if "glitch" in state_in:
                state_cfg["glitch"] = bool(state_in.get("glitch"))
                changed.append(f"states.{state_name}.glitch")
            for key in ["primary", "bright", "dim", "warning"]:
                if key in state_in:
                    raw = str(state_in.get(key) or "").strip()
                    if raw:
                        color = normalize_color(raw)
                        if color is None:
                            return _json_response({"ok": False, "error": f"Invalid state color for {key}"}, status_code=400)
                        state_cfg[key] = color
                        changed.append(f"states.{state_name}.{key}")

        if not changed:
            return _json_response({"ok": False, "error": "No style fields supplied"}, status_code=400)

        cfg["config_version"] = SUPPORTED_CONFIG_VERSION
        cfg["id"] = pack_id
        if not cfg.get("renderer"):
            cfg["renderer"] = "procedural"

        target = pack.path / "face_pack.yaml"
        old_text = target.read_text(encoding="utf-8")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.backup_dir / f"{pack_id}-{timestamp}-style.yaml.bak"

        try:
            if self.record.config.get("editor", {}).get("backup_before_save", True):
                backup.write_text(old_text, encoding="utf-8")
            target.write_text(_dump_yaml(cfg), encoding="utf-8")
            load_face_pack(pack.path, readonly=False)
            face.load_face_packs()
            if pack_id not in face.face_packs:
                raise FacePackError("Updated pack did not reload correctly")
            await self.context.events.publish(
                "face_designer.pack.style_saved",
                {"pack_id": pack_id, "changed": changed, "backup": str(backup) if backup.exists() else None},
                source=self.record.plugin_id,
            )
            new_pack = face.face_packs[pack_id]
            return {
                "ok": True,
                "pack": self._pack_summary(new_pack),
                "config": new_pack.config,
                "yaml": _dump_yaml(new_pack.config),
                "changed": changed,
                "backup": str(backup) if backup.exists() else None,
            }
        except Exception as exc:  # noqa: BLE001
            target.write_text(old_text, encoding="utf-8")
            face.load_face_packs()
            self.context.logger.exception("Face pack visual style save failed; restored previous file")
            return _json_response({"ok": False, "error": str(exc), "restored": True}, status_code=400)


    async def api_activate_pack(self, request):
        face = self._face()
        if face is None:
            return _json_response({"ok": False, "error": "FaceService is not available"}, status_code=404)
        pack_id = request.path_params.get("pack_id")
        ok = await face.set_active_pack(str(pack_id), source=self.record.plugin_id)
        return {"ok": ok, "status": face.status_payload()}

    async def api_preview_pack(self, request):
        face = self._face()
        if face is None:
            return _plain_response("FaceService is not available", status_code=404)
        pack_id = request.path_params.get("pack_id")
        state = request.query_params.get("state") or self.record.config.get("preview", {}).get("default_state", "idle")
        try:
            svg = face.render_preview_svg(pack_id=str(pack_id), state=str(state))
            from fastapi.responses import Response

            return Response(svg, media_type="image/svg+xml")
        except Exception as exc:  # noqa: BLE001
            return _plain_response(f"Preview failed: {exc}", status_code=500)

    def _write_pack_yaml(self, directory: Path, data: dict[str, Any]) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "face_pack.yaml").write_text(_dump_yaml(data), encoding="utf-8")

    def render_web_page(self):
        title = html.escape(self.record.manifest.get("name", self.record.plugin_id))
        route = html.escape(self.route)
        api = html.escape(self.plugin_api)
        return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{title}</title>
  <link rel=\"stylesheet\" href=\"/static/norm.css\">
</head>
<body>
  <div class=\"scanlines\"></div>
  <main class=\"shell\">
    <header class=\"topbar\">
      <div><div class=\"kicker\">Face pack containment lab</div><h1>{title}</h1></div>
      <div class=\"status-pill\">pre4.5 plugin</div>
    </header>
    <nav class=\"nav\"><a href=\"/\">Dashboard</a><a href=\"/face\">Face</a><a href=\"/plugins\">Plugins</a><a href=\"/events\">Events</a></nav>
    <section class=\"content\">
      <div class=\"designer-grid\">
        <aside class=\"designer-sidebar\">
          <div class=\"card\">
            <div class=\"card-title\">Pack</div>
            <div class=\"designer-controls\">
              <label class=\"norm-label\" for=\"packSelect\">Face pack</label>
              <select id=\"packSelect\" class=\"norm-input\"></select>
              <label class=\"norm-label\" for=\"stateSelect\">State</label>
              <select id=\"stateSelect\" class=\"norm-input\"></select>
              <div class=\"button-row\">
                <button id=\"refreshBtn\" class=\"norm-btn\">Refresh</button>
                <button id=\"activateBtn\" class=\"norm-btn\">Activate</button>
              </div>
              <p id=\"packMeta\" class=\"muted designer-meta\"></p>
            </div>
          </div>
          <div class=\"card\">
            <div class=\"card-title\">Duplicate</div>
            <p class=\"muted form-hint\">Built-in packs are read-only. Duplicate first, then mutate the copy. Sensible. Annoying. Necessary.</p>
            <label class=\"norm-label\" for=\"duplicateId\">New pack ID</label>
            <input id=\"duplicateId\" class=\"norm-input\" placeholder=\"custom_norm_default\">
            <label class=\"norm-label\" for=\"duplicateName\">New pack name</label>
            <input id=\"duplicateName\" class=\"norm-input\" placeholder=\"My Suspicious Face\">
            <div class=\"button-row\"><button id=\"duplicateBtn\" class=\"norm-btn\">Duplicate selected pack</button></div>
          </div>
        </aside>
        <div class=\"designer-main\">
          <div class=\"card face-preview-card\">
            <div class=\"card-title\">Preview</div>
            <div class=\"designer-preview-wrap\">
              <img id=\"previewImg\" class=\"face-preview\" alt=\"Face preview\">
            </div>
          </div>
          <div class="card designer-visual">
            <div class="card-title">Visual Controls</div>
            <p class="muted form-hint">Edit the common procedural face settings without hand-feeding YAML to the goblin.</p>
            <div class="designer-tabs" role="tablist" aria-label="Designer sections">
              <button class="norm-btn tab-btn active" data-tab="colors" type="button">Colors</button>
              <button class="norm-btn tab-btn" data-tab="geometry" type="button">Geometry</button>
              <button class="norm-btn tab-btn" data-tab="state" type="button">State</button>
            </div>
            <div class="visual-panel" data-panel="colors">
              <div class="control-grid compact">
                <label>Background <input id="color_background" type="color" class="color-input"></label>
                <label>Frame <input id="color_frame" type="color" class="color-input"></label>
                <label>Primary <input id="color_primary" type="color" class="color-input"></label>
                <label>Bright <input id="color_bright" type="color" class="color-input"></label>
                <label>Dim <input id="color_dim" type="color" class="color-input"></label>
                <label>Warning <input id="color_warning" type="color" class="color-input"></label>
              </div>
            </div>
            <div class="visual-panel hidden" data-panel="geometry">
              <div class="control-grid">
                <label>Eye width <input id="geo_eye_w" type="range" min="40" max="320" step="1"><output></output></label>
                <label>Eye height <input id="geo_eye_h" type="range" min="16" max="180" step="1"><output></output></label>
                <label>Eye Y <input id="geo_eye_y" type="range" min="40" max="290" step="1"><output></output></label>
                <label>Eye gap <input id="geo_eye_gap" type="range" min="0" max="260" step="1"><output></output></label>
                <label>Mouth width <input id="geo_mouth_w" type="range" min="60" max="620" step="1"><output></output></label>
                <label>Mouth Y <input id="geo_mouth_y" type="range" min="210" max="440" step="1"><output></output></label>
              </div>
            </div>
            <div class="visual-panel hidden" data-panel="state">
              <div class="control-grid">
                <label>Label <input id="state_label" class="norm-input" maxlength="64"></label>
                <label>Mood <input id="state_mood" class="norm-input" maxlength="64"></label>
                <label>Mouth <select id="state_mouth" class="norm-input"><option>idle</option><option>flat</option><option>thinking</option><option>speaking</option><option>error</option><option>frown</option></select></label>
                <label>Brow <select id="state_brow" class="norm-input"><option>flat</option><option>angry</option><option>worried</option><option>bored</option></select></label>
                <label>Pupil X <input id="state_pupil_dx" type="range" min="-60" max="60" step="1"><output></output></label>
                <label>Pupil Y <input id="state_pupil_dy" type="range" min="-60" max="60" step="1"><output></output></label>
                <label>Blink <input id="state_blink" type="range" min="0" max="1" step="0.05"><output></output></label>
                <label class="check-label"><input id="state_glitch" type="checkbox"> Glitch effect</label>
              </div>
            </div>
            <div class="button-row">
              <button id="saveVisualBtn" class="norm-btn">Save visual controls</button>
              <button id="syncYamlBtn" class="norm-btn">Sync from YAML</button>
            </div>
          </div>
          <div class="card designer-editor">
            <div class="card-title">Advanced YAML Editor</div>
            <p class="muted form-hint">Visual controls cover the usual knobs. YAML remains the forbidden basement for exact edits. Backup is made before save.</p>
            <textarea id="yamlEditor" class="norm-textarea" spellcheck="false"></textarea>
            <div class="button-row">
              <button id="saveBtn" class="norm-btn">Save YAML</button>
              <button id="reloadBtn" class="norm-btn">Reload selected pack</button>
            </div>
            <pre id="statusBox" class="status-log">Route: {route}\nAPI: {api}</pre>
          </div>
        </div>
      </div>
    </section>
  </main>
<script>
window.NORM_FACE_DESIGNER = {{ apiBase: "{api}" }};
</script>
<script src=\"/static/face_designer.js\"></script>
</body>
</html>"""
