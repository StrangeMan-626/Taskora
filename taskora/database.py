from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .utils import to_iso, utc_now

SCHEMA_VERSION = 1


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.initialize()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self.transaction() as conn:
            return conn.execute(sql, tuple(params))

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> sqlite3.Cursor:
        with self.transaction() as conn:
            return conn.executemany(sql, seq)

    def query_all(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(sql, tuple(params)).fetchall())

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, tuple(params)).fetchone()

    def scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        row = self.query_one(sql, params)
        return None if row is None else row[0]

    def initialize(self) -> None:
        with self.transaction() as conn:
            conn.executescript(BASE_SCHEMA)
            current = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            if not current:
                conn.execute(
                    "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                    (SCHEMA_VERSION, "initial_schema", to_iso(utc_now())),
                )
            self._seed_privacy_rules(conn)

    @staticmethod
    def _seed_privacy_rules(conn: sqlite3.Connection) -> None:
        if conn.execute("SELECT COUNT(*) FROM privacy_rules").fetchone()[0]:
            return
        now = to_iso(utc_now())
        rules = [
            ("process_name", "WeChat", "contains", "mark_private"),
            ("process_name", "QQ", "contains", "mark_private"),
            ("process_name", "Telegram", "contains", "mark_private"),
            ("process_name", "Signal", "contains", "mark_private"),
            ("process_name", "1Password", "contains", "exclude"),
            ("process_name", "Bitwarden", "contains", "exclude"),
            ("process_name", "KeePass", "contains", "exclude"),
            ("window_title", "Incognito", "contains", "redact_title"),
            ("window_title", "Private Browsing", "contains", "redact_title"),
            ("window_title", "password", "contains", "redact_title"),
        ]
        for rule_type, pattern, match_type, action in rules:
            conn.execute(
                """
                INSERT INTO privacy_rules(id, rule_type, pattern, match_type, action, enabled, created_at, updated_at)
                VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, 1, ?, ?)
                """,
                (rule_type, pattern, match_type, action, now, now),
            )


BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  color TEXT NULL,
  description TEXT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  archived_at TEXT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  project_id TEXT NULL REFERENCES projects(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  description TEXT NULL,
  status TEXT NOT NULL CHECK (status IN ('todo', 'in_progress', 'paused', 'completed', 'archived')),
  priority INTEGER NOT NULL DEFAULT 0,
  due_at TEXT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  started_at TEXT NULL,
  completed_at TEXT NULL,
  archived_at TEXT NULL,
  note_x REAL NULL,
  note_y REAL NULL,
  note_width REAL NULL,
  note_height REAL NULL,
  note_collapsed INTEGER NOT NULL DEFAULT 0,
  note_visible INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due_at ON tasks(due_at);
CREATE INDEX IF NOT EXISTS idx_tasks_project_id ON tasks(project_id);

CREATE TABLE IF NOT EXISTS task_sessions (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  started_at TEXT NOT NULL,
  ended_at TEXT NULL,
  duration_seconds INTEGER NOT NULL DEFAULT 0,
  ended_reason TEXT NULL CHECK (ended_reason IN ('paused', 'completed', 'switched_task', 'interrupted', 'manual')),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_sessions_task_id ON task_sessions(task_id);
CREATE INDEX IF NOT EXISTS idx_task_sessions_started_at ON task_sessions(started_at);

CREATE TABLE IF NOT EXISTS applications (
  id TEXT PRIMARY KEY,
  process_name TEXT NOT NULL,
  display_name TEXT NULL,
  executable_path_hash TEXT NULL,
  category TEXT NULL,
  is_private INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(process_name, executable_path_hash)
);
CREATE INDEX IF NOT EXISTS idx_applications_process_name ON applications(process_name);

CREATE TABLE IF NOT EXISTS activity_spans (
  id TEXT PRIMARY KEY,
  application_id TEXT NULL REFERENCES applications(id) ON DELETE SET NULL,
  task_id TEXT NULL REFERENCES tasks(id) ON DELETE SET NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT NOT NULL,
  duration_seconds INTEGER NOT NULL,
  process_id INTEGER NULL,
  process_name TEXT NOT NULL,
  window_title TEXT NULL,
  normalized_window_title TEXT NULL,
  is_idle INTEGER NOT NULL DEFAULT 0,
  is_private INTEGER NOT NULL DEFAULT 0,
  capture_level TEXT NOT NULL DEFAULT 'app_title',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_spans_started_at ON activity_spans(started_at);
CREATE INDEX IF NOT EXISTS idx_activity_spans_task_id ON activity_spans(task_id);
CREATE INDEX IF NOT EXISTS idx_activity_spans_application_id ON activity_spans(application_id);
CREATE INDEX IF NOT EXISTS idx_activity_spans_private ON activity_spans(is_private);

CREATE TABLE IF NOT EXISTS task_progress (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  session_id TEXT NULL REFERENCES task_sessions(id) ON DELETE SET NULL,
  occurred_at TEXT NOT NULL,
  done_text TEXT NULL,
  blocker_text TEXT NULL,
  next_text TEXT NULL,
  source_application_id TEXT NULL REFERENCES applications(id) ON DELETE SET NULL,
  source_process_name TEXT NULL,
  source_window_title TEXT NULL,
  is_private_context INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_progress_task_id ON task_progress(task_id);
CREATE INDEX IF NOT EXISTS idx_task_progress_occurred_at ON task_progress(occurred_at);

CREATE TABLE IF NOT EXISTS timeline_events (
  id TEXT PRIMARY KEY,
  occurred_at TEXT NOT NULL,
  event_type TEXT NOT NULL,
  task_id TEXT NULL REFERENCES tasks(id) ON DELETE SET NULL,
  activity_span_id TEXT NULL REFERENCES activity_spans(id) ON DELETE SET NULL,
  progress_id TEXT NULL REFERENCES task_progress(id) ON DELETE SET NULL,
  payload_json TEXT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_timeline_events_occurred_at ON timeline_events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_timeline_events_task_id ON timeline_events(task_id);
CREATE INDEX IF NOT EXISTS idx_timeline_events_event_type ON timeline_events(event_type);

CREATE TABLE IF NOT EXISTS ai_summaries (
  id TEXT PRIMARY KEY,
  summary_type TEXT NOT NULL CHECK (summary_type IN ('daily', 'weekly', 'task', 'project', 'custom')),
  task_id TEXT NULL REFERENCES tasks(id) ON DELETE SET NULL,
  project_id TEXT NULL REFERENCES projects(id) ON DELETE SET NULL,
  scope_start TEXT NULL,
  scope_end TEXT NULL,
  title TEXT NOT NULL,
  content_markdown TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  model_provider TEXT NOT NULL,
  model_name TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  input_snapshot_json TEXT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  user_accepted_at TEXT NULL,
  archived_at TEXT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_summaries_type ON ai_summaries(summary_type);
CREATE INDEX IF NOT EXISTS idx_ai_summaries_task_id ON ai_summaries(task_id);
CREATE INDEX IF NOT EXISTS idx_ai_summaries_scope ON ai_summaries(scope_start, scope_end);

CREATE TABLE IF NOT EXISTS knowledge_items (
  id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL CHECK (source_type IN ('task', 'progress', 'daily_summary', 'weekly_summary', 'task_summary', 'project_note', 'imported_document')),
  source_id TEXT NULL,
  project_id TEXT NULL REFERENCES projects(id) ON DELETE SET NULL,
  task_id TEXT NULL REFERENCES tasks(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  body_markdown TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  occurred_at TEXT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  archived_at TEXT NULL,
  exported_markdown_path TEXT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_items_source ON knowledge_items(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_items_task_id ON knowledge_items(task_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_items_project_id ON knowledge_items(project_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_items_occurred_at ON knowledge_items(occurred_at);

CREATE TABLE IF NOT EXISTS knowledge_links (
  id TEXT PRIMARY KEY,
  from_item_id TEXT NOT NULL REFERENCES knowledge_items(id) ON DELETE CASCADE,
  to_item_id TEXT NOT NULL REFERENCES knowledge_items(id) ON DELETE CASCADE,
  link_type TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  color TEXT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_tags (
  id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  UNIQUE(entity_type, entity_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_entity_tags_entity ON entity_tags(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS privacy_rules (
  id TEXT PRIMARY KEY,
  rule_type TEXT NOT NULL CHECK (rule_type IN ('process_name', 'window_title', 'website_domain')),
  pattern TEXT NOT NULL,
  match_type TEXT NOT NULL CHECK (match_type IN ('exact', 'contains', 'regex')),
  action TEXT NOT NULL CHECK (action IN ('exclude', 'redact_title', 'mark_private')),
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_privacy_rules_enabled ON privacy_rules(enabled);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_items_fts USING fts5(
  title,
  body_markdown,
  source_type UNINDEXED,
  content='knowledge_items',
  content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS knowledge_items_ai AFTER INSERT ON knowledge_items BEGIN
  INSERT INTO knowledge_items_fts(rowid, title, body_markdown, source_type)
  VALUES (new.rowid, new.title, new.body_markdown, new.source_type);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_items_ad AFTER DELETE ON knowledge_items BEGIN
  INSERT INTO knowledge_items_fts(knowledge_items_fts, rowid, title, body_markdown, source_type)
  VALUES ('delete', old.rowid, old.title, old.body_markdown, old.source_type);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_items_au AFTER UPDATE ON knowledge_items BEGIN
  INSERT INTO knowledge_items_fts(knowledge_items_fts, rowid, title, body_markdown, source_type)
  VALUES ('delete', old.rowid, old.title, old.body_markdown, old.source_type);
  INSERT INTO knowledge_items_fts(rowid, title, body_markdown, source_type)
  VALUES (new.rowid, new.title, new.body_markdown, new.source_type);
END;
"""
