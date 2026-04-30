from __future__ import annotations


class Plugin:
    def setup(self, context, record):
        self.context = context
        self.record = record
        self.greeting = record.config.get("greeting", "Hello from hello_norm")
        context.logger.info("[%s] setup complete", record.plugin_id)

    async def start(self):
        self.context.logger.info("[%s] %s", self.record.plugin_id, self.greeting)
        if self.record.config.get("emit_ready_event", True):
            await self.context.events.publish(
                "hello_norm.ready",
                {"greeting": self.greeting},
                source=self.record.plugin_id,
            )

    async def stop(self):
        self.context.logger.info("[%s] stopped", self.record.plugin_id)

    async def health(self):
        return {
            "ok": True,
            "message": self.greeting,
        }

    def get_webui_routes(self):
        # Pre2 will actually mount plugin routes. Pre1 records this capability only.
        return []

    def get_tools(self):
        return []
