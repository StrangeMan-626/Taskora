from __future__ import annotations

import ctypes
import os
import re
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from .settings import SettingsStore
from .utils import normalize_process_name


@dataclass(frozen=True)
class ForegroundWindowSnapshot:
    process_id: int | None
    process_name: str
    window_title: str | None
    is_idle: bool = False


@dataclass(frozen=True)
class PrivacyDecision:
    should_record: bool
    process_name: str
    window_title: str | None
    is_private: bool
    capture_level: str


class ForegroundWindowSampler:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def __init__(self, idle_threshold_seconds: int = 180):
        self.idle_threshold_seconds = idle_threshold_seconds
        self.is_windows = os.name == "nt"
        if self.is_windows:
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    def capture(self) -> ForegroundWindowSnapshot:
        if not self.is_windows:
            return ForegroundWindowSnapshot(None, "Taskora", "Taskora", False)
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return ForegroundWindowSnapshot(None, "Unknown", None, self._is_idle())
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return ForegroundWindowSnapshot(
            process_id=int(pid.value) if pid.value else None,
            process_name=self._process_name(pid.value),
            window_title=self._window_title(hwnd),
            is_idle=self._is_idle(),
        )

    def _window_title(self, hwnd: int) -> str | None:
        length = self.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return None
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value.strip() or None

    def _process_name(self, pid: int) -> str:
        if not pid:
            return "Unknown"
        handle = self.kernel32.OpenProcess(self.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return f"pid_{pid}"
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            ok = self.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
            if ok:
                return Path(buffer.value).name or f"pid_{pid}"
        finally:
            self.kernel32.CloseHandle(handle)
        return f"pid_{pid}"

    def _is_idle(self) -> bool:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not self.user32.GetLastInputInfo(ctypes.byref(info)):
            return False
        idle_ms = self.kernel32.GetTickCount64() - info.dwTime
        return idle_ms >= self.idle_threshold_seconds * 1000


class PrivacyRuleMatcher:
    def __init__(self, settings: SettingsStore, db=None):
        self.settings = settings
        self.db = db

    def apply(self, snapshot: ForegroundWindowSnapshot) -> PrivacyDecision:
        process_name = snapshot.process_name or "Unknown"
        window_title = snapshot.window_title
        action = self._strongest_action(
            self._settings_action(process_name, window_title),
            self._database_action(process_name, window_title),
        )
        if action == "exclude":
            return PrivacyDecision(False, process_name, None, True, "excluded")
        if action == "mark_private":
            return PrivacyDecision(True, process_name, "[hidden]", True, "private")
        if action == "redact_title":
            return PrivacyDecision(True, process_name, "[hidden]", True, "app_only")
        return PrivacyDecision(True, process_name, window_title, False, "app_title")

    def _settings_action(self, process_name: str, title: str | None) -> str | None:
        process_norm = normalize_process_name(process_name)
        excluded = {normalize_process_name(item) for item in self.settings.list_value("privacy.excludedProcesses")}
        private = {normalize_process_name(item) for item in self.settings.list_value("privacy.privateProcesses")}
        if process_norm in excluded:
            return "exclude"
        if process_norm in private:
            return "mark_private"
        title_lower = (title or "").lower()
        for keyword in self.settings.list_value("privacy.privateTitleKeywords"):
            if keyword.lower() in title_lower:
                return "redact_title"
        return None

    def _database_action(self, process_name: str, title: str | None) -> str | None:
        if self.db is None:
            return None
        rows = self.db.query_all(
            "SELECT rule_type, pattern, match_type, action FROM privacy_rules WHERE enabled = 1"
        )
        for row in rows:
            value = process_name if row["rule_type"] == "process_name" else title or ""
            if self._matches(value, row["pattern"], row["match_type"]):
                return row["action"]
        return None

    @staticmethod
    def _matches(value: str, pattern: str, match_type: str) -> bool:
        if match_type == "exact":
            return value.lower() == pattern.lower()
        if match_type == "contains":
            return pattern.lower() in value.lower()
        if match_type == "regex":
            try:
                return re.search(pattern, value, re.IGNORECASE) is not None
            except re.error:
                return False
        return False

    @staticmethod
    def _strongest_action(left: str | None, right: str | None) -> str | None:
        rank = {None: 0, "redact_title": 1, "mark_private": 2, "exclude": 3}
        return left if rank[left] >= rank[right] else right


class ActivityRecorder:
    def __init__(self, db, settings: SettingsStore, task_service, sampler=None):
        self.db = db
        self.settings = settings
        self.task_service = task_service
        threshold = int(settings.get("recording.idleThresholdSeconds", 180))
        self.sampler = sampler or ForegroundWindowSampler(threshold)
        self.matcher = PrivacyRuleMatcher(settings, db)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._current: dict | None = None
        self._lock = threading.RLock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="TaskoraActivity", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self.flush_current()

    def sample_once(self) -> None:
        if not self.settings.get("recording.enabled", True):
            self.flush_current()
            return
        snapshot = self.sampler.capture()
        decision = self.matcher.apply(snapshot)
        if not decision.should_record:
            self.flush_current()
            return
        task_id = self.task_service.current_active_task_id()
        now = time.time()
        key = (
            decision.process_name,
            decision.window_title,
            bool(snapshot.is_idle),
            bool(decision.is_private),
            task_id,
            decision.capture_level,
        )
        with self._lock:
            if self._current and self._current["key"] == key:
                self._current["last_seen"] = now
                return
            self._flush_locked(now)
            self._current = {
                "key": key,
                "started": now,
                "last_seen": now,
                "process_id": snapshot.process_id,
                "process_name": decision.process_name,
                "window_title": decision.window_title,
                "is_idle": int(snapshot.is_idle),
                "is_private": int(decision.is_private),
                "capture_level": decision.capture_level,
                "task_id": task_id,
            }

    def flush_current(self) -> None:
        with self._lock:
            self._flush_locked(time.time())

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sample_once()
            except Exception:
                pass
            interval = max(1, int(self.settings.get("recording.samplingIntervalSeconds", 2)))
            self._stop.wait(interval)

    def _flush_locked(self, end_time: float) -> None:
        if not self._current:
            return
        from datetime import datetime, timezone
        from uuid import uuid4

        started = self._current["started"]
        duration = max(1, int(end_time - started))
        started_at = datetime.fromtimestamp(started, timezone.utc).isoformat()
        ended_at = datetime.fromtimestamp(max(end_time, started + 1), timezone.utc).isoformat()
        app_id = self._ensure_application(self._current["process_name"], self._current["is_private"])
        self.db.execute(
            """
            INSERT INTO activity_spans(
              id, application_id, task_id, started_at, ended_at, duration_seconds,
              process_id, process_name, window_title, normalized_window_title,
              is_idle, is_private, capture_level, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                app_id,
                self._current["task_id"],
                started_at,
                ended_at,
                duration,
                self._current["process_id"],
                self._current["process_name"],
                self._current["window_title"],
                (self._current["window_title"] or "").lower(),
                self._current["is_idle"],
                self._current["is_private"],
                self._current["capture_level"],
                ended_at,
            ),
        )
        self._current = None

    def _ensure_application(self, process_name: str, is_private: int) -> str:
        row = self.db.query_one(
            "SELECT id FROM applications WHERE process_name = ? AND executable_path_hash IS NULL",
            (process_name,),
        )
        if row:
            return row["id"]
        from datetime import timezone, datetime
        from uuid import uuid4

        now = datetime.now(timezone.utc).isoformat()
        app_id = uuid4().hex
        self.db.execute(
            """
            INSERT INTO applications(id, process_name, display_name, executable_path_hash, category, is_private, created_at, updated_at)
            VALUES (?, ?, ?, NULL, NULL, ?, ?, ?)
            """,
            (app_id, process_name, process_name, int(is_private), now, now),
        )
        return app_id
