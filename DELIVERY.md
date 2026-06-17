# Taskora Delivery Notes

## Current Result

Taskora now has a working Windows desktop MVP implemented with Python, Tkinter, SQLite, and Win32 APIs through ctypes. It can start as a desktop app, create task note windows, track task sessions, record foreground app spans, redact private app/window data, generate editable Markdown summary drafts, archive summaries into a local searchable knowledge base, and export Markdown knowledge files.

The repository originally specified .NET/WPF, but this machine has only .NET 6 runtimes and no .NET SDK. To deliver a verifiable runnable application in the current environment, the MVP uses the installed Python 3.13 runtime and standard library. The module boundaries still follow the documented Taskora architecture: tasks, activity, AI, storage, settings, and knowledge base are separated.

## How To Run

```powershell
python taskora_cli.py
```

or double-click:

```text
start_taskora.bat
```

Optional custom data directory:

```powershell
python taskora_cli.py --data-dir C:\TaskoraData
```

Default data is stored under `%LOCALAPPDATA%\Taskora`.

## Main Features Implemented

- Task CRUD with title, description, project, due date, and tags.
- Desktop task note windows with saved positions and right-click task actions.
- Task states: todo, in progress, paused, completed, archived.
- One active focus task at a time.
- Task session timing, pause, completion, and interrupted-session recovery.
- Progress notes with current app/window context and privacy redaction.
- Foreground window sampling using Win32 APIs through `ctypes`.
- Idle detection using `GetLastInputInfo`.
- Activity span aggregation in SQLite.
- Privacy process and title rules, with private titles hidden.
- Today view: task time, app time, timeline, progress, active and idle totals.
- AI summary drafts for daily and task summaries.
- Optional OpenAI-compatible / Ollama provider adapter; default is local offline draft generation.
- AI input snapshot hashing and summary persistence.
- Knowledge archive backed by SQLite FTS5.
- Markdown export for knowledge items.
- Settings for recording, sampling, idle threshold, note topmost behavior, and privacy lists.
- Self-test and unit test entry points.

## Verification Performed

```powershell
python -m py_compile taskora\__init__.py taskora\utils.py taskora\settings.py taskora\database.py taskora\activity.py taskora\ai_provider.py taskora\services.py taskora\app_context.py taskora\ui.py taskora\main.py taskora\selftest.py tests\test_taskora_core.py run_tests.py
python run_tests.py
python -m taskora.selftest
```

Results:

- 5 unit tests passed.
- Self-test passed: task creation, session timing, progress, privacy redaction, today stats, summary save, knowledge archive, and search.
- GUI smoke test passed by launching the Tkinter app, creating the main window, then exiting cleanly.
- Source encoding check passed for all tracked source files.

## Notes

- No screenshots, keyboard logging, clipboard logging, OCR, chat-content reading, or screen recording is implemented.
- AI calls are not made unless provider, endpoint, and model are configured. The default offline summary draft keeps the app usable without network or API keys.
- API keys are currently stored in settings if configured. For production hardening, move secrets to Windows Credential Manager or DPAPI.
- The documented .NET/WPF architecture remains the preferred long-term direction if a .NET SDK is installed later.
