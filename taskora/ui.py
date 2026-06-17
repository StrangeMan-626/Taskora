from __future__ import annotations

import json
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from .activity import ForegroundWindowSampler, PrivacyRuleMatcher
from .app_context import AppContext
from .utils import format_duration, parse_dt

STATUS_LABELS = {
    "todo": "Todo",
    "in_progress": "In progress",
    "paused": "Paused",
    "completed": "Completed",
    "archived": "Archived",
}

STATUS_COLORS = {
    "todo": "#6b7280",
    "in_progress": "#0f766e",
    "paused": "#b45309",
    "completed": "#15803d",
    "archived": "#64748b",
}


class TaskoraApp(tk.Tk):
    def __init__(self, context: AppContext):
        super().__init__()
        self.context = context
        self.title("Taskora")
        self.geometry("1120x720")
        self.minsize(920, 600)
        self.configure(bg="#f5f7f9")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.note_windows: dict[str, TaskNoteWindow] = {}
        self.task_filter = tk.StringVar(value="all")
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.summary_title = tk.StringVar(value="Today Summary")
        self.summary_task_id: str | None = None
        self.current_summary_id: str | None = None
        self.current_summary_type = "daily"
        self.current_summary_input: dict | None = None
        self._configure_style()
        self._build_layout()
        self._maybe_show_onboarding()
        self.context.start()
        self.refresh_all()
        self.after(1000, self.tick)

    def _configure_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f5f7f9")
        style.configure("Surface.TFrame", background="#ffffff")
        style.configure("TLabel", background="#f5f7f9", foreground="#172033")
        style.configure("Surface.TLabel", background="#ffffff", foreground="#172033")
        style.configure("TButton", padding=(10, 6))
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9))
        style.configure("TNotebook.Tab", padding=(14, 8))

    def _build_layout(self) -> None:
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True, padx=14, pady=14)
        bar = ttk.Frame(root)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Label(bar, text="Taskora", font=("Segoe UI Semibold", 18)).pack(side="left")
        ttk.Button(bar, text="New Task", command=self.open_task_dialog).pack(side="right")
        ttk.Button(bar, text="Pause/Resume Recording", command=self.toggle_recording).pack(side="right", padx=(0, 8))
        ttk.Label(bar, textvariable=self.status_var).pack(side="right", padx=(0, 16))
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)
        self.today_tab = ttk.Frame(self.notebook)
        self.tasks_tab = ttk.Frame(self.notebook)
        self.timeline_tab = ttk.Frame(self.notebook)
        self.knowledge_tab = ttk.Frame(self.notebook)
        self.ai_tab = ttk.Frame(self.notebook)
        self.settings_tab = ttk.Frame(self.notebook)
        for tab, label in [(self.today_tab, "Today"), (self.tasks_tab, "Tasks"), (self.timeline_tab, "Timeline"), (self.knowledge_tab, "Knowledge"), (self.ai_tab, "AI Summaries"), (self.settings_tab, "Settings")]:
            self.notebook.add(tab, text=label)
        self._build_today()
        self._build_tasks()
        self._build_timeline()
        self._build_knowledge()
        self._build_ai()
        self._build_settings()

    def _tree(self, parent, columns: tuple[str, ...], headings: tuple[str, ...]) -> ttk.Treeview:
        frame = ttk.Frame(parent, style="Surface.TFrame")
        frame.pack(fill="both", expand=True, pady=6)
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        for col, heading in zip(columns, headings):
            tree.heading(col, text=heading)
            tree.column(col, width=140, anchor="w")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return tree

    def _build_today(self) -> None:
        summary = ttk.Frame(self.today_tab, style="Surface.TFrame", padding=14)
        summary.pack(fill="x", padx=10, pady=10)
        self.today_metrics = ttk.Label(summary, text="", style="Surface.TLabel", font=("Segoe UI Semibold", 12))
        self.today_metrics.pack(anchor="w")
        ttk.Button(summary, text="Generate Today Summary", command=self.generate_daily_summary).pack(anchor="e", pady=(8, 0))
        body = ttk.PanedWindow(self.today_tab, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        left = ttk.Frame(body, style="Surface.TFrame", padding=10)
        right = ttk.Frame(body, style="Surface.TFrame", padding=10)
        body.add(left, weight=1)
        body.add(right, weight=1)
        ttk.Label(left, text="Task Time", style="Surface.TLabel", font=("Segoe UI Semibold", 11)).pack(anchor="w")
        self.today_task_tree = self._tree(left, ("task", "status", "time"), ("Task", "Status", "Time"))
        ttk.Label(left, text="Progress", style="Surface.TLabel", font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(12, 0))
        self.today_progress = tk.Listbox(left, height=8, borderwidth=0, highlightthickness=1)
        self.today_progress.pack(fill="both", expand=True, pady=(6, 0))
        ttk.Label(right, text="App Time", style="Surface.TLabel", font=("Segoe UI Semibold", 11)).pack(anchor="w")
        self.today_app_tree = self._tree(right, ("app", "time", "switches"), ("App", "Time", "Switches"))

    def _build_tasks(self) -> None:
        controls = ttk.Frame(self.tasks_tab, padding=10)
        controls.pack(fill="x")
        ttk.Label(controls, text="Status").pack(side="left")
        ttk.Combobox(controls, textvariable=self.task_filter, values=["all", "todo", "in_progress", "paused", "completed", "archived"], width=16, state="readonly").pack(side="left", padx=8)
        ttk.Button(controls, text="Refresh", command=self.refresh_all).pack(side="left")
        ttk.Button(controls, text="New Task", command=self.open_task_dialog).pack(side="right")
        self.tasks_tree = self._tree(self.tasks_tab, ("title", "status", "project", "today", "total", "progress"), ("Title", "Status", "Project", "Today", "Total", "Progress"))
        self.tasks_tree.bind("<Double-1>", self.open_selected_task)
        self.tasks_tree.bind("<Button-3>", self.show_task_tree_menu)

    def _build_timeline(self) -> None:
        controls = ttk.Frame(self.timeline_tab, padding=10)
        controls.pack(fill="x")
        ttk.Button(controls, text="Delete Today Activity", command=self.delete_today_activity).pack(side="right")
        self.timeline_tree = self._tree(self.timeline_tab, ("time", "duration", "app", "title", "task", "flags"), ("Time", "Duration", "App", "Window", "Task", "Flags"))

    def _build_knowledge(self) -> None:
        controls = ttk.Frame(self.knowledge_tab, padding=10)
        controls.pack(fill="x")
        ttk.Entry(controls, textvariable=self.search_var).pack(side="left", fill="x", expand=True)
        ttk.Button(controls, text="Search", command=self.refresh_knowledge).pack(side="left", padx=8)
        ttk.Button(controls, text="Export Selected", command=self.export_selected_knowledge).pack(side="left")
        pane = ttk.PanedWindow(self.knowledge_tab, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        left = ttk.Frame(pane, style="Surface.TFrame", padding=8)
        right = ttk.Frame(pane, style="Surface.TFrame", padding=8)
        pane.add(left, weight=1)
        pane.add(right, weight=2)
        self.knowledge_tree = self._tree(left, ("title", "type", "date"), ("Title", "Type", "Date"))
        self.knowledge_tree.bind("<<TreeviewSelect>>", self.show_knowledge_preview)
        self.knowledge_preview = tk.Text(right, wrap="word", borderwidth=0)
        self.knowledge_preview.pack(fill="both", expand=True)

    def _build_ai(self) -> None:
        top = ttk.Frame(self.ai_tab, padding=10)
        top.pack(fill="x")
        ttk.Button(top, text="Generate Today Summary", command=self.generate_daily_summary).pack(side="left")
        ttk.Button(top, text="Generate Selected Task Summary", command=self.generate_selected_task_summary).pack(side="left", padx=8)
        ttk.Button(top, text="Save Summary", command=self.save_current_summary).pack(side="right")
        ttk.Button(top, text="Archive Summary", command=self.archive_current_summary).pack(side="right", padx=8)
        title_row = ttk.Frame(self.ai_tab, padding=(10, 0))
        title_row.pack(fill="x")
        ttk.Label(title_row, text="Title").pack(side="left")
        ttk.Entry(title_row, textvariable=self.summary_title).pack(side="left", fill="x", expand=True, padx=8)
        pane = ttk.PanedWindow(self.ai_tab, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=10, pady=10)
        left = ttk.Frame(pane, style="Surface.TFrame", padding=8)
        right = ttk.Frame(pane, style="Surface.TFrame", padding=8)
        pane.add(left, weight=1)
        pane.add(right, weight=2)
        ttk.Label(left, text="Input Scope", style="Surface.TLabel").pack(anchor="w")
        self.ai_scope = tk.Text(left, height=20, wrap="word", borderwidth=0)
        self.ai_scope.pack(fill="both", expand=True, pady=(6, 0))
        ttk.Label(right, text="Markdown Draft", style="Surface.TLabel").pack(anchor="w")
        self.ai_editor = tk.Text(right, height=20, wrap="word", borderwidth=0)
        self.ai_editor.pack(fill="both", expand=True, pady=(6, 0))

    def _build_settings(self) -> None:
        outer = ttk.Frame(self.settings_tab, style="Surface.TFrame", padding=14)
        outer.pack(fill="both", expand=True, padx=10, pady=10)
        self.recording_enabled = tk.BooleanVar(value=self.context.settings.get("recording.enabled", True))
        self.sampling_interval = tk.IntVar(value=int(self.context.settings.get("recording.samplingIntervalSeconds", 2)))
        self.idle_threshold = tk.IntVar(value=int(self.context.settings.get("recording.idleThresholdSeconds", 180)))
        self.topmost_notes = tk.BooleanVar(value=self.context.settings.get("recording.topmostNotes", True))
        ttk.Checkbutton(outer, text="Recording enabled", variable=self.recording_enabled, command=self.save_settings).pack(anchor="w")
        ttk.Checkbutton(outer, text="Keep task notes on top", variable=self.topmost_notes, command=self.save_settings).pack(anchor="w")
        self._labeled_spin(outer, "Sampling interval seconds", self.sampling_interval, 1, 5)
        self._labeled_spin(outer, "Idle threshold seconds", self.idle_threshold, 30, 3600)
        ttk.Label(outer, text="Private processes", style="Surface.TLabel", font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(16, 4))
        self.private_processes = tk.Text(outer, height=6, width=50)
        self.private_processes.insert("1.0", "\n".join(self.context.settings.list_value("privacy.privateProcesses")))
        self.private_processes.pack(fill="x")
        ttk.Label(outer, text="Private title keywords", style="Surface.TLabel", font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(16, 4))
        self.private_titles = tk.Text(outer, height=5, width=50)
        self.private_titles.insert("1.0", "\n".join(self.context.settings.list_value("privacy.privateTitleKeywords")))
        self.private_titles.pack(fill="x")
        ttk.Button(outer, text="Save Settings", command=self.save_settings).pack(anchor="e", pady=(14, 0))

    def _labeled_spin(self, parent, label: str, variable: tk.IntVar, from_: int, to: int) -> None:
        row = ttk.Frame(parent, style="Surface.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text=label, style="Surface.TLabel").pack(side="left")
        ttk.Spinbox(row, from_=from_, to=to, textvariable=variable, width=8, command=self.save_settings).pack(side="right")

    def _maybe_show_onboarding(self) -> None:
        if self.context.settings.get("onboarding.completed", False):
            return
        messagebox.showinfo("Taskora privacy", "Taskora records local task time, foreground app names, window titles, and idle time for personal review.\n\nIt does not record keyboard input, clipboard contents, screenshots, recordings, or chat content.\n\nAI summaries are generated only after you review the input scope.")
        self.context.settings.set("onboarding.completed", True)

    def refresh_all(self) -> None:
        self.refresh_status()
        self.refresh_tasks()
        self.refresh_today()
        self.refresh_timeline()
        self.refresh_knowledge()
        self.sync_note_windows()

    def refresh_status(self) -> None:
        enabled = self.context.settings.get("recording.enabled", True)
        active = self.context.task_service.current_active_task_id()
        state = "Recording" if enabled else "Paused"
        task = self.context.task_service.get_task(active) if active else None
        if task:
            state += f" - Focus: {task['title']}"
        self.status_var.set(state)

    def refresh_tasks(self) -> None:
        self._clear_tree(self.tasks_tree)
        selected_filter = self.task_filter.get()
        for task in self.context.task_service.list_tasks(include_archived=True):
            if selected_filter != "all" and task["status"] != selected_filter:
                continue
            self.tasks_tree.insert("", "end", iid=task["id"], values=(task["title"], STATUS_LABELS.get(task["status"], task["status"]), task["project_name"] or "", format_duration(task["today_seconds"]), format_duration(task["total_seconds"]), task["progress_count_today"]))

    def refresh_today(self) -> None:
        data = self.context.stats_service.today()
        self.today_metrics.config(text=f"{data['date']} - Active {format_duration(data['active_seconds'])} - Idle {format_duration(data['idle_seconds'])}")
        self._clear_tree(self.today_task_tree)
        for item in data["task_usage"]:
            self.today_task_tree.insert("", "end", values=(item["title"], STATUS_LABELS.get(item["status"], item["status"]), format_duration(item["seconds"])))
        self._clear_tree(self.today_app_tree)
        for item in data["app_usage"]:
            self.today_app_tree.insert("", "end", values=(item["process_name"], format_duration(item["seconds"]), item["switch_count"]))
        self.today_progress.delete(0, "end")
        for item in data["progress"]:
            parts = [item["task_title"], item["done_text"], item["blocker_text"], item["next_text"]]
            self.today_progress.insert("end", " - ".join(part for part in parts if part))

    def refresh_timeline(self) -> None:
        self._clear_tree(self.timeline_tree)
        for item in self.context.stats_service.today()["timeline"]:
            flags = []
            if item["is_idle"]:
                flags.append("idle")
            if item["is_private"]:
                flags.append("private")
            self.timeline_tree.insert("", "end", iid=item["id"], values=(f"{self._local_time(item['started_at'])}-{self._local_time(item['ended_at'])}", format_duration(item["duration_seconds"]), "Hidden app" if item["is_private"] else item["process_name"], "[hidden]" if item["is_private"] else item["window_title"] or "", item["task_title"] or "", ", ".join(flags)))

    def refresh_knowledge(self) -> None:
        self._clear_tree(self.knowledge_tree)
        for item in self.context.knowledge_service.search(self.search_var.get()):
            self.knowledge_tree.insert("", "end", iid=item["id"], values=(item["title"], item["source_type"], self._local_date(item["created_at"])))

    def sync_note_windows(self) -> None:
        tasks = {task["id"]: task for task in self.context.task_service.list_tasks(include_archived=True) if task["note_visible"] and task["status"] != "archived"}
        for task_id, task in tasks.items():
            if task_id not in self.note_windows or not self.note_windows[task_id].winfo_exists():
                self.note_windows[task_id] = TaskNoteWindow(self, self.context, task_id)
            self.note_windows[task_id].refresh(task)
        for task_id in list(self.note_windows.keys()):
            if task_id not in tasks:
                window = self.note_windows.pop(task_id)
                if window.winfo_exists():
                    window.destroy()

    def open_task_dialog(self, task_id: str | None = None) -> None:
        TaskDialog(self, self.context, task_id, on_saved=self.refresh_all)

    def open_selected_task(self, event=None) -> None:
        selected = self.tasks_tree.selection()
        if selected:
            self.open_task_dialog(selected[0])

    def show_task_tree_menu(self, event) -> None:
        row = self.tasks_tree.identify_row(event.y)
        if row:
            self.tasks_tree.selection_set(row)
            self.show_task_menu(row, event.x_root, event.y_root)

    def show_task_menu(self, task_id: str, x: int, y: int) -> None:
        menu = tk.Menu(self, tearoff=0)
        task = self.context.task_service.get_task(task_id)
        if not task:
            return
        if task["status"] in {"todo", "paused"}:
            menu.add_command(label="Start Focus", command=lambda: self.start_task(task_id))
        if task["status"] == "in_progress":
            menu.add_command(label="Pause Task", command=lambda: self.pause_task(task_id))
        menu.add_command(label="Add Progress", command=lambda: self.add_progress(task_id))
        if task["status"] != "completed":
            menu.add_command(label="Mark Complete", command=lambda: self.complete_task(task_id))
        menu.add_separator()
        menu.add_command(label="Generate Task Summary", command=lambda: self.generate_task_summary(task_id))
        menu.add_command(label="Archive Task Snapshot", command=lambda: self.archive_task_snapshot(task_id))
        menu.add_separator()
        menu.add_command(label="Edit Task", command=lambda: self.open_task_dialog(task_id))
        menu.add_command(label="Hide Note", command=lambda: self.hide_note(task_id))
        menu.add_command(label="Delete Task", command=lambda: self.delete_task(task_id))
        menu.tk_popup(x, y)

    def start_task(self, task_id: str) -> None:
        try:
            self.context.task_service.start_task(task_id)
            self.refresh_all()
        except ValueError as exc:
            messagebox.showerror("Task", str(exc))

    def pause_task(self, task_id: str) -> None:
        self.context.task_service.pause_task(task_id)
        self.refresh_all()

    def complete_task(self, task_id: str) -> None:
        self.context.task_service.complete_task(task_id)
        self.refresh_all()
        if messagebox.askyesno("Task completed", "Generate a task summary now?"):
            self.generate_task_summary(task_id)

    def add_progress(self, task_id: str) -> None:
        AddProgressDialog(self, self.context, task_id, on_saved=self.refresh_all)

    def hide_note(self, task_id: str) -> None:
        self.context.task_service.set_note_visibility(task_id, False)
        self.refresh_all()

    def delete_task(self, task_id: str) -> None:
        if messagebox.askyesno("Delete task", "Delete this task and all related records?"):
            self.context.task_service.delete_task(task_id)
            self.refresh_all()

    def archive_task_snapshot(self, task_id: str) -> None:
        task = self.context.task_service.get_task(task_id)
        if not task:
            return
        progress = self.context.task_service.progress_for_task(task_id)
        lines = [f"# {task['title']}", "", f"- Status: {task['status']}", f"- Total time: {format_duration(task['total_seconds'])}", "", "## Progress", ""]
        for item in reversed(progress):
            lines.append(f"- {self._local_time(item['occurred_at'])}: {item['done_text'] or ''}")
        item_id = self.context.knowledge_service.archive_task_snapshot(task_id, task["title"], "\n".join(lines))
        messagebox.showinfo("Knowledge", f"Archived task snapshot: {item_id}")
        self.refresh_knowledge()

    def generate_daily_summary(self) -> None:
        if not self.confirm_ai_scope("daily"):
            return
        markdown, data = self.context.ai_service.generate_daily_summary()
        self.current_summary_type = "daily"
        self.summary_task_id = None
        self.current_summary_input = data
        self.current_summary_id = None
        self.summary_title.set(f"{datetime.now():%Y-%m-%d} Today Summary")
        self._set_text(self.ai_scope, json.dumps(data, ensure_ascii=False, indent=2))
        self._set_text(self.ai_editor, markdown)
        self.notebook.select(self.ai_tab)

    def generate_selected_task_summary(self) -> None:
        selected = self.tasks_tree.selection()
        if not selected:
            messagebox.showwarning("AI Summary", "Select a task first in the Tasks tab.")
            return
        self.generate_task_summary(selected[0])

    def generate_task_summary(self, task_id: str) -> None:
        if not self.confirm_ai_scope("task"):
            return
        markdown, data = self.context.ai_service.generate_task_summary(task_id)
        task = self.context.task_service.get_task(task_id)
        self.current_summary_type = "task"
        self.summary_task_id = task_id
        self.current_summary_input = data
        self.current_summary_id = None
        self.summary_title.set(f"{task['title']} Summary" if task else "Task Summary")
        self._set_text(self.ai_scope, json.dumps(data, ensure_ascii=False, indent=2))
        self._set_text(self.ai_editor, markdown)
        self.notebook.select(self.ai_tab)

    def confirm_ai_scope(self, summary_type: str) -> bool:
        if not self.context.settings.get("privacy.confirmBeforeAi", True):
            return True
        return messagebox.askyesno("Confirm AI input", f"Generate a {summary_type} summary from visible tasks, progress notes, and non-private app statistics?\n\nPrivate apps and hidden titles are excluded.")

    def save_current_summary(self) -> None:
        markdown = self.ai_editor.get("1.0", "end").strip()
        if not markdown:
            messagebox.showwarning("AI Summary", "There is no summary draft to save.")
            return
        self.current_summary_id = self.context.ai_service.save_summary(self.current_summary_type, self.summary_title.get().strip() or "Taskora Summary", markdown, self.current_summary_input or {}, self.summary_task_id)
        messagebox.showinfo("AI Summary", "Summary saved.")

    def archive_current_summary(self) -> None:
        if not self.current_summary_id:
            self.save_current_summary()
        if self.current_summary_id:
            item_id = self.context.knowledge_service.archive_summary(self.current_summary_id)
            messagebox.showinfo("Knowledge", f"Summary archived: {item_id}")
            self.refresh_knowledge()

    def show_knowledge_preview(self, event=None) -> None:
        selected = self.knowledge_tree.selection()
        if selected:
            row = self.context.db.query_one("SELECT * FROM knowledge_items WHERE id = ?", (selected[0],))
            if row:
                self._set_text(self.knowledge_preview, row["body_markdown"])

    def export_selected_knowledge(self) -> None:
        selected = self.knowledge_tree.selection()
        if not selected:
            messagebox.showwarning("Knowledge", "Select a knowledge item first.")
            return
        path = self.context.knowledge_service.export_markdown(selected[0])
        messagebox.showinfo("Knowledge", f"Exported to:\n{path}")

    def toggle_recording(self) -> None:
        current = self.context.settings.get("recording.enabled", True)
        self.context.settings.set("recording.enabled", not current)
        if current:
            self.context.activity_recorder.flush_current()
        self.recording_enabled.set(not current)
        self.refresh_status()

    def save_settings(self) -> None:
        self.context.settings.set("recording.enabled", self.recording_enabled.get())
        self.context.settings.set("recording.samplingIntervalSeconds", int(self.sampling_interval.get()))
        self.context.settings.set("recording.idleThresholdSeconds", int(self.idle_threshold.get()))
        self.context.settings.set("recording.topmostNotes", self.topmost_notes.get())
        self.context.settings.set("privacy.privateProcesses", [line.strip() for line in self.private_processes.get("1.0", "end").splitlines() if line.strip()])
        self.context.settings.set("privacy.privateTitleKeywords", [line.strip() for line in self.private_titles.get("1.0", "end").splitlines() if line.strip()])
        for window in self.note_windows.values():
            window.attributes("-topmost", self.topmost_notes.get())
        self.refresh_status()

    def delete_today_activity(self) -> None:
        if messagebox.askyesno("Delete activity", "Delete today's app activity records? Task notes remain."):
            self.context.stats_service.delete_day_activity(datetime.now().date())
            self.refresh_all()

    def tick(self) -> None:
        self.refresh_status()
        for window in list(self.note_windows.values()):
            if window.winfo_exists():
                window.refresh()
        self.after(1000, self.tick)

    def on_close(self) -> None:
        self.context.stop()
        for window in list(self.note_windows.values()):
            if window.winfo_exists():
                window.destroy()
        self.destroy()

    @staticmethod
    def _clear_tree(tree: ttk.Treeview) -> None:
        for item in tree.get_children():
            tree.delete(item)

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", text)

    @staticmethod
    def _local_time(value: str | None) -> str:
        parsed = parse_dt(value)
        return parsed.astimezone().strftime("%H:%M") if parsed else ""

    @staticmethod
    def _local_date(value: str | None) -> str:
        parsed = parse_dt(value)
        return parsed.astimezone().strftime("%Y-%m-%d") if parsed else ""

class TaskNoteWindow(tk.Toplevel):
    def __init__(self, app: TaskoraApp, context: AppContext, task_id: str):
        super().__init__(app)
        self.app = app
        self.context = context
        self.task_id = task_id
        self.overrideredirect(True)
        self.attributes("-topmost", context.settings.get("recording.topmostNotes", True))
        self.configure(bg="#ffffff", highlightthickness=1, highlightbackground="#d6dde5")
        self.drag_offset = (0, 0)
        self.title_label = tk.Label(self, text="", bg="#ffffff", fg="#172033", font=("Segoe UI Semibold", 10), anchor="w")
        self.meta_label = tk.Label(self, text="", bg="#ffffff", fg="#475569", font=("Segoe UI", 9), anchor="w")
        self.progress_label = tk.Label(self, text="", bg="#ffffff", fg="#64748b", font=("Segoe UI", 9), anchor="w")
        self.title_label.pack(fill="x", padx=10, pady=(8, 0))
        self.meta_label.pack(fill="x", padx=10, pady=(2, 0))
        self.progress_label.pack(fill="x", padx=10, pady=(2, 8))
        for widget in [self, self.title_label, self.meta_label, self.progress_label]:
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.drag)
            widget.bind("<ButtonRelease-1>", self.stop_drag)
            widget.bind("<Button-3>", self.show_menu)
            widget.bind("<Double-1>", lambda e: self.app.open_task_dialog(self.task_id))
        self.refresh()

    def refresh(self, task: dict | None = None) -> None:
        task = task or self.context.task_service.get_task(self.task_id)
        if not task:
            self.destroy()
            return
        self.configure(highlightbackground=STATUS_COLORS.get(task["status"], "#64748b"))
        self.title_label.config(text=task["title"])
        self.meta_label.config(text=f"{STATUS_LABELS.get(task['status'], task['status'])} - Today {format_duration(task['today_seconds'])} - Total {format_duration(task['total_seconds'])}")
        due = f" - Due {task['due_at']}" if task["due_at"] else ""
        self.progress_label.config(text=f"Progress today {task['progress_count_today']}{due}")
        width = int(task["note_width"] or 290)
        height = int(task["note_height"] or 92)
        x = int(task["note_x"] if task["note_x"] is not None else 80)
        y = int(task["note_y"] if task["note_y"] is not None else 80)
        if not self.winfo_ismapped():
            self.geometry(f"{width}x{height}+{x}+{y}")

    def start_drag(self, event) -> None:
        self.drag_offset = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def drag(self, event) -> None:
        self.geometry(f"+{event.x_root - self.drag_offset[0]}+{event.y_root - self.drag_offset[1]}")

    def stop_drag(self, event) -> None:
        self.context.task_service.save_note_position(self.task_id, self.winfo_x(), self.winfo_y(), self.winfo_width(), self.winfo_height())

    def show_menu(self, event) -> None:
        self.app.show_task_menu(self.task_id, event.x_root, event.y_root)


class TaskDialog(tk.Toplevel):
    def __init__(self, parent: TaskoraApp, context: AppContext, task_id: str | None, on_saved):
        super().__init__(parent)
        self.context = context
        self.task_id = task_id
        self.on_saved = on_saved
        self.title("Task")
        self.geometry("480x420")
        self.transient(parent)
        self.grab_set()
        task = context.task_service.get_task(task_id) if task_id else None
        self.title_var = tk.StringVar(value=task["title"] if task else "")
        self.project_var = tk.StringVar(value=task["project_name"] if task else "")
        self.due_var = tk.StringVar(value=task["due_at"] if task and task["due_at"] else "")
        self.tags_var = tk.StringVar(value=", ".join(task["tags"]) if task else "")
        self._build(task)

    def _build(self, task: dict | None) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        self._entry(frame, "Title", self.title_var)
        ttk.Label(frame, text="Description").pack(anchor="w", pady=(10, 0))
        self.description = tk.Text(frame, height=6)
        self.description.pack(fill="x")
        if task and task["description"]:
            self.description.insert("1.0", task["description"])
        self._entry(frame, "Project", self.project_var)
        self._entry(frame, "Due date/time", self.due_var)
        self._entry(frame, "Tags", self.tags_var)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(16, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Save", command=self.save).pack(side="right", padx=8)

    def _entry(self, parent, label: str, var: tk.StringVar) -> None:
        ttk.Label(parent, text=label).pack(anchor="w", pady=(10, 0))
        ttk.Entry(parent, textvariable=var).pack(fill="x")

    def save(self) -> None:
        try:
            if self.task_id:
                self.context.task_service.update_task(self.task_id, self.title_var.get(), self.description.get("1.0", "end").strip(), self.due_var.get().strip() or None, self.project_var.get(), self.tags_var.get())
            else:
                self.context.task_service.create_task(self.title_var.get(), self.description.get("1.0", "end").strip(), self.due_var.get().strip() or None, self.project_var.get(), self.tags_var.get())
            self.on_saved()
            self.destroy()
        except ValueError as exc:
            messagebox.showerror("Task", str(exc), parent=self)


class AddProgressDialog(tk.Toplevel):
    def __init__(self, parent: TaskoraApp, context: AppContext, task_id: str, on_saved):
        super().__init__(parent)
        self.context = context
        self.task_id = task_id
        self.on_saved = on_saved
        self.title("Add Progress")
        self.geometry("520x520")
        self.transient(parent)
        self.grab_set()
        self.snapshot = self._capture_context()
        self._build()

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"Time: {datetime.now():%H:%M}\nApp: {self.snapshot.process_name}\nWindow: {self.snapshot.window_title or '[hidden]'}").pack(anchor="w")
        self.done = self._text(frame, "What was completed?")
        self.blocker = self._text(frame, "Any blocker?")
        self.next_step = self._text(frame, "Next step?")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Save", command=self.save).pack(side="right", padx=8)
        ttk.Button(buttons, text="Save and Pause", command=self.save_and_pause).pack(side="right")

    def _text(self, parent, label: str) -> tk.Text:
        ttk.Label(parent, text=label).pack(anchor="w", pady=(12, 0))
        widget = tk.Text(parent, height=4)
        widget.pack(fill="x")
        return widget

    def _capture_context(self):
        sampler = ForegroundWindowSampler(int(self.context.settings.get("recording.idleThresholdSeconds", 180)))
        raw = sampler.capture()
        decision = PrivacyRuleMatcher(self.context.settings, self.context.db).apply(raw)

        class Snapshot:
            process_name = decision.process_name if decision.should_record else "Hidden app"
            window_title = decision.window_title if decision.should_record else "[hidden]"
            is_private = decision.is_private or not decision.should_record

        return Snapshot()

    def save(self) -> None:
        self.context.task_service.add_progress(self.task_id, self.done.get("1.0", "end").strip(), self.blocker.get("1.0", "end").strip(), self.next_step.get("1.0", "end").strip(), self.snapshot.process_name, self.snapshot.window_title, self.snapshot.is_private)
        self.on_saved()
        self.destroy()

    def save_and_pause(self) -> None:
        self.context.task_service.add_progress(self.task_id, self.done.get("1.0", "end").strip(), self.blocker.get("1.0", "end").strip(), self.next_step.get("1.0", "end").strip(), self.snapshot.process_name, self.snapshot.window_title, self.snapshot.is_private)
        self.context.task_service.pause_task(self.task_id)
        self.on_saved()
        self.destroy()


def run_app(data_dir=None) -> None:
    context = AppContext(data_dir)
    app = TaskoraApp(context)
    app.mainloop()
