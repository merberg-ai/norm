from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class OllamaResponse:
    ok: bool
    text: str = ""
    model: str | None = None
    raw: dict[str, Any] | None = None
    error: str | None = None


class OllamaClient:
    """Small stdlib-only Ollama client for the beta2 brain service."""

    def __init__(self, host: str, timeout: int = 120):
        self.host = self._normalize_host(host)
        self.timeout = int(timeout)

    @staticmethod
    def _normalize_host(host: str) -> str:
        host = str(host or "http://127.0.0.1:11434").strip()
        if not host.startswith(("http://", "https://")):
            host = "http://" + host
        return host.rstrip("/")

    def _post_json(self, path: str, payload: dict[str, Any], *, timeout: int | None = None) -> dict[str, Any]:
        url = f"{self.host}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=timeout or self.timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

    def _get_json(self, path: str, *, timeout: int | None = None) -> dict[str, Any]:
        url = f"{self.host}{path}"
        req = Request(url, headers={"Accept": "application/json"}, method="GET")
        with urlopen(req, timeout=timeout or self.timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

    def tags(self, *, timeout: int = 8) -> dict[str, Any]:
        try:
            data = self._get_json("/api/tags", timeout=timeout)
            models = []
            for item in data.get("models", []) or []:
                if isinstance(item, dict) and item.get("name"):
                    models.append({
                        "name": item.get("name"),
                        "modified_at": item.get("modified_at"),
                        "size": item.get("size"),
                        "details": item.get("details") or {},
                    })
            return {"ok": True, "host": self.host, "models": models}
        except HTTPError as exc:
            return {"ok": False, "host": self.host, "error": f"HTTP {exc.code}: {exc.reason}"}
        except URLError as exc:
            return {"ok": False, "host": self.host, "error": str(exc.reason)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "host": self.host, "error": str(exc)}

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        system: str = "",
        options: dict[str, Any] | None = None,
        keep_alive: str | None = None,
    ) -> OllamaResponse:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        if options:
            payload["options"] = options
        if keep_alive:
            payload["keep_alive"] = keep_alive
        try:
            data = self._post_json("/api/generate", payload, timeout=self.timeout)
            if "error" in data:
                return OllamaResponse(ok=False, model=model, raw=data, error=str(data.get("error")))
            return OllamaResponse(ok=True, text=str(data.get("response") or ""), model=str(data.get("model") or model), raw=data)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else exc.reason
            return OllamaResponse(ok=False, model=model, error=f"HTTP {exc.code}: {detail}")
        except URLError as exc:
            return OllamaResponse(ok=False, model=model, error=str(exc.reason))
        except Exception as exc:  # noqa: BLE001
            return OllamaResponse(ok=False, model=model, error=str(exc))
