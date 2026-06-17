from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

DEFAULT_SETTINGS: dict[str, Any] = {
    "onboarding": {"completed": False},
    "recording": {
        "enabled": True,
        "samplingIntervalSeconds": 2,
        "idleThresholdSeconds": 180,
        "topmostNotes": True,
    },
    "privacy": {
        "hidePrivateWindowTitles": True,
        "confirmBeforeAi": True,
        "privateProcesses": [
            "WeChat.exe",
            "QQ.exe",
            "Telegram.exe",
            "Signal.exe",
            "1Password.exe",
            "Bitwarden.exe",
            "KeePass.exe",
        ],
        "excludedProcesses": ["LastPass.exe"],
        "privateTitleKeywords": ["password", "private browsing", "incognito", "bank", "payment"],
    },
    "ai": {
        "provider": "LocalDraft",
        "endpoint": "",
        "model": "local-template",
        "apiKey": "",
        "timeoutSeconds": 45,
        "saveInputSnapshot": True,
    },
    "knowledgeBase": {
        "directory": "Taskora Knowledge Base",
        "autoExportMarkdown": True,
    },
}


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self.load()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            data = copy.deepcopy(DEFAULT_SETTINGS)
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return data
        try:
            existing = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
        data = deep_merge(DEFAULT_SETTINGS, existing)
        if data != existing:
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted_key: str, value: Any) -> None:
        node = self.data
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self.save()

    def list_value(self, dotted_key: str) -> list[str]:
        value = self.get(dotted_key, [])
        if isinstance(value, str):
            return [line.strip() for line in value.splitlines() if line.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []
