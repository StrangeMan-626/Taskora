from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AiProviderConfig:
    provider: str
    endpoint: str
    model: str
    api_key: str = ""
    timeout_seconds: int = 45


class AiProviderError(RuntimeError):
    pass


class AiProviderClient:
    def __init__(self, config: AiProviderConfig):
        self.config = config

    def is_configured(self) -> bool:
        return bool(self.config.endpoint.strip() and self.config.model.strip() and self.config.provider.lower() != "localdraft")

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        provider = self.config.provider.lower().replace(" ", "")
        if provider in {"ollama", "localollama"}:
            return self._ollama(system_prompt, user_prompt)
        if provider in {"openai", "openaicompatible", "deepseek", "custom"}:
            return self._openai_compatible(system_prompt, user_prompt)
        raise AiProviderError(f"Unsupported AI provider: {self.config.provider}")

    def _openai_compatible(self, system_prompt: str, user_prompt: str) -> str:
        endpoint = self.config.endpoint.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint = endpoint + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        data = self._post_json(endpoint, payload)
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise AiProviderError("AI provider returned an unexpected response.") from exc

    def _ollama(self, system_prompt: str, user_prompt: str) -> str:
        endpoint = self.config.endpoint.rstrip("/")
        if not endpoint.endswith("/api/chat"):
            endpoint = endpoint + "/api/chat"
        payload = {
            "model": self.config.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        data = self._post_json(endpoint, payload)
        try:
            return data["message"]["content"].strip()
        except (KeyError, TypeError) as exc:
            raise AiProviderError("Ollama returned an unexpected response.") from exc

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise AiProviderError(f"AI provider HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AiProviderError(f"AI provider request failed: {exc}") from exc
