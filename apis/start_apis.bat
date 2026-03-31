@echo off
:: APIS Combined Startup Script
:: Starts Redis (if not already running), then the API+Scheduler in one process.
:: Uses full paths throughout so it works correctly from Task Scheduler.

echo [APIS] Starting APIS at %DATE% %TIME%

:: ── 1. Ensure Redis is running ─────────────────────────────────────────────
tasklist /FI "IMAGENAME eq redis-server.exe" 2>NUL | find /I "redis-server.exe" >NUL
if %ERRORLEVEL% NEQ 0 (
    echo [APIS] Redis not running — starting...
    start "APIS-Redis" /MIN "C:\Users\aaron\Desktop\redis\redis-server.exe" "C:\Users\aaron\Desktop\redis\redis.windows.conf"
    ping -n 4 127.0.0.1 >NUL
) else (
    echo [APIS] Redis already running — OK
)

:: ── 2. Start the combined API + scheduler (single process) ─────────────────
echo [APIS] Starting API + Scheduler...
"C:\Users\aaron\OneDrive\Desktop\AI Projects\Auto Trade Bot\apis\.venv\Scripts\python.exe" -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
