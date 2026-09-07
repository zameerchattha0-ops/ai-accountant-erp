@echo off
REM =============================================================================
REM ONE-CLICK CLOCK FIX - run this whenever the app says
REM "Invalid authentication token" / "clock is behind real time".
REM The machine's clock drifts behind real time, which makes freshly issued
REM login tokens look "not yet valid" to the backend.  This script re-syncs
REM the Windows clock with the internet time servers (needs admin - it will
REM ask for permission automatically).
REM =============================================================================
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
echo [1/3] Starting the Windows time service...
net start w32time >nul 2>&1
echo [2/3] Pointing it at reliable internet time servers...
w32tm /config /manualpeerlist:"time.windows.com,0x9 pool.ntp.org,0x9" /syncfromflags:manual /reliable:yes /update
echo [3/3] Forcing a sync...
w32tm /resync /force
echo.
echo Current system time: %date% %time%
echo.
echo Done. If the app still reports a clock problem, run this file once more.
pause
