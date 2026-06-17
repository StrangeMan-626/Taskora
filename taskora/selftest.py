from __future__ import annotations

import tempfile
import time

from .activity import ForegroundWindowSnapshot, PrivacyRuleMatcher
from .app_context import AppContext


def run_selftest() -> list[str]:
    checks: list[str] = []
    with tempfile.TemporaryDirectory(prefix="taskora-selftest-") as tmp:
        context = AppContext(tmp)
        try:
            task_id = context.task_service.create_task("Self-test Task", "Verify the main workflow.", project="Taskora", tags="selftest, local")
            checks.append("created task")
            context.task_service.start_task(task_id)
            time.sleep(1.05)
            context.task_service.add_progress(task_id, done="Created a task and started a focus session.", blocker="None", next_step="Complete and summarize the task.", source_process_name="Code.exe", source_window_title="Taskora", is_private_context=False)
            context.task_service.complete_task(task_id)
            task = context.task_service.get_task(task_id)
            assert task and task["status"] == "completed"
            assert task["total_seconds"] >= 1
            checks.append("tracked session and progress")
            decision = PrivacyRuleMatcher(context.settings, context.db).apply(ForegroundWindowSnapshot(123, "Telegram.exe", "Sensitive chat"))
            assert decision.should_record and decision.is_private and decision.window_title == "[hidden]"
            checks.append("redacted privacy process")
            stats = context.stats_service.today()
            assert any(item["title"] == "Self-test Task" for item in stats["task_usage"])
            checks.append("computed today stats")
            markdown, data = context.ai_service.generate_task_summary(task_id)
            assert "## Task Result" in markdown
            summary_id = context.ai_service.save_summary("task", "Self-test Task Summary", markdown, data, task_id=task_id)
            item_id = context.knowledge_service.archive_summary(summary_id)
            assert any(item["id"] == item_id for item in context.knowledge_service.search("Self-test"))
            checks.append("saved summary and searched knowledge")
        finally:
            context.stop()
    return checks


def main() -> None:
    for check in run_selftest():
        print(f"OK {check}")


if __name__ == "__main__":
    main()
