from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from .ai_provider import AiProviderClient, AiProviderConfig
from .utils import format_duration, local_day_bounds, parse_dt, safe_filename, seconds_between, to_iso, utc_now


class TaskService:
    def __init__(self, db):
        self.db = db
        self.recover_interrupted_sessions()

    def create_task(self, title: str, description: str = "", due_at: str | None = None, project: str = "", tags: str = "", x: float | None = None, y: float | None = None) -> str:
        title = title.strip()
        if not title:
            raise ValueError("Task title is required.")
        now = to_iso(utc_now())
        project_id = self._ensure_project(project.strip()) if project.strip() else None
        task_id = uuid4().hex
        self.db.execute(
            """
            INSERT INTO tasks(id, project_id, title, description, status, priority, due_at, created_at, updated_at, note_x, note_y)
            VALUES (?, ?, ?, ?, 'todo', 0, ?, ?, ?, ?, ?)
            """,
            (task_id, project_id, title, description.strip() or None, due_at, now, now, x, y),
        )
        self._set_tags("task", task_id, tags)
        self._timeline("task_created", task_id, {"title": title})
        return task_id

    def update_task(self, task_id: str, title: str, description: str = "", due_at: str | None = None, project: str = "", tags: str = "") -> None:
        if not self.get_task(task_id):
            raise ValueError("Task not found.")
        title = title.strip()
        if not title:
            raise ValueError("Task title is required.")
        project_id = self._ensure_project(project.strip()) if project.strip() else None
        now = to_iso(utc_now())
        self.db.execute(
            "UPDATE tasks SET project_id = ?, title = ?, description = ?, due_at = ?, updated_at = ? WHERE id = ?",
            (project_id, title, description.strip() or None, due_at, now, task_id),
        )
        self._set_tags("task", task_id, tags, replace=True)
        self._timeline("task_updated", task_id, {"title": title})

    def delete_task(self, task_id: str) -> None:
        self.db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def list_tasks(self, include_archived: bool = False) -> list[dict]:
        where = "" if include_archived else "WHERE t.status != 'archived'"
        rows = self.db.query_all(
            f"""
            SELECT t.*, p.name AS project_name
            FROM tasks t LEFT JOIN projects p ON p.id = t.project_id
            {where}
            ORDER BY CASE t.status WHEN 'in_progress' THEN 0 WHEN 'paused' THEN 1 WHEN 'todo' THEN 2 WHEN 'completed' THEN 3 ELSE 4 END, t.updated_at DESC
            """
        )
        return [self._task_dict(row) for row in rows]

    def get_task(self, task_id: str) -> dict | None:
        row = self.db.query_one(
            """
            SELECT t.*, p.name AS project_name
            FROM tasks t LEFT JOIN projects p ON p.id = t.project_id
            WHERE t.id = ?
            """,
            (task_id,),
        )
        return self._task_dict(row) if row else None

    def start_task(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if not task:
            raise ValueError("Task not found.")
        if task["status"] == "completed":
            raise ValueError("Completed tasks cannot be started.")
        active = self.current_active_task_id()
        if active and active != task_id:
            self.pause_task(active, "switched_task")
        now = to_iso(utc_now())
        if not task["started_at"]:
            self.db.execute("UPDATE tasks SET started_at = ? WHERE id = ?", (now, task_id))
        if not self.open_session(task_id):
            self.db.execute("INSERT INTO task_sessions(id, task_id, started_at, created_at) VALUES (?, ?, ?, ?)", (uuid4().hex, task_id, now, now))
        self.db.execute("UPDATE tasks SET status = 'in_progress', updated_at = ? WHERE id = ?", (now, task_id))
        self._timeline("task_started", task_id, {})

    def pause_task(self, task_id: str, reason: str = "paused") -> None:
        self._close_open_session(task_id, reason)
        now = to_iso(utc_now())
        self.db.execute("UPDATE tasks SET status = 'paused', updated_at = ? WHERE id = ? AND status != 'completed'", (now, task_id))
        self._timeline("task_paused", task_id, {"reason": reason})

    def complete_task(self, task_id: str) -> None:
        self._close_open_session(task_id, "completed")
        now = to_iso(utc_now())
        self.db.execute("UPDATE tasks SET status = 'completed', completed_at = ?, updated_at = ? WHERE id = ?", (now, now, task_id))
        self._timeline("task_completed", task_id, {})

    def archive_task(self, task_id: str) -> None:
        now = to_iso(utc_now())
        self.db.execute("UPDATE tasks SET status = 'archived', archived_at = ?, updated_at = ? WHERE id = ?", (now, now, task_id))
        self._timeline("task_archived", task_id, {})

    def add_progress(self, task_id: str, done: str = "", blocker: str = "", next_step: str = "", source_process_name: str | None = None, source_window_title: str | None = None, is_private_context: bool = False) -> str:
        if not self.get_task(task_id):
            raise ValueError("Task not found.")
        now = to_iso(utc_now())
        session = self.open_session(task_id)
        progress_id = uuid4().hex
        self.db.execute(
            """
            INSERT INTO task_progress(id, task_id, session_id, occurred_at, done_text, blocker_text, next_text, source_process_name, source_window_title, is_private_context, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (progress_id, task_id, session["id"] if session else None, now, done.strip() or None, blocker.strip() or None, next_step.strip() or None, source_process_name, None if is_private_context else source_window_title, int(is_private_context), now, now),
        )
        self._timeline("progress_added", task_id, {"done": done.strip(), "blocker": blocker.strip(), "next": next_step.strip()}, progress_id)
        return progress_id

    def progress_for_task(self, task_id: str) -> list[dict]:
        rows = self.db.query_all("SELECT * FROM task_progress WHERE task_id = ? ORDER BY occurred_at DESC", (task_id,))
        return [dict(row) for row in rows]

    def current_active_task_id(self) -> str | None:
        row = self.db.query_one("SELECT id FROM tasks WHERE status = 'in_progress' ORDER BY updated_at DESC LIMIT 1")
        return row["id"] if row else None

    def open_session(self, task_id: str) -> dict | None:
        row = self.db.query_one("SELECT * FROM task_sessions WHERE task_id = ? AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1", (task_id,))
        return dict(row) if row else None

    def recover_interrupted_sessions(self) -> None:
        now = to_iso(utc_now())
        for row in self.db.query_all("SELECT * FROM task_sessions WHERE ended_at IS NULL"):
            self.db.execute("UPDATE task_sessions SET ended_at = ?, duration_seconds = ?, ended_reason = 'interrupted' WHERE id = ?", (now, seconds_between(row["started_at"], now), row["id"]))
            self.db.execute("UPDATE tasks SET status = 'paused', updated_at = ? WHERE id = ? AND status = 'in_progress'", (now, row["task_id"]))

    def save_note_position(self, task_id: str, x: float, y: float, width: float | None = None, height: float | None = None) -> None:
        self.db.execute("UPDATE tasks SET note_x = ?, note_y = ?, note_width = COALESCE(?, note_width), note_height = COALESCE(?, note_height), updated_at = ? WHERE id = ?", (x, y, width, height, to_iso(utc_now()), task_id))

    def set_note_visibility(self, task_id: str, visible: bool) -> None:
        self.db.execute("UPDATE tasks SET note_visible = ?, updated_at = ? WHERE id = ?", (int(visible), to_iso(utc_now()), task_id))

    def task_total_seconds(self, task_id: str) -> int:
        total = int(self.db.scalar("SELECT COALESCE(SUM(duration_seconds), 0) FROM task_sessions WHERE task_id = ?", (task_id,)) or 0)
        open_row = self.open_session(task_id)
        return total + (seconds_between(open_row["started_at"]) if open_row else 0)

    def task_today_seconds(self, task_id: str, target: date | None = None) -> int:
        start, end = local_day_bounds(target)
        rows = self.db.query_all("SELECT started_at, ended_at FROM task_sessions WHERE task_id = ? AND started_at < ? AND COALESCE(ended_at, ?) >= ?", (task_id, to_iso(end), to_iso(utc_now()), to_iso(start)))
        total = 0
        for row in rows:
            session_start = parse_dt(row["started_at"]) or start
            session_end = parse_dt(row["ended_at"]) or utc_now()
            total += max(0, int((min(session_end, end) - max(session_start, start)).total_seconds()))
        return total

    def tags_for_entity(self, entity_type: str, entity_id: str) -> list[str]:
        rows = self.db.query_all("SELECT tags.name FROM tags JOIN entity_tags ON entity_tags.tag_id = tags.id WHERE entity_tags.entity_type = ? AND entity_tags.entity_id = ? ORDER BY tags.name", (entity_type, entity_id))
        return [row["name"] for row in rows]

    def _close_open_session(self, task_id: str, reason: str) -> None:
        row = self.open_session(task_id)
        if row:
            now = to_iso(utc_now())
            self.db.execute("UPDATE task_sessions SET ended_at = ?, duration_seconds = ?, ended_reason = ? WHERE id = ?", (now, seconds_between(row["started_at"], now), reason, row["id"]))

    def _ensure_project(self, name: str) -> str:
        row = self.db.query_one("SELECT id FROM projects WHERE name = ?", (name,))
        if row:
            return row["id"]
        project_id = uuid4().hex
        now = to_iso(utc_now())
        self.db.execute("INSERT INTO projects(id, name, created_at, updated_at) VALUES (?, ?, ?, ?)", (project_id, name, now, now))
        return project_id

    def _set_tags(self, entity_type: str, entity_id: str, tags: str, replace: bool = False) -> None:
        if replace:
            self.db.execute("DELETE FROM entity_tags WHERE entity_type = ? AND entity_id = ?", (entity_type, entity_id))
        for name in [item.strip() for item in tags.replace("，", ",").split(",") if item.strip()]:
            tag_id = self._ensure_tag(name)
            self.db.execute("INSERT OR IGNORE INTO entity_tags(id, entity_type, entity_id, tag_id, created_at) VALUES (?, ?, ?, ?, ?)", (uuid4().hex, entity_type, entity_id, tag_id, to_iso(utc_now())))

    def _ensure_tag(self, name: str) -> str:
        row = self.db.query_one("SELECT id FROM tags WHERE name = ?", (name,))
        if row:
            return row["id"]
        tag_id = uuid4().hex
        self.db.execute("INSERT INTO tags(id, name, created_at) VALUES (?, ?, ?)", (tag_id, name, to_iso(utc_now())))
        return tag_id

    def _timeline(self, event_type: str, task_id: str | None, payload: dict, progress_id: str | None = None) -> None:
        now = to_iso(utc_now())
        self.db.execute("INSERT INTO timeline_events(id, occurred_at, event_type, task_id, progress_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (uuid4().hex, now, event_type, task_id, progress_id, json.dumps(payload), now))

    def _task_dict(self, row) -> dict:
        data = dict(row)
        data["total_seconds"] = self.task_total_seconds(data["id"])
        data["today_seconds"] = self.task_today_seconds(data["id"])
        start, end = local_day_bounds()
        data["progress_count_today"] = int(self.db.scalar("SELECT COUNT(*) FROM task_progress WHERE task_id = ? AND occurred_at >= ? AND occurred_at < ?", (data["id"], to_iso(start), to_iso(end))) or 0)
        data["tags"] = self.tags_for_entity("task", data["id"])
        return data


class StatsService:
    def __init__(self, db, task_service: TaskService):
        self.db = db
        self.task_service = task_service

    def today(self, target: date | None = None) -> dict:
        start, end = local_day_bounds(target)
        return {
            "date": (target or datetime.now().date()).isoformat(),
            "active_seconds": self._activity_seconds(start, end, False),
            "idle_seconds": self._activity_seconds(start, end, True),
            "task_usage": self.task_usage(start, end),
            "app_usage": self.app_usage(start, end),
            "timeline": self.timeline(start, end),
            "progress": self.progress(start, end),
            "completed_tasks": [t for t in self.task_service.list_tasks(True) if t["status"] == "completed"],
            "continuing_tasks": [t for t in self.task_service.list_tasks(True) if t["status"] in {"todo", "paused", "in_progress"}],
        }

    def task_usage(self, start: datetime, end: datetime) -> list[dict]:
        rows = self.db.query_all("SELECT t.id, t.title, t.status, COALESCE(SUM(s.duration_seconds), 0) AS seconds FROM tasks t JOIN task_sessions s ON s.task_id = t.id WHERE s.started_at >= ? AND s.started_at < ? GROUP BY t.id, t.title, t.status ORDER BY seconds DESC", (to_iso(start), to_iso(end)))
        result = [dict(row) for row in rows]
        active_id = self.task_service.current_active_task_id()
        if active_id:
            for item in result:
                if item["id"] == active_id:
                    item["seconds"] = self.task_service.task_today_seconds(active_id)
                    break
            else:
                task = self.task_service.get_task(active_id)
                if task:
                    result.insert(0, {"id": active_id, "title": task["title"], "status": task["status"], "seconds": task["today_seconds"]})
        return result

    def app_usage(self, start: datetime, end: datetime) -> list[dict]:
        rows = self.db.query_all("SELECT CASE WHEN is_private = 1 THEN 'Hidden app' ELSE process_name END AS process_name, SUM(duration_seconds) AS seconds, COUNT(*) AS switch_count, MAX(is_private) AS is_private FROM activity_spans WHERE started_at >= ? AND started_at < ? AND is_idle = 0 GROUP BY CASE WHEN is_private = 1 THEN 'Hidden app' ELSE process_name END ORDER BY seconds DESC", (to_iso(start), to_iso(end)))
        return [dict(row) for row in rows]

    def timeline(self, start: datetime, end: datetime, limit: int = 200) -> list[dict]:
        rows = self.db.query_all("SELECT a.*, t.title AS task_title FROM activity_spans a LEFT JOIN tasks t ON t.id = a.task_id WHERE a.started_at >= ? AND a.started_at < ? ORDER BY a.started_at DESC LIMIT ?", (to_iso(start), to_iso(end), limit))
        return [dict(row) for row in rows]

    def progress(self, start: datetime, end: datetime, limit: int = 100) -> list[dict]:
        rows = self.db.query_all("SELECT p.*, t.title AS task_title FROM task_progress p JOIN tasks t ON t.id = p.task_id WHERE p.occurred_at >= ? AND p.occurred_at < ? ORDER BY p.occurred_at DESC LIMIT ?", (to_iso(start), to_iso(end), limit))
        return [dict(row) for row in rows]

    def delete_day_activity(self, target: date) -> None:
        start, end = local_day_bounds(target)
        self.db.execute("DELETE FROM activity_spans WHERE started_at >= ? AND started_at < ?", (to_iso(start), to_iso(end)))

    def delete_task_records(self, task_id: str) -> None:
        for table in ["activity_spans", "task_progress", "task_sessions", "ai_summaries", "knowledge_items"]:
            self.db.execute(f"DELETE FROM {table} WHERE task_id = ?", (task_id,))

    def _activity_seconds(self, start: datetime, end: datetime, idle: bool) -> int:
        return int(self.db.scalar("SELECT COALESCE(SUM(duration_seconds), 0) FROM activity_spans WHERE started_at >= ? AND started_at < ? AND is_idle = ?", (to_iso(start), to_iso(end), int(idle))) or 0)


class AiSummaryService:
    PROMPT_VERSION = "taskora-summary-v1"

    def __init__(self, db, task_service: TaskService, stats_service: StatsService, settings):
        self.db = db
        self.task_service = task_service
        self.stats_service = stats_service
        self.settings = settings

    def daily_input(self, target: date | None = None) -> dict:
        data = self.stats_service.today(target)
        return {
            "date": data["date"],
            "timezone": datetime.now().astimezone().tzname(),
            "tasks": [{"title": item["title"], "status": item["status"], "todayDurationMinutes": round(item["today_seconds"] / 60), "progressCount": item["progress_count_today"]} for item in self.task_service.list_tasks(True) if item["today_seconds"] or item["progress_count_today"] or item["status"] == "completed"],
            "appUsage": [{"app": item["process_name"], "minutes": round(item["seconds"] / 60), "switchCount": item["switch_count"], "private": bool(item["is_private"])} for item in data["app_usage"]],
            "progress": [{"time": self._local_time(item["occurred_at"]), "task": item["task_title"], "done": item["done_text"], "blocker": item["blocker_text"], "next": item["next_text"]} for item in data["progress"]],
            "privacyNotes": ["Private apps and hidden window titles are excluded from AI input."],
        }

    def task_input(self, task_id: str) -> dict:
        task = self.task_service.get_task(task_id)
        if not task:
            raise ValueError("Task not found.")
        sessions = self.db.query_all("SELECT started_at, ended_at, duration_seconds, ended_reason FROM task_sessions WHERE task_id = ? ORDER BY started_at ASC", (task_id,))
        progress = self.task_service.progress_for_task(task_id)
        activity = self.db.query_all("SELECT started_at, ended_at, duration_seconds, process_name, window_title, is_private FROM activity_spans WHERE task_id = ? ORDER BY started_at ASC LIMIT 100", (task_id,))
        return {
            "task": {"title": task["title"], "description": task["description"], "status": task["status"], "createdAt": task["created_at"], "completedAt": task["completed_at"], "totalMinutes": round(task["total_seconds"] / 60)},
            "sessions": [dict(row) for row in sessions],
            "progress": [{"time": item["occurred_at"], "done": item["done_text"], "blocker": item["blocker_text"], "next": item["next_text"]} for item in reversed(progress)],
            "activity": [{"start": self._local_time(row["started_at"]), "end": self._local_time(row["ended_at"]), "minutes": round(row["duration_seconds"] / 60), "app": "Hidden app" if row["is_private"] else row["process_name"], "windowTitle": None if row["is_private"] else row["window_title"]} for row in activity],
        }

    def generate_daily_summary(self, target: date | None = None) -> tuple[str, dict]:
        data = self.daily_input(target)
        external = self._generate_with_provider("daily", data)
        if external:
            return external, data
        tasks = data["tasks"]
        completed = [item for item in tasks if item["status"] == "completed"]
        continuing = [item for item in tasks if item["status"] != "completed"]
        apps = data["appUsage"][:5]
        lines = ["## Today Overview", "", self._overview_sentence(tasks, apps), "", "## Completed", "", *self._task_bullets(completed, "No completed tasks were recorded."), "", "## Main Progress", "", *self._progress_bullets(data["progress"]), "", "## To Continue", "", *self._task_bullets(continuing, "No continuing tasks were recorded."), "", "## Time Investment Notes", "", *self._app_bullets(apps), "", "## Tomorrow Suggestions", "", "- Pick one continuing task as the first focus block.", "- Add progress notes when a useful decision, blocker, or next step appears."]
        return "\n".join(lines).strip() + "\n", data

    def generate_task_summary(self, task_id: str) -> tuple[str, dict]:
        data = self.task_input(task_id)
        external = self._generate_with_provider("task", data)
        if external:
            return external, data
        task = data["task"]
        progress = data["progress"]
        lines = ["## Task Result", "", f"- Status: {task['status']}", f"- Total time: {format_duration(task['totalMinutes'] * 60)}", "", "## Process Timeline", "", *self._session_bullets(data["sessions"]), "", "## Key Progress", "", *self._progress_bullets(progress), "", "## Issues", "", *self._blocker_bullets(progress), "", "## Follow-up Suggestions", "", *self._next_bullets(progress), "", "## Archive Summary", "", self._archive_sentence(task, progress)]
        return "\n".join(lines).strip() + "\n", data

    def save_summary(self, summary_type: str, title: str, markdown: str, input_data: dict, task_id: str | None = None, scope_start: str | None = None, scope_end: str | None = None) -> str:
        now = to_iso(utc_now())
        snapshot = json.dumps(input_data, ensure_ascii=False, sort_keys=True)
        input_hash = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
        summary_id = uuid4().hex
        self.db.execute("""
            INSERT INTO ai_summaries(id, summary_type, task_id, scope_start, scope_end, title, content_markdown, prompt_version, model_provider, model_name, input_hash, input_snapshot_json, created_at, updated_at, user_accepted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (summary_id, summary_type, task_id, scope_start, scope_end, title, markdown, self.PROMPT_VERSION, self.settings.get("ai.provider", "LocalDraft"), self.settings.get("ai.model", "local-template") or "local-template", input_hash, snapshot if self.settings.get("ai.saveInputSnapshot", True) else None, now, now, now))
        return summary_id

    def _generate_with_provider(self, summary_type: str, data: dict) -> str | None:
        config = AiProviderConfig(
            provider=str(self.settings.get("ai.provider", "LocalDraft") or "LocalDraft"),
            endpoint=str(self.settings.get("ai.endpoint", "") or ""),
            model=str(self.settings.get("ai.model", "") or ""),
            api_key=str(self.settings.get("ai.apiKey", "") or ""),
            timeout_seconds=int(self.settings.get("ai.timeoutSeconds", 45) or 45),
        )
        client = AiProviderClient(config)
        if not client.is_configured():
            return None
        system, user = self._prompts(summary_type, data)
        return client.complete(system, user)

    @staticmethod
    def _prompts(summary_type: str, data: dict) -> tuple[str, str]:
        if summary_type == "daily":
            system = "You are Taskora's personal work review assistant. Only summarize provided local task records, progress notes, and app usage. Do not invent facts. Do not expose private or hidden data. Output Markdown with Today Overview, Completed, Main Progress, To Continue, Time Investment Notes, Tomorrow Suggestions."
            return system, "Generate a concise daily work summary from this Taskora JSON data:\n" + json.dumps(data, ensure_ascii=False, indent=2)
        system = "You are Taskora's task review assistant. Only summarize provided task sessions, progress notes, and visible app context. Do not invent facts. Output Markdown with Task Result, Process Timeline, Key Progress, Issues, Follow-up Suggestions, Archive Summary."
        return system, "Generate a task completion summary from this Taskora JSON data:\n" + json.dumps(data, ensure_ascii=False, indent=2)

    @staticmethod
    def _local_time(value: str | None) -> str:
        parsed = parse_dt(value)
        return parsed.astimezone().strftime("%H:%M") if parsed else ""

    @staticmethod
    def _overview_sentence(tasks: list[dict], apps: list[dict]) -> str:
        if not tasks and not apps:
            return "Records are not enough to judge today's work."
        app_text = ", ".join(f"{a['app']} {a['minutes']}m" for a in apps[:3]) or "no app usage"
        return f"Today has {len(tasks)} task records. Main recorded app time: {app_text}."

    @staticmethod
    def _task_bullets(tasks: list[dict], empty: str) -> list[str]:
        return [f"- {empty}"] if not tasks else [f"- {item['title']} ({item['status']}, {item.get('todayDurationMinutes', 0)}m today)" for item in tasks]

    @staticmethod
    def _progress_bullets(progress: list[dict]) -> list[str]:
        if not progress:
            return ["- No progress notes were recorded."]
        bullets = []
        for item in progress[:12]:
            parts = [part for part in [item.get("done"), item.get("blocker"), item.get("next")] if part]
            body = "; ".join(parts) if parts else "Progress note without details"
            prefix = f"{item.get('time', '')} " if item.get("time") else ""
            task = f"[{item.get('task')}] " if item.get("task") else ""
            bullets.append(f"- {prefix}{task}{body}")
        return bullets

    @staticmethod
    def _app_bullets(apps: list[dict]) -> list[str]:
        return ["- No app usage was recorded."] if not apps else [f"- {item['app']}: {item['minutes']}m, {item['switchCount']} switches" for item in apps]

    @staticmethod
    def _session_bullets(sessions: list[dict]) -> list[str]:
        return ["- No task sessions were recorded."] if not sessions else [f"- {AiSummaryService._local_time(item['started_at'])}-{AiSummaryService._local_time(item['ended_at'])}: {format_duration(item['duration_seconds'])} ({item['ended_reason'] or 'open'})" for item in sessions]

    @staticmethod
    def _blocker_bullets(progress: list[dict]) -> list[str]:
        blockers = [item.get("blocker") for item in progress if item.get("blocker")]
        return [f"- {item}" for item in blockers] or ["- No blockers were recorded."]

    @staticmethod
    def _next_bullets(progress: list[dict]) -> list[str]:
        next_steps = [item.get("next") for item in progress if item.get("next")]
        return [f"- {item}" for item in next_steps[-5:]] or ["- No explicit next steps were recorded."]

    @staticmethod
    def _archive_sentence(task: dict, progress: list[dict]) -> str:
        for item in reversed(progress):
            if item.get("done"):
                return f"{task['title']} reached status {task['status']}. Latest recorded progress: {item['done']}"
        return f"{task['title']} reached status {task['status']} with {task['totalMinutes']} recorded minutes."


class KnowledgeBaseService:
    def __init__(self, db, settings):
        self.db = db
        self.settings = settings

    def archive_summary(self, summary_id: str) -> str:
        summary = self.db.query_one("SELECT * FROM ai_summaries WHERE id = ?", (summary_id,))
        if not summary:
            raise ValueError("Summary not found.")
        source_type = "daily_summary" if summary["summary_type"] == "daily" else "task_summary"
        return self.create_item(source_type, summary_id, summary["title"], summary["content_markdown"], summary["task_id"], None, summary["created_at"])

    def archive_task_snapshot(self, task_id: str, title: str, body_markdown: str) -> str:
        return self.create_item("task", task_id, title, body_markdown, task_id, None, to_iso(utc_now()))

    def create_item(self, source_type: str, source_id: str | None, title: str, body_markdown: str, task_id: str | None = None, project_id: str | None = None, occurred_at: str | None = None) -> str:
        now = to_iso(utc_now())
        content_hash = hashlib.sha256(f"{title}\n{body_markdown}".encode("utf-8")).hexdigest()
        existing = self.db.query_one("SELECT id FROM knowledge_items WHERE content_hash = ?", (content_hash,))
        if existing:
            return existing["id"]
        item_id = uuid4().hex
        self.db.execute("""
            INSERT INTO knowledge_items(id, source_type, source_id, project_id, task_id, title, body_markdown, content_hash, occurred_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (item_id, source_type, source_id, project_id, task_id, title, body_markdown, content_hash, occurred_at, now, now))
        if self.settings.get("knowledgeBase.autoExportMarkdown", True):
            path = self.export_markdown(item_id)
            self.db.execute("UPDATE knowledge_items SET exported_markdown_path = ? WHERE id = ?", (str(path), item_id))
        return item_id

    def search(self, query: str, limit: int = 50) -> list[dict]:
        clean = query.strip()
        if not clean:
            rows = self.db.query_all("SELECT * FROM knowledge_items ORDER BY updated_at DESC LIMIT ?", (limit,))
        else:
            rows = self.db.query_all("SELECT k.*, snippet(knowledge_items_fts, 1, '[', ']', '...', 12) AS snippet FROM knowledge_items_fts JOIN knowledge_items k ON k.rowid = knowledge_items_fts.rowid WHERE knowledge_items_fts MATCH ? ORDER BY rank LIMIT ?", (self._fts_query(clean), limit))
        return [dict(row) for row in rows]

    def list_items(self, limit: int = 100) -> list[dict]:
        return self.search("", limit)

    def export_markdown(self, item_id: str) -> Path:
        item = self.db.query_one("SELECT * FROM knowledge_items WHERE id = ?", (item_id,))
        if not item:
            raise ValueError("Knowledge item not found.")
        base = Path(self.settings.get("knowledgeBase.directory", "Taskora Knowledge Base"))
        if not base.is_absolute():
            base = self.settings.path.parent / base
        occurred = parse_dt(item["occurred_at"]) or utc_now()
        local = occurred.astimezone()
        if item["source_type"] == "daily_summary":
            path = base / "Daily" / f"{local:%Y}" / f"{local:%m}" / f"{local:%Y-%m-%d}.md"
        elif item["source_type"] in {"task_summary", "task"}:
            path = base / "Tasks" / f"{local:%Y}" / f"{local:%m}" / f"{safe_filename(item['title'])}.md"
        else:
            path = base / "Exports" / f"{safe_filename(item['title'])}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._front_matter(item) + "\n" + item["body_markdown"].strip() + "\n", encoding="utf-8")
        return path

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = [token.replace('"', "") for token in query.split() if token.strip()]
        return " OR ".join(f'"{token}"' for token in tokens) if tokens else '""'

    @staticmethod
    def _front_matter(item) -> str:
        return "\n".join(["---", f"type: {item['source_type']}", f"source_id: {json.dumps(item['source_id'])}", f"task_id: {json.dumps(item['task_id'])}", f"occurred_at: {json.dumps(item['occurred_at'])}", "---", "", f"# {item['title']}"])
