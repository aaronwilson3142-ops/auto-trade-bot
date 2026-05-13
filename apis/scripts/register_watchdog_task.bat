@echo off
:: Register the APIS Docker Watchdog as a Windows Scheduled Task.
::
:: Phase 81-D (DEC-084) durable mitigation for the Docker Desktop Autostart
:: Blocker incident pattern. Run this as Administrator once per machine.
::
:: The task fires:
::   - At user logon (catches Docker Desktop autostart failures).
::   - Every 5 minutes thereafter (catches mid-day engine crashes).
::
:: One-shot mode each tick so a hung run cannot block subsequent ticks.

setlocal

set "TASK_NAME=APIS Docker Watchdog"
set "SCRIPT=C:\Projects\Auto Trade Bot\apis\scripts\windows_docker_watchdog.ps1"

if not exist "%SCRIPT%" (
    echo [ERROR] Cannot find %SCRIPT%
    exit /b 1
)

echo === Removing prior task (if any) ===
schtasks /Delete /TN "%TASK_NAME%" /F >NUL 2>&1

echo === Registering at-logon trigger ===
schtasks /Create ^
    /TN "%TASK_NAME% (Logon)" ^
    /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"%SCRIPT%\" -OneShot" ^
    /SC ONLOGON ^
    /RL HIGHEST ^
    /F

echo === Registering 5-minute trigger ===
schtasks /Create ^
    /TN "%TASK_NAME%" ^
    /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"%SCRIPT%\" -OneShot" ^
    /SC MINUTE /MO 5 ^
    /RL HIGHEST ^
    /F

echo.
echo Watchdog tasks registered. Log file: C:\ProgramData\APIS\watchdog.log
echo Test with: schtasks /Run /TN "%TASK_NAME%"
endlocal
