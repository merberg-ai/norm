from __future__ import annotations

import asyncio
import html
import inspect
from pathlib import Path
from typing import Any

from core.service import BaseService, ServiceHealth


class WebUIService(BaseService):
    """FastAPI web cockpit shell for beta2-pre2.

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
            from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
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
            }

        @app.get("/api/core/events", response_class=JSONResponse)
        async def api_events():
            return {"events": [self._event_to_dict(event) for event in self.context.events.history()]}

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

        # Configurable plugin landing routes, e.g. /hello or later /servos.
        plugin_manager = self.context.services.services.get("plugin_manager")
        if plugin_manager is not None:
            for record in plugin_manager.records.values():
                if not record.enabled or not record.webui_route:
                    continue
                self._mount_plugin_route(app, record, HTMLResponse, PlainTextResponse)

        return app

    def _mount_plugin_route(self, app, record, HTMLResponse, PlainTextResponse) -> None:
        route = record.webui_route
        if not route:
            return
        self.bound_routes.append(route)

        async def plugin_page(record=record):
            try:
                if record.instance and hasattr(record.instance, "render_web_page"):
                    result = record.instance.render_web_page()
                    if inspect.isawaitable(result):
                        result = await result
                    return HTMLResponse(str(result))
                body = self._render_plugin_landing(record)
                return HTMLResponse(self._page(record.manifest.get("name", record.plugin_id), body))
            except Exception as exc:  # noqa: BLE001
                self.context.logger.exception("Plugin route failed: %s", record.plugin_id)
                return PlainTextResponse(f"Plugin route failed: {exc}", status_code=500)

        app.add_api_route(route, plugin_page, methods=["GET"], response_class=HTMLResponse)

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
      <div class=\"status-pill\">pre2 web shell</div>
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
        return f"""
        <div class=\"grid\">
          <div class=\"card wide\"><div class=\"card-title\">config/norm.yaml</div><pre>{norm}</pre></div>
          <div class=\"card wide\"><div class=\"card-title\">config/plugins.yaml</div><pre>{plugins}</pre></div>
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
