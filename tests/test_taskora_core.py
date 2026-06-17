from __future__ import annotations

import tempfile
import time
import unittest

from taskora.activity import ForegroundWindowSnapshot, PrivacyRuleMatcher
from taskora.app_context import AppContext


class TaskoraCoreTests(unittest.TestCase):
    def make_context(self) -> AppContext:
        self.tempdir = tempfile.TemporaryDirectory(prefix="taskora-test-")
        return AppContext(self.tempdir.name)

    def tearDown(self) -> None:
        temp = getattr(self, "tempdir", None)
        if temp:
            temp.cleanup()

    def test_task_session_lifecycle(self) -> None:
        context = self.make_context()
        try:
            task_id = context.task_service.create_task("Write tests")
            context.task_service.start_task(task_id)
            time.sleep(1.02)
            context.task_service.pause_task(task_id)
            task = context.task_service.get_task(task_id)
            self.assertEqual(task["status"], "paused")
            self.assertGreaterEqual(task["total_seconds"], 1)
            session = context.db.query_one("SELECT * FROM task_sessions WHERE task_id = ?", (task_id,))
            self.assertEqual(session["ended_reason"], "paused")
        finally:
            context.stop()

    def test_only_one_active_task(self) -> None:
        context = self.make_context()
        try:
            first = context.task_service.create_task("First")
            second = context.task_service.create_task("Second")
            context.task_service.start_task(first)
            context.task_service.start_task(second)
            self.assertEqual(context.task_service.current_active_task_id(), second)
            self.assertEqual(context.task_service.get_task(first)["status"], "paused")
        finally:
            context.stop()

    def test_privacy_rule_redacts_title(self) -> None:
        context = self.make_context()
        try:
            decision = PrivacyRuleMatcher(context.settings, context.db).apply(ForegroundWindowSnapshot(1, "Telegram.exe", "Client details"))
            self.assertTrue(decision.should_record)
            self.assertTrue(decision.is_private)
            self.assertEqual(decision.window_title, "[hidden]")
        finally:
            context.stop()

    def test_ai_summary_and_knowledge_search(self) -> None:
        context = self.make_context()
        try:
            task_id = context.task_service.create_task("Implement archive")
            context.task_service.start_task(task_id)
            context.task_service.add_progress(task_id, done="Implemented knowledge archive", next_step="Run search verification")
            context.task_service.complete_task(task_id)
            markdown, data = context.ai_service.generate_task_summary(task_id)
            self.assertIn("## Task Result", markdown)
            summary_id = context.ai_service.save_summary("task", "Archive Summary", markdown, data, task_id)
            item_id = context.knowledge_service.archive_summary(summary_id)
            results = context.knowledge_service.search("archive")
            self.assertIn(item_id, {item["id"] for item in results})
        finally:
            context.stop()

    def test_daily_summary_uses_no_private_titles(self) -> None:
        context = self.make_context()
        try:
            task_id = context.task_service.create_task("Private check")
            context.task_service.start_task(task_id)
            context.db.execute(
                """
                INSERT INTO activity_spans(id, task_id, started_at, ended_at, duration_seconds, process_name, window_title, is_private, is_idle, capture_level, created_at)
                VALUES ('span1', ?, datetime('now'), datetime('now', '+1 minute'), 60, 'Telegram.exe', '[hidden]', 1, 0, 'private', datetime('now'))
                """,
                (task_id,),
            )
            data = context.ai_service.daily_input()
            self.assertNotIn("Client details", str(data))
            self.assertIn("Hidden app", str(data))
        finally:
            context.stop()


if __name__ == "__main__":
    unittest.main()
