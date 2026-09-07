@echo off
REM =============================================================================
REM ERP AI AGENT - PROJECT CLEANUP (one click)
REM =============================================================================
REM Removes ONLY regenerable artifacts, keeps all sources, tests and goldens:
REM   * runtime logs      : backend.log, ai_worker.log, frontend.log
REM   * python caches     : __pycache__ (everywhere outside venv), .pytest_cache
REM   * frontend caches   : frontend\.next, frontend\tsconfig.tsbuildinfo
REM   * scratch probes    : _* files in the workspace root (e:\Qoder)
REM
REM NEVER touches: app\, frontend\src, tests\goldens, scripts\test_*_live.py,
REM                smoke_test.py, eval_harness.py, ai_worker.py, venv, .env
REM
REM Running servers are stopped first (their logs are locked while in use);
REM you are asked whether to relaunch everything with Runapp.bat at the end.
REM =============================================================================
setlocal EnableExtensions
title ERP AI Agent - Cleanup

set "ERP_ROOT=%~dp0"
if "%ERP_ROOT:~-1%"=="\" set "ERP_ROOT=%ERP_ROOT:~0,-1%"
set "WS_ROOT=%ERP_ROOT%\.."

echo [1/4] Stopping running servers (ports 8000 / 3000 + AI worker)...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":3000 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq python.exe" /fo list 2^>nul ^| findstr /i "PID"') do (
    wmic process where "ProcessId=%%a" get CommandLine 2>nul | findstr /i "ai_worker" >nul 2>&1 && taskkill /F /PID %%a >nul 2>&1
)
ping -n 3 127.0.0.1 >nul

echo [2/4] Removing logs and caches...
del /f /q "%ERP_ROOT%\backend.log"    >nul 2>&1
del /f /q "%ERP_ROOT%\ai_worker.log"  >nul 2>&1
del /f /q "%ERP_ROOT%\frontend.log"   >nul 2>&1
rmdir /s /q "%ERP_ROOT%\.pytest_cache" >nul 2>&1
rmdir /s /q "%ERP_ROOT%\frontend\.next" >nul 2>&1
del /f /q "%ERP_ROOT%\frontend\tsconfig.tsbuildinfo" >nul 2>&1
for /d /r "%ERP_ROOT%" %%d in (__pycache__) do (
    echo %%d | findstr /i "\\venv\\" >nul 2>&1 || rmdir /s /q "%%d" >nul 2>&1
)

echo [3/4] Removing scratch probe files from the workspace root...
del /f /q "%WS_ROOT%\_*.txt" >nul 2>&1
del /f /q "%WS_ROOT%\_*.py"  >nul 2>&1
del /f /q "%WS_ROOT%\_*.ps1" >nul 2>&1
del /f /q "%WS_ROOT%\_*.bat" >nul 2>&1

echo [4/4] Done.
echo.
echo  Cleaned: logs, __pycache__, .pytest_cache, .next, tsbuildinfo, scratch files.
echo  Kept   : sources, app\tests, tests\goldens, live-test scripts, venv, .env
echo.
set /p RESTART="Restart the stack now with Runapp.bat? [y/N]: "
if /i "%RESTART%"=="y" call "%ERP_ROOT%\Runapp.bat"
endlocal
exit /b 0