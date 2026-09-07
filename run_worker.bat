@echo off
REM AI worker runner - claims and executes background AI runs from
REM ai.worker_jobs (Work Stream C).  Separate .bat so Runapp.bat stays
REM quote-safe and the worker logs to its own file.
cd /d "%~dp0"
"venv\Scripts\python.exe" scripts\ai_worker.py > ai_worker.log 2>&1
