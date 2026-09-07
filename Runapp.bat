@echo off
REM =============================================================================
REM ERP AI Agent - INSTANT One-Click Launcher (v3)
REM =============================================================================
REM Starts the three runtime components of the current project layout:
REM   * backend  : FastAPI (app.main:app)        -> http://localhost:8000  (run_backend.bat)
REM   * worker   : AI background job processor   -> ai.worker_jobs         (run_worker.bat)
REM                (scripts/ai_worker.py, logs to ai_worker.log)
REM   * frontend : Next.js 15 (frontend/src)     -> http://localhost:3000  (run_frontend.bat)
REM
REM WHY THIS IS FAST:
REM   * BACKEND, WORKER AND FRONTEND START IN PARALLEL.
REM   * The browser opens IMMEDIATELY - Next.js compiles the landing page
REM     while the backend finishes booting, so you never wait.
REM   * Frontend runs `next dev --turbopack` (Next 15.5 Turbopack: several
REM     times faster cold start than the default webpack dev server).
REM   * Health checks use native curl.exe (ships with Windows 10/11) instead
REM     of spawning a fresh Python interpreter every 2 seconds.
REM   * npm runner overhead is skipped: the local next binary is called
REM     directly from node_modules.
REM   * ERP_PROD=1 + an existing .next build  =>  `next start` (instant
REM     pages, no compile; rebuild with: cd frontend && npm run build).
REM =============================================================================

setlocal EnableExtensions EnableDelayedExpansion
title ERP AI Agent Launcher - Instant

REM ---- Resolve paths (quote-safe: paths contain spaces) ------------------------
set "ERP_ROOT=%~dp0"
if "%ERP_ROOT:~-1%"=="\" set "ERP_ROOT=%ERP_ROOT:~0,-1%"
set "VENV_PY=%ERP_ROOT%\venv\Scripts\python.exe"
set "FRONTEND_DIR=%ERP_ROOT%\frontend"
set "NEXT_BIN=%FRONTEND_DIR%\node_modules\.bin\next.cmd"
set "BACKEND_LOG=%ERP_ROOT%\backend.log"
set "WORKER_LOG=%ERP_ROOT%\ai_worker.log"
set "FRONTEND_LOG=%ERP_ROOT%\frontend.log"
set "BACKEND_URL=http://127.0.0.1:8000/api/health"
set "FRONTEND_URL=http://127.0.0.1:3000"

echo.
echo  ============================================
echo   ERP AI Agent - instant start...
echo  ============================================
echo.

REM ---- [1/5] Fast prerequisite checks ------------------------------------------
echo [1/5] Checking prerequisites...
if not exist "%VENV_PY%" (
    echo ERROR: Virtual environment not found: %VENV_PY%
    echo        Create it first:  python -m venv venv
    echo        Then:             venv\Scripts\pip install -r requirements.txt
    goto :fail
)
if not exist "%ERP_ROOT%\.env" (
    echo ERROR: .env not found at %ERP_ROOT%\.env
    echo        Copy .env.example to .env and fill in your credentials.
    goto :fail
)
if not exist "%FRONTEND_DIR%\package.json" (
    echo ERROR: Frontend not found at %FRONTEND_DIR%
    goto :fail
)
if not exist "%ERP_ROOT%\scripts\ai_worker.py" (
    echo ERROR: AI worker not found at %ERP_ROOT%\scripts\ai_worker.py
    goto :fail
)
if not exist "%NEXT_BIN%" (
    echo        node_modules missing - installing dependencies ^(one time only^)...
    pushd "%FRONTEND_DIR%"
    call npm install
    popd
    if not exist "%NEXT_BIN%" (
        echo ERROR: npm install failed - next binary still missing.
        goto :fail
    )
)
where curl >nul 2>&1
if errorlevel 1 (
    echo ERROR: curl.exe not found ^(built into Windows 10/11^).
    goto :fail
)

REM ---- [2/5] Kill stale servers on ports 8000 / 3000 (quick) --------------------
echo [2/5] Cleaning stale servers on ports 8000 / 3000...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":3000 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
ping -n 2 127.0.0.1 >nul

REM ---- [3/5] Start backend AND frontend IN PARALLEL ------------------------------
echo [3/5] Starting backend  (FastAPI   -^> http://localhost:8000) ...
start "ERP Backend (FastAPI)" /min "%ERP_ROOT%\run_backend.bat"

echo [3b/5] Starting AI worker (background job processor) ...
start "ERP AI Worker" /min "%ERP_ROOT%\run_worker.bat"

echo [4/5] Starting frontend (Next.js    -^> http://localhost:3000) ...
start "ERP Frontend (Next.js)" /min "%ERP_ROOT%\run_frontend.bat"

REM ---- [5/5] Open the browser IMMEDIATELY; then report health -------------------
echo [5/5] Opening browser (the page compiles while servers finish booting)...
start "" http://localhost:3000

set /a BT=0
:wait_backend
set /a BT+=1
curl -s -o NUL -m 2 "%BACKEND_URL%" >nul 2>&1
if errorlevel 1 (
    if !BT! GEQ 45 (
        echo        WARNING: backend not healthy after 90s - check backend.log
        goto :report
    )
    ping -n 2 127.0.0.1 >nul
    goto :wait_backend
)
echo        Backend is healthy.

:report
curl -s -o NUL -m 2 "%FRONTEND_URL%" >nul 2>&1
if errorlevel 1 (
    echo        Frontend is still compiling - it will finish in your browser tab.
) else (
    echo        Frontend is up.
)
echo.
echo  ============================================
echo   ERP AI Agent is running!
echo  ============================================
echo.
echo    App      : http://localhost:3000
echo    API      : http://localhost:8000   (docs at /docs)
echo    Worker   : background AI job processor (ai_worker.log)
echo.
echo    Backend log : %BACKEND_LOG%
echo    Worker log  : %WORKER_LOG%
echo    Frontend log: %FRONTEND_LOG%
echo    Tip: set ERP_PROD=1 before running to use the prebuilt .next bundle
echo         (instant pages, no hot reload). Rebuild with:  cd frontend ^&^& npm run build
echo.
echo    Close the three minimized server windows to stop.
echo.
endlocal
exit /b 0

:fail
echo.
echo  ============================ STARTUP FAILED ============================
echo  Fix the error above, then run Runapp.bat again.
echo  ========================================================================
endlocal
exit /b 1
