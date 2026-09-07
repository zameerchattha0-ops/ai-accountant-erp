@echo off
REM Backend runner - kept in a SEPARATE .bat file so Runapp.bat needs no
REM nested quoting (cmd.exe quote handling with space-containing paths is
REM the #1 cause of silent launcher failures).
cd /d "%~dp0"
"venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1
