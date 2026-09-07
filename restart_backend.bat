@echo off
REM =============================================================================
REM INSTANT BACKEND RESTART - kills whatever is listening on :8000 and
REM relaunches uvicorn with the CURRENT code (logs to backend.log).
REM Use after code changes, or whenever the backend behaves oddly.
REM =============================================================================
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
ping -n 2 127.0.0.1 >nul
start "ERP Backend (FastAPI)" /min "%~dp0run_backend.bat"
echo Backend restarting on http://localhost:8000 - allow a few seconds, then check http://localhost:8000/api/health
