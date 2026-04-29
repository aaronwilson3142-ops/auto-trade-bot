@echo off
REM Restart APIS Docker stack to pick up updated .env
REM (max_positions 10 -> 15, max_new_positions_per_day 3 -> 5)
REM Created 2026-04-15

cd /d "C:\Projects\Auto Trade Bot\apis\infra\docker"

echo.
echo === Current container status ===
docker ps --format "table {{.Names}}\t{{.Status}}"

echo.
echo === Restarting api + worker (picks up new .env) ===
docker compose --env-file "../../.env" up -d --force-recreate api worker

echo.
echo === New status ===
docker ps --format "table {{.Names}}\t{{.Status}}"

echo.
echo === Verifying new APIS_MAX_POSITIONS inside worker container ===
docker exec docker-worker-1 printenv APIS_MAX_POSITIONS
docker exec docker-worker-1 printenv APIS_MAX_NEW_POSITIONS_PER_DAY

echo.
echo Done. Press any key to close.
pause >nul
