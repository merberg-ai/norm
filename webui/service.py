from __future__ import annotations

import asyncio
import html
import inspect
from pathlib import Path
from typing import Any

from core.service import BaseService, ServiceHealth


class WebUIService(BaseService):
    """FastAPI web cockpit shell for beta2-pre4.

    This service intentionally stays tiny. It exposes core health/config/events,
    plugin health, and configurable plugin landing routes. Later pre-releases can
    replace these HTML string renderers with templates without changing the core
    service contract.
    """

    name = "webui"

    def __init__(self, context):
        super().__init__(context)
        self.app = None
        self.server = None
        self.server_task: asyncio.Task | None = None
        self.import_error: str | None = None
        self.bound_routes: list[str] = []

    async def start(self) -> None:
        await super().start()
        try:
            self.app = self._build_app()
        except RuntimeError as exc:
            self.import_error = str(exc)
            self.context.logger.error("Web UI failed to initialize: %s", exc)
            await self.context.events.publish(
                "webui.failed",
                {"error": str(exc)},
                source="webui",
            )
            return
        except Exception as exc:  # noqa: BLE001
            self.import_error = str(exc)
            self.context.logger.exception("Web UI failed to initialize: %s", exc)
            await self.context.events.publish(
                "webui.failed",
                {"error": str(exc)},
                source="webui",
            )
            return

        enabled = bool(self.context.config.get("webui.enabled", True))
        if not enabled:
            self.context.logger.info("Web UI service initialized but webui.enabled=false")
            await self.context.events.publish("webui.ready", {"enabled": False}, source="webui")
            return

        host = str(self.context.config.get("webui.host", "0.0.0.0"))
        port = int(self.context.config.get("webui.port", 8090))
        log_level = str(self.context.config.get("webui.uvicorn_log_level", "warning"))

        try:
            import uvicorn
        except Exception as exc:  # noqa: BLE001
            self.import_error = f"uvicorn import failed: {exc}"
            self.context.logger.error("Web UI dependency missing: %s", self.import_error)
            await self.context.events.publish(
                "webui.failed",
                {"error": self.import_error},
                source="webui",
            )
            return

        config = uvicorn.Config(self.app, host=host, port=port, log_level=log_level, access_log=False)
        self.server = uvicorn.Server(config)
        self.server_task = asyncio.create_task(self.server.serve())
        await asyncio.sleep(0.15)
        self.context.logger.info("Web UI listening on http://%s:%s", host, port)
        await self.context.events.publish(
            "webui.ready",
            {"enabled": True, "host": host, "port": port, "routes": self.bound_routes},
            source="webui",
        )

    async def stop(self) -> None:
        if self.server is not None:
            self.context.logger.info("Stopping Web UI")
            self.server.should_exit = True
        if self.server_task is not None:
            try:
                await asyncio.wait_for(self.server_task, timeout=5)
            except asyncio.TimeoutError:
                self.server_task.cancel()
        await super().stop()

    def _build_app(self):
        try:
            from fastapi import FastAPI
            from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
            from fastapi.staticfiles import StaticFiles
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "FastAPI web dependencies are missing. Run ./scripts/install_deps.sh"
            ) from exc

        app = FastAPI(title="N.O.R.M. beta2", version=self.context.config.get("app.codename", "beta2"))

        static_dir = self.context.root / "webui" / "static"
        if static_dir.exists():
            app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", response_class=HTMLResponse)
        async def dashboard():
            report = await self.context.health_report()
            return self._page("Dashboard", self._render_dashboard(report))

        @app.get("/plugins", response_class=HTMLResponse)
        async def plugins_page():
            return self._page("Plugins", await self._render_plugins_page())

        @app.get("/face", response_class=HTMLResponse)
        async def face_page():
            return self._page("Face", self._render_face_page())

        @app.get("/config", response_class=HTMLResponse)
        async def config_page():
            return self._page("Config", self._render_config_page())

        @app.get("/events", response_class=HTMLResponse)
        async def events_page():
            return self._page("Events", self._render_events_page())

        @app.get("/logs", response_class=HTMLResponse)
        async def logs_page():
            return self._page("Logs", self._render_logs_page())

        @app.get("/api/core/health", response_class=JSONResponse)
        async def api_health():
            return await self.context.health_report()

        @app.get("/api/core/config", response_class=JSONResponse)
        async def api_config():
            return {
                "norm": self.context.config.norm,
                "plugins": self.context.config.plugins,
                "face": self.context.config.face or {},
            }

        @app.get("/api/core/events", response_class=JSONResponse)
        async def api_events():
            return {"events": [self._event_to_dict(event) for event in self.context.events.history()]}

        @app.get("/api/core/face/status", response_class=JSONResponse)
        async def api_face_status():
            face = self._face_service()
            if face is None:
                return JSONResponse({"ok": False, "error": "face service not available"}, status_code=404)
            return face.status_payload()

        @app.get("/api/core/face/screen/diagnostics", response_class=JSONResponse)
        async def api_face_screen_diagnostics():
            face = self._face_service()
            if face is None:
                return JSONResponse({"ok": False, "error": "face service not available"}, status_code=404)
            return face.screen_diagnostics_payload()

        @app.post("/api/core/face/state/{state}", response_class=JSONResponse)
        async def api_face_set_state(state: str):
            face = self._face_service()
            if face is None:
                return JSONResponse({"ok": False, "error": "face service not available"}, status_code=404)
            ok = await face.set_state(state, source="webui")
            return {"ok": ok, "status": face.status_payload()}

        @app.post("/api/core/face/pack/{pack_id}", response_class=JSONResponse)
        async def api_face_set_pack(pack_id: str):
            face = self._face_service()
            if face is None:
                return JSONResponse({"ok": False, "error": "face service not available"}, status_code=404)
            ok = await face.set_active_pack(pack_id, source="webui")
            return {"ok": ok, "status": face.status_payload()}

        @app.get("/api/core/face/preview.svg")
        async def api_face_preview_svg(pack: str | None = None, state: str | None = None):
            face = self._face_service()
            if face is None:
                return PlainTextResponse("face service not available", status_code=404)
            try:
                svg = face.render_preview_svg(pack_id=pack, state=state)
                return Response(svg, media_type="image/svg+xml")
            except Exception as exc:  # noqa: BLE001
                return PlainTextResponse(f"face preview failed: {exc}", status_code=500)

        @app.get("/api/plugins", response_class=JSONResponse)
        async def api_plugins():
            return {"plugins": await self._plugin_statuses()}

        @app.get("/api/plugins/{plugin_id}/health", response_class=JSONResponse)
        async def api_plugin_health(plugin_id: str):
            record = self._get_plugin_record(plugin_id)
            if record is None:
                return JSONResponse({"ok": False, "error": "plugin not found"}, status_code=404)
            return await self._plugin_health(record)

        @app.get("/api/plugins/{plugin_id}/status", response_class=JSONResponse)
        async def api_plugin_status(plugin_id: str):
            record = self._get_plugin_record(plugin_id)
            if record is None:
                return JSONResponse({"ok": False, "error": "plugin not found"}, status_code=404)
            payload = await self._plugin_health(record)
            if record.instance and hasattr(record.instance, "api_status"):
                result = record.instance.api_status()
                if inspect.isawaitable(result):
                    result = await result
                payload["plugin_status"] = result
            return payload

        # Plugin-owned API/page routes, mounted through Starlette so FastAPI/Pydantic
        # does not inspect plugin callables or app-context object graphs.
        plugin_manager = self.context.services.services.get("plugin_manager")
        if plugin_manager is not None:
            for record in plugin_manager.records.values():
                if record.enabled and record.instance is not None:
                    self._mount_plugin_custom_routes(app, record, HTMLResponse, JSONResponse, PlainTextResponse, Response)

            # Configurable plugin landing routes, e.g. /hello, /face-designer, or later /servos.
            for record in plugin_manager.records.values():
                if not record.enabled or not record.webui_route:
                    continue
                self._mount_plugin_route(app, record, HTMLResponse, PlainTextResponse)

        return app

    def _mount_plugin_custom_routes(self, app, record, HTMLResponse, JSONResponse, PlainTextResponse, Response) -> None:
        """Mount plugin-declared API/web routes safely.

        Plugins return route specs from get_api_routes(). Handlers are called
        manually from a Starlette route wrapper, so FastAPI never tries to
        dependency-inject plugin objects.
        """
        if not record.instance:
            return
        route_specs = []
        if hasattr(record.instance, "get_api_routes"):
            try:
                result = record.instance.get_api_routes()
                route_specs.extend(result or [])
            except Exception as exc:  # noqa: BLE001
                self.context.logger.exception("Plugin API route discovery failed: %s", record.plugin_id)
                return
        for spec in route_specs:
            if not isinstance(spec, dict):
                continue
            suffix = str(spec.get("path") or "").strip()
            if not suffix:
                continue
            if not suffix.startswith("/"):
                suffix = "/" + suffix
            full_path = f"/api/plugins/{record.plugin_id}{suffix}"
            methods = spec.get("methods") or ["GET"]
            if isinstance(methods, str):
                methods = [methods]
            methods = [str(m).upper() for m in methods]
            handler = spec.get("handler")
            if handler is None or not callable(handler):
                continue
            self._mount_plugin_endpoint(app, record, full_path, methods, handler, HTMLResponse, JSONResponse, PlainTextResponse, Response)
            self.bound_routes.append(full_path)

    def _mount_plugin_endpoint(self, app, record, path, methods, handler, HTMLResponse, JSONResponse, PlainTextResponse, Response) -> None:
        bound_handler = handler
        bound_record = record
        bound_path = path

        async def plugin_endpoint(request):
            try:
                result = bound_handler(request)
                if inspect.isawaitable(result):
                    result = await result
                return self._plugin_result_to_response(result, HTMLResponse, JSONResponse, PlainTextResponse, Response)
            except Exception as exc:  # noqa: BLE001
                self.context.logger.exception("Plugin endpoint failed: %s %s", bound_record.plugin_id, bound_path)
                return JSONResponse({"ok": False, "error": str(exc), "plugin": bound_record.plugin_id}, status_code=500)

        app.add_route(path, plugin_endpoint, methods=methods)

    def _plugin_result_to_response(self, result, HTMLResponse, JSONResponse, PlainTextResponse, Response):
        if isinstance(result, Response):
            return result
        if isinstance(result, (dict, list)):
            return JSONResponse(result)
        if isinstance(result, bytes):
            return Response(result)
        text = "" if result is None else str(result)
        stripped = text.lstrip().lower()
        if stripped.startswith("<!doctype") or stripped.startswith("<html"):
            return HTMLResponse(text)
        return PlainTextResponse(text)

    def _mount_plugin_route(self, app, record, HTMLResponse, PlainTextResponse) -> None:
        route = record.webui_route
        if not route:
            return
        self.bound_routes.append(route)

        # Do not bind PluginRecord as a default route argument. FastAPI/Pydantic
        # treats default arguments as request parameters and tries to deepcopy
        # the whole PluginRecord/AppContext graph, which causes recursion on
        # Python 3.13. Capture it in a closure instead.
        bound_record = record

        async def plugin_page(request):  # Starlette route endpoint; request is intentionally accepted.
            try:
                if bound_record.instance and hasattr(bound_record.instance, "render_web_page"):
                    result = bound_record.instance.render_web_page()
                    if inspect.isawaitable(result):
                        result = await result
                    return HTMLResponse(str(result))
                body = self._render_plugin_landing(bound_record)
                return HTMLResponse(self._page(bound_record.manifest.get("name", bound_record.plugin_id), body))
            except Exception as exc:  # noqa: BLE001
                self.context.logger.exception("Plugin route failed: %s", bound_record.plugin_id)
                return PlainTextResponse(f"Plugin route failed: {exc}", status_code=500)

        # Use Starlette's plain route layer for plugin landing pages.
        # FastAPI's add_api_route inspects endpoint signatures with Pydantic.
        # That is great for typed API handlers, but bad for dynamic plugin pages
        # because plugin closures can drag the AppContext/PluginRecord object graph
        # into dependency analysis. app.add_route bypasses that machinery.
        app.add_route(route, plugin_page, methods=["GET"])

    def _page(self, title: str, body: str) -> str:
        nav = self._render_nav()
        safe_title = html.escape(title)
        return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>N.O.R.M. beta2 · {safe_title}</title>
  <link rel=\"stylesheet\" href=\"/static/norm.css\">
