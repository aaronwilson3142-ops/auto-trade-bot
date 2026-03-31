@echo off
:: APIS Watchdog — keeps the API+Scheduler process alive indefinitely.
:: Run this script at login via Task Scheduler. It loops forever, restarting
:: APIS if it exits for any reason (crash, update, etc.).

:loop
echo [APIS-WATCHDOG] %DATE% %TIME% — Checking APIS...

:: Is uvicorn already running?
tasklist /FI "IMAGENAME eq python.exe" 2>NUL | find /I "python.exe" >NUL
if %ERRORLEVEL% NEQ 0 (
    echo [APIS-WATCHDOG] APIS not running — starting now...
    call "C:\Users\aaron\OneDrive\Desktop\AI Projects\Auto Trade Bot\apis\start_apis.bat"
) else (
    :: python.exe is running, but check if it is OUR uvicorn specifically
    wmic process where "name='python.exe'" get CommandLine 2>NUL | find "uvicorn" >NUL
    if %ERRORLEVEL% NEQ 0 (
        echo [APIS-WATCHDOG] uvicorn not in running python processes — starting now...
        call "C:\Users\aaron\OneDrive\Desktop\AI Projects\Auto Trade Bot\apis\start_apis.bat"
    ) else (
        echo [APIS-WATCHDOG] APIS is running — OK
    )
)

:: Wait 60 seconds before checking again
timeout /t 60 /nobreak >NUL
goto loop
