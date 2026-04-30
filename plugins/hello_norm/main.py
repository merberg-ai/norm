from __future__ import annotations

import html


class Plugin:
    def setup(self, context, record):
        self.context = context
        self.record = record
        self.greeting = record.config.get("greeting", "Hello from hello_norm")
        self.web_message = record.config.get("web_message", "Hello from the plugin web route.")
        self.started = False
        context.logger.info("[%s] setup complete", record.plugin_id)

    async def start(self):
        self.started = True
        self.context.logger.info("[%s] %s", self.record.plugin_id, self.greeting)
        if self.record.config.get("emit_ready_event", True):
            await self.context.events.publish(
                "hello_norm.ready",
                {"greeting": self.greeting, "route": self.record.webui_route},
                source=self.record.plugin_id,
            )

    async def stop(self):
        self.started = False
        self.context.logger.info("[%s] stopped", self.record.plugin_id)

    async def health(self):
        return {
            "ok": True,
            "started": self.started,
            "message": self.greeting,
            "route": self.record.webui_route,
        }

    def api_status(self):
        return {
            "plugin": self.record.plugin_id,
            "web_message": self.web_message,
            "containment": "stable",
        }

    def render_web_page(self):
        title = html.escape(self.record.manifest.get("name", self.record.plugin_id))
        message = html.escape(self.web_message)
        greeting = html.escape(self.greeting)
        route = html.escape(self.record.webui_route or "")
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
      <div><div class=\"kicker\">Plugin route test</div><h1>{title}</h1></div>
      <div class=\"status-pill\">contained</div>
    </header>
    <nav class=\"nav\"><a href=\"/\">Dashboard</a><a href=\"/plugins\">Plugins</a><a href=\"/events\">Events</a></nav>
    <section class=\"content\">
      <div class=\"card wide\">
        <div class=\"card-title\">Plugin page mounted at <code>{route}</code></div>
        <p>{message}</p>
        <p class=\"muted\">{greeting}</p>
        <p><a href=\"/api/plugins/{html.escape(self.record.plugin_id)}/status\">View plugin status JSON</a></p>
      </div>
    </section>
  </main>
</body>
</html>"""

    def get_webui_routes(self):
        return [
            {
                "path": self.record.webui_route,
                "label": self.record.manifest.get("webui", {}).get("label", "Hello"),
                "nav_enabled": True,
            }
        ]

    def get_tools(self):
        return []
