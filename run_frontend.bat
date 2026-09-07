@echo off
REM Frontend runner - separate .bat so Runapp.bat needs no nested quoting.
REM ERP_PROD=1 + existing .next build  =>  production server (instant pages).
REM Otherwise                          =>  Turbopack dev (fast cold start).
cd /d "%~dp0frontend"
set "MODE=dev"
if defined ERP_PROD if exist ".next\BUILD_ID" set "MODE=start"
if "%MODE%"=="start" (
    npm run start > "%~dp0frontend.log" 2>&1
) else (
    node_modules\.bin\next.cmd dev --turbopack > "%~dp0frontend.log" 2>&1
)
