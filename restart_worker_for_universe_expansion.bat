@echo off
REM Restart the APIS worker so the expanded universe (498 tickers) takes effect.
REM The worker auto-seeds the securities/themes/security_themes tables on startup.

echo.
echo === Current container status ===
docker ps --format "table {{.Names}}\t{{.Status}}" | findstr /R "worker api postgres redis"

echo.
echo === Restarting docker-worker-1 ===
docker restart docker-worker-1

echo.
echo === Tailing worker log for seed messages (Ctrl+C to exit) ===
docker logs -f --tail 50 docker-worker-1
