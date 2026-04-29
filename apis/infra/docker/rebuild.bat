@echo off
cd /d "%~dp0"
echo === Starting Docker build ===
docker compose --env-file "../../../.env" build --no-cache worker api
echo === Build exit code: %ERRORLEVEL% ===
echo === Restarting containers ===
docker compose --env-file "../../../.env" up -d worker api
echo === Up exit code: %ERRORLEVEL% ===
echo === Done ===