</head>
<body>
  <div class=\"scanlines\"></div>
  <main class=\"shell\">
    <header class=\"topbar\">
      <div>
        <div class=\"kicker\">Neural Overseer for Routine Management</div>
        <h1>N.O.R.M. beta2</h1>
      </div>
      <div class=\"status-pill\">pre3.5 face screen</div>
    </header>
    {nav}
    <section class=\"content\">{body}</section>
  </main>
</body>
</html>"""

    def _render_nav(self) -> str:
        items = [
            ("/", "Dashboard"),
            ("/plugins", "Plugins"),
            ("/face", "Face"),
            ("/config", "Config"),
            ("/events", "Events"),
            ("/logs", "Logs"),
        ]
        plugin_manager = self.context.services.services.get("plugin_manager")
        if plugin_manager is not None:
            for record in plugin_manager.records.values():
                if record.enabled and record.webui_route:
                    label = record.manifest.get("webui", {}).get("label") or record.manifest.get("name") or record.plugin_id
                    items.append((record.webui_route, str(label)))
        links = "".join(f'<a href="{html.escape(path)}">{html.escape(label)}</a>' for path, label in items)
        return f'<nav class="nav">{links}</nav>'

    def _render_dashboard(self, report: dict[str, Any]) -> str:
        app = report.get("app", {})
        services = report.get("services", {})
        service_cards = []
        for name, health in services.items():
            ok = bool(health.get("ok"))
            service_cards.append(
                f"""<div class=\"card {'ok' if ok else 'bad'}\">
                    <div class=\"card-title\">{html.escape(name)}</div>
                    <div class=\"big\">{'OK' if ok else 'FAIL'}</div>
                    <div class=\"muted\">{html.escape(str(health.get('status')))}</div>
                </div>"""
            )
        return f"""
        <div class=\"grid\">
          <div class=\"card wide\">
            <div class=\"card-title\">Runtime</div>
            <p><b>App:</b> {html.escape(str(app.get('name')))} / {html.escape(str(app.get('codename')))}</p>
            <p><b>Install ID:</b> {html.escape(str(app.get('install_id')))}</p>
            <p><b>Safe mode:</b> {html.escape(str(app.get('safe_mode')))}</p>
            <p><b>Events seen:</b> {html.escape(str(report.get('events_seen')))}</p>
          </div>
          {''.join(service_cards)}
        </div>
        """

    async def _render_plugins_page(self) -> str:
        statuses = await self._plugin_statuses()
        rows = []
        for plugin_id, status in statuses.items():
            route = status.get("route") or ""
            route_html = f'<a href="{html.escape(route)}">{html.escape(route)}</a>' if route else "—"
            rows.append(
                f"""<tr>
                    <td>{html.escape(plugin_id)}</td>
                    <td>{html.escape(str(status.get('status')))}</td>
                    <td>{html.escape(str(status.get('enabled')))}</td>
                    <td>{route_html}</td>
                    <td><code>{html.escape(', '.join(status.get('permissions') or []))}</code></td>
                </tr>"""
            )
        return f"""
        <div class=\"card wide\">
          <div class=\"card-title\">Plugin containment chamber</div>
          <p class=\"muted\">Loaded plugins, permissions, routes, and health. The goblins are being observed.</p>
          <table>
            <thead><tr><th>Plugin</th><th>Status</th><th>Enabled</th><th>Route</th><th>Permissions</th></tr></thead>
            <tbody>{''.join(rows) or '<tr><td colspan="5">No plugins discovered.</td></tr>'}</tbody>
          </table>
        </div>
        """

    def _render_config_page(self) -> str:
        import json

        norm = html.escape(json.dumps(self.context.config.norm, indent=2, sort_keys=True))
        plugins = html.escape(json.dumps(self.context.config.plugins, indent=2, sort_keys=True))
        face = html.escape(json.dumps(self.context.config.face or {}, indent=2, sort_keys=True))
        return f"""
        <div class=\"grid\">
          <div class=\"card wide\"><div class=\"card-title\">config/norm.yaml</div><pre>{norm}</pre></div>
          <div class=\"card wide\"><div class=\"card-title\">config/plugins.yaml</div><pre>{plugins}</pre></div>
          <div class=\"card wide\"><div class=\"card-title\">config/face.yaml</div><pre>{face}</pre></div>
        </div>
        """

    def _render_events_page(self) -> str:
        rows = []
        for seq, event in enumerate(reversed(self.context.events.history()[-100:]), start=1):
            event_data = self._event_to_dict(event)
            rows.append(
                f"""<tr>
                  <td>{html.escape(str(seq))}</td>
                  <td>{html.escape(str(event_data.get('type')))}</td>
                  <td>{html.escape(str(event_data.get('source')))}</td>
                  <td><code>{html.escape(str(event_data.get('payload')))}</code></td>
                </tr>"""
            )
        return f"""
        <div class=\"card wide\">
          <div class=\"card-title\">Event bus history</div>
          <p class=\"muted\">Most recent 100 events.</p>
          <table><thead><tr><th>#</th><th>Event</th><th>Source</th><th>Payload</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
        </div>
        """

    def _render_logs_page(self) -> str:
        log_dir = self.context.paths.logs_dir
        files = []
        if log_dir.exists():
            for path in sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
                files.append(f"<li><code>{html.escape(path.name)}</code> — {path.stat().st_size} bytes</li>")
        return f"""
        <div class=\"card wide\">
          <div class=\"card-title\">Logs</div>
          <p class=\"muted\">Basic log file listing. Full tail/viewer arrives in a later debug plugin.</p>
          <ul>{''.join(files) or '<li>No log files yet.</li>'}</ul>
        </div>
        """


    def _face_service(self):
        return self.context.services.services.get("face")

    def _render_face_page(self) -> str:
        face = self._face_service()
        if face is None:
            return '<div class="card wide bad"><div class="card-title">Face service</div><p>Face service is not available.</p></div>'
        status = face.status_payload()
        active_pack = html.escape(str(status.get("active_pack")))
        state = html.escape(str(status.get("state")))
        preview = f'/api/core/face/preview.svg?pack={active_pack}&state={state}'
        screen = status.get("screen") or {}
        screen_line = html.escape(
            f"configured={screen.get('configured_enabled')} running={screen.get('running')} "
            f"{screen.get('width')}x{screen.get('height')} fullscreen={screen.get('fullscreen')} "
            f"driver={screen.get('video_driver') or screen.get('requested_video_driver') or 'unknown'} "
            f"skip={screen.get('skip_reason') or ''}"
        )
        screen_error = html.escape(str(screen.get("last_error") or ""))
        screen_attempts = html.escape(str(screen.get("attempts") or []))

        state_buttons = []
        for face_state in status.get("states", []):
            safe_state = html.escape(str(face_state))
            state_buttons.append(
                f'<button class="norm-btn" data-face-state="{safe_state}">{safe_state}</button>'
            )

        pack_cards = []
        for pack in status.get("packs", []):
            pack_id = html.escape(str(pack.get("id")))
            pack_name = html.escape(str(pack.get("name")))
            pack_desc = html.escape(str(pack.get("description")))
            renderer = html.escape(str(pack.get("renderer")))
            active_class = " active-face-pack" if pack_id == active_pack else ""
            pack_cards.append(
                f'''<div class="card{active_class}">
                    <div class="card-title">{pack_name}</div>
                    <p><code>{pack_id}</code></p>
                    <p class="muted">{pack_desc}</p>
                    <p><b>Renderer:</b> {renderer}</p>
                    <button class="norm-btn" data-face-pack="{pack_id}">Activate</button>
                </div>'''
            )

        errors = status.get("errors") or []
        error_html = ""
        if errors:
            error_html = '<div class="card wide bad"><div class="card-title">Face pack errors</div><ul>' + "".join(
                f"<li>{html.escape(str(err))}</li>" for err in errors
            ) + "</ul></div>"

        return f'''
        <div class="grid face-grid">
          <div class="card wide">
            <div class="card-title">Face core</div>
            <p><b>Active pack:</b> <code id="active-pack">{active_pack}</code></p>
            <p><b>Current state:</b> <code id="active-state">{state}</code></p>
            <p><b>Screen:</b> <code id="screen-status">{screen_line}</code></p>
            <p><b>Screen error:</b> <code>{screen_error or 'none'}</code></p>
            <p><b>Driver attempts:</b> <code>{screen_attempts}</code></p>
            <p><a href="/api/core/face/screen/diagnostics">Screen diagnostics JSON</a></p>
            <p class="muted">Pre3.5 hotfix3 keeps SVG previews and makes the Pygame display backend configurable. If the screen is enabled, it follows the same active pack and state.</p>
          </div>
          <div class="card wide face-preview-card">
            <div class="card-title">Preview</div>
            <img id="face-preview" class="face-preview" src="{preview}" alt="N.O.R.M. face preview">
          </div>
          <div class="card wide">
            <div class="card-title">State test buttons</div>
            <div class="button-row">{''.join(state_buttons)}</div>
          </div>
          <div class="card wide">
            <div class="card-title">Face packs</div>
            <div class="grid">{''.join(pack_cards)}</div>
          </div>
          {error_html}
        </div>
        <script src="/static/face.js"></script>
        '''

    def _render_plugin_landing(self, record) -> str:
        return f"""
        <div class=\"card wide\">
          <div class=\"card-title\">{html.escape(record.manifest.get('name', record.plugin_id))}</div>
          <p>{html.escape(record.manifest.get('description', 'Plugin route is mounted.'))}</p>
          <p><b>Status:</b> {html.escape(record.status)}</p>
          <p><b>Plugin ID:</b> <code>{html.escape(record.plugin_id)}</code></p>
          <p><b>Route:</b> <code>{html.escape(record.webui_route or '')}</code></p>
          <p><a href=\"/api/plugins/{html.escape(record.plugin_id)}/health\">View plugin health JSON</a></p>
        </div>
        """

    async def _plugin_statuses(self) -> dict[str, Any]:
        plugin_manager = self.context.services.services.get("plugin_manager")
        if plugin_manager is None:
            return {}
        health = await plugin_manager.health()
        return health.details

    def _get_plugin_record(self, plugin_id: str):
        plugin_manager = self.context.services.services.get("plugin_manager")
        if plugin_manager is None:
            return None
        return plugin_manager.records.get(plugin_id)

    async def _plugin_health(self, record) -> dict[str, Any]:
        payload = {
            "ok": record.status in {"running", "loaded", "disabled"} and not record.error,
            "id": record.plugin_id,
            "enabled": record.enabled,
            "status": record.status,
            "route": record.webui_route,
            "permissions": record.permissions,
            "error": record.error,
        }
        if record.instance and hasattr(record.instance, "health"):
            try:
                result = record.instance.health()
                if inspect.isawaitable(result):
                    result = await result
                payload["plugin_health"] = result
            except Exception as exc:  # noqa: BLE001
                payload["ok"] = False
                payload["plugin_health"] = {"ok": False, "error": str(exc)}
        return payload

    def _event_to_dict(self, event) -> dict[str, Any]:
        return {
            "type": getattr(event, "type", None),
            "source": getattr(event, "source", None),
            "timestamp": getattr(event, "timestamp", None),
            "payload": getattr(event, "payload", {}),
        }

    async def health(self) -> ServiceHealth:
        base_details = {
            "routes": self.bound_routes,
            "enabled": bool(self.context.config.get("webui.enabled", True)),
            "host": self.context.config.get("webui.host", "0.0.0.0"),
            "port": self.context.config.get("webui.port", 8090),
        }
        if self.import_error:
            return ServiceHealth(
                ok=False,
                status="dependency_missing",
                details={**base_details, "error": self.import_error},
            )
        details = {
            "routes": self.bound_routes,
            "enabled": bool(self.context.config.get("webui.enabled", True)),
            "host": self.context.config.get("webui.host", "0.0.0.0"),
            "port": self.context.config.get("webui.port", 8090),
        }
        return ServiceHealth(ok=True, status="running" if self.started else "stopped", details=details)
