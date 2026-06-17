from __future__ import annotations

from pathlib import Path

from .activity import ActivityRecorder
from .database import Database
from .services import AiSummaryService, KnowledgeBaseService, StatsService, TaskService
from .settings import SettingsStore
from .utils import app_data_dir


class AppContext:
    def __init__(self, data_dir: Path | str | None = None):
        self.data_dir = app_data_dir(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings = SettingsStore(self.data_dir / "taskora.settings.json")
        self.db = Database(self.data_dir / "taskora.db")
        self.task_service = TaskService(self.db)
        self.stats_service = StatsService(self.db, self.task_service)
        self.ai_service = AiSummaryService(self.db, self.task_service, self.stats_service, self.settings)
        self.knowledge_service = KnowledgeBaseService(self.db, self.settings)
        self.activity_recorder = ActivityRecorder(self.db, self.settings, self.task_service)

    def start(self) -> None:
        self.activity_recorder.start()

    def stop(self) -> None:
        self.activity_recorder.stop()
        self.db.close()
