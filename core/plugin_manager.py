from __future__ import annotations

import importlib.util
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core import yaml_compat as yaml

from core.config import SUPPORTED_CONFIG_VERSION, deep_merge
from core.service import BaseService, ServiceHealth

RESERVED_WEB_ROUTES = {
    "/",
    "/config",
    "/face",
    "/audio",
    "/brain",
    "/memory",
    "/people",
    "/plugins",
    "/logs",
    "/events",
    "/static",
}


class PluginError(RuntimeError):
    pass


@dataclass
class PluginRecord:
    plugin_id: str
    path: Path
    manifest: dict[str, Any]
    config: dict[str, Any]
    enabled: bool = True
    status: str = "discovered"
    instance: Any | None = None
    error: str | None = None
    webui_route: str | None = None
    permissions: list[str] = field(default_factory=list)


class PluginManagerService(BaseService):
    name = "plugin_manager"

    def __init__(self, context):
        super().__init__(context)
        self.records: dict[str, PluginRecord] = {}

    async def start(self) -> None:
        await super().start()
        await self.discover()
        if self.context.safe_mode:
            self.context.logger.warning("Safe mode enabled: plugin startup skipped")
            return
        await self.load_enabled_plugins()

    async def stop(self) -> None:
        for record in reversed(list(self.records.values())):
            if record.instance and hasattr(record.instance, "stop"):
                try:
                    result = record.instance.stop()
                    if inspect.isawaitable(result):
                        await result
                    record.status = "stopped"
                    await self.context.events.publish(
                        "plugin.stopped",
                        {"plugin_id": record.plugin_id},
                        source="plugin_manager",
                    )
                except Exception as exc:  # noqa: BLE001
                    record.status = "failed_stop"
                    record.error = str(exc)
                    self.context.logger.exception("Plugin stop failed: %s", record.plugin_id)
        await super().stop()

    async def discover(self) -> None:
        plugins_dir = self.context.paths.plugins_dir
        self.context.logger.info("Scanning plugins: %s", plugins_dir)
        for plugin_dir in sorted(p for p in plugins_dir.iterdir() if p.is_dir()):
            manifest_path = plugin_dir / "plugin.yaml"
            if not manifest_path.exists():
                continue
            try:
                record = self._read_plugin(plugin_dir)
                self.records[record.plugin_id] = record
                self.context.logger.info("Plugin discovered: %s", record.plugin_id)
                await self.context.events.publish(
                    "plugin.discovered",
                    {"plugin_id": record.plugin_id, "enabled": record.enabled},
                    source="plugin_manager",
                )
            except Exception as exc:  # noqa: BLE001
                self.context.logger.exception("Plugin discovery failed in %s: %s", plugin_dir, exc)

    def _read_plugin(self, plugin_dir: Path) -> PluginRecord:
        manifest = self._load_yaml(plugin_dir / "plugin.yaml")
        plugin_id = manifest.get("id")
        if not plugin_id or not isinstance(plugin_id, str):
            raise PluginError(f"Plugin at {plugin_dir} is missing string id in plugin.yaml")

        if manifest.get("manifest_version") != 1:
            raise PluginError(f"Plugin {plugin_id} has unsupported manifest_version")

        default_config = {}
        config_path = plugin_dir / "config.yaml"
        if config_path.exists():
            default_config = self._load_yaml(config_path)
            version = default_config.get("config_version")
            if version != SUPPORTED_CONFIG_VERSION:
                raise PluginError(
                    f"Plugin {plugin_id} config_version must be {SUPPORTED_CONFIG_VERSION}; got {version}"
                )

        overrides = self.context.config.plugin_overrides(plugin_id)
        enabled = bool(overrides.get("enabled", manifest.get("enabled", True)))
        config_overrides = overrides.get("config_overrides", {})
        merged_config = deep_merge(default_config, config_overrides if isinstance(config_overrides, dict) else {})

        manifest_webui = manifest.get("webui", {}) if isinstance(manifest.get("webui", {}), dict) else {}
        override_webui = overrides.get("webui", {}) if isinstance(overrides.get("webui", {}), dict) else {}
        webui = deep_merge(manifest_webui, override_webui)
        route = webui.get("route")
        if route:
            self._validate_route(plugin_id, route)

        permissions = manifest.get("permissions", [])
        if not isinstance(permissions, list):
            raise PluginError(f"Plugin {plugin_id} permissions must be a list")

        return PluginRecord(
            plugin_id=plugin_id,
            path=plugin_dir,
            manifest=manifest,
            config=merged_config,
            enabled=enabled,
            webui_route=route,
            permissions=[str(p) for p in permissions],
        )

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle.read()) or {}
        if not isinstance(data, dict):
            raise PluginError(f"YAML file must contain a mapping/object: {path}")
        return data

    def _validate_route(self, plugin_id: str, route: str) -> None:
        if not isinstance(route, str) or not route.startswith("/"):
            raise PluginError(f"Plugin {plugin_id} route must start with '/': {route!r}")
        if route in RESERVED_WEB_ROUTES or route.startswith("/api/core") or route.startswith("/api/plugins"):
            raise PluginError(f"Plugin {plugin_id} tried to use reserved route: {route}")
        for record in self.records.values():
            if record.webui_route == route:
                raise PluginError(
                    f"Plugin route conflict: {plugin_id} and {record.plugin_id} both want {route}"
                )

    async def load_enabled_plugins(self) -> None:
        for record in self.records.values():
            if not record.enabled:
                record.status = "disabled"
                self.context.logger.info("Plugin disabled: %s", record.plugin_id)
                continue
            await self._load_one(record)

    async def _load_one(self, record: PluginRecord) -> None:
        try:
            entrypoint = record.manifest.get("entrypoint", "main:Plugin")
            module_name, class_name = entrypoint.split(":", 1)
            module_path = record.path / f"{module_name}.py"
            if not module_path.exists():
                raise PluginError(f"Entrypoint module not found: {module_path}")

            spec = importlib.util.spec_from_file_location(
                f"norm_plugins.{record.plugin_id}.{module_name}",
                module_path,
            )
            if spec is None or spec.loader is None:
                raise PluginError(f"Unable to import plugin module: {module_path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            plugin_class = getattr(module, class_name)
            instance = plugin_class()
            record.instance = instance

            if hasattr(instance, "setup"):
                result = instance.setup(self.context, record)
                if inspect.isawaitable(result):
                    await result
            record.status = "loaded"
            await self.context.events.publish(
                "plugin.loaded",
                {"plugin_id": record.plugin_id},
                source="plugin_manager",
            )

            if hasattr(instance, "start"):
                result = instance.start()
                if inspect.isawaitable(result):
                    await result
            record.status = "running"
            await self.context.events.publish(
                "plugin.started",
                {"plugin_id": record.plugin_id},
                source="plugin_manager",
            )
            self.context.logger.info("Plugin started: %s", record.plugin_id)
        except Exception as exc:  # noqa: BLE001 - failed plugins must not kill N.O.R.M.
            record.status = "failed"
            record.error = str(exc)
            self.context.logger.exception("Plugin failed: %s", record.plugin_id)
            await self.context.events.publish(
                "plugin.failed",
                {"plugin_id": record.plugin_id, "error": str(exc)},
                source="plugin_manager",
            )

    async def health(self) -> ServiceHealth:
        details = {}
        ok = True
        for plugin_id, record in self.records.items():
            plugin_health: dict[str, Any] = {
                "enabled": record.enabled,
                "status": record.status,
                "route": record.webui_route,
                "permissions": record.permissions,
            }
            if record.error:
                plugin_health["error"] = record.error
                ok = False
            if record.instance and hasattr(record.instance, "health"):
                try:
                    result = record.instance.health()
                    if inspect.isawaitable(result):
                        result = await result
                    plugin_health["plugin_health"] = result
                except Exception as exc:  # noqa: BLE001
                    plugin_health["plugin_health"] = {"ok": False, "error": str(exc)}
                    ok = False
            details[plugin_id] = plugin_health
        return ServiceHealth(ok=ok, status="running" if self.started else "stopped", details=details)
