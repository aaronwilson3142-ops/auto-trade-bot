# APIS Database Backup Runbook

## Overview

PostgreSQL is the authoritative store for all APIS data: trades, portfolio
snapshots, signals, rankings, evaluations, system state, and audit events.
Regular backups are essential before any live trading is enabled.

---

## Backup Strategy

| Schedule | Type | Retention | Command |
|----------|------|-----------|---------|
| Daily (03:00 local) | Full logical dump (pg_dump) | 14 days | See §1 |
| Before any migration | Pre-migration snapshot | Keep until migration verified | See §2 |
| Before live mode promotion | Full snapshot | Keep indefinitely | See §2 |

---

## §1 — Daily Automated Backup (Docker Compose)

### 1.1 Manual backup (run any time)

```bash
# From the project root — substitute real password
docker exec docker-postgres-1 pg_dump \
  -U apis \
  --format=custom \
  --compress=9 \
  apis \
  > "backups/apis_$(date +%Y%m%d_%H%M%S).dump"
```

### 1.2 Automated backup via docker-compose cron service

Add the following service to `apis/infra/docker/docker-compose.yml` when ready
to enable automated backups.  The service uses the official `postgres` image,
so no extra tools are needed.

```yaml
  db-backup:
    image: postgres:17-alpine
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      PGPASSWORD: ${POSTGRES_PASSWORD:-apis_dev_password}
    volumes:
      - ../../../backups:/backups
    entrypoint: >
      sh -c "
        while true; do
          FILENAME=\"/backups/apis_$$(date +%Y%m%d_%H%M%S).dump\";
          pg_dump -h postgres -U ${POSTGRES_USER:-apis} --format=custom --compress=9 apis > $$FILENAME;
          echo \"Backup written: $$FILENAME\";
          find /backups -name '*.dump' -mtime +14 -delete;
          echo \"Old backups pruned (>14 days)\";
          sleep 86400;
        done
      "
    networks:
      - apis_net
```

Also create the `backups/` directory at the project root and add it to
`.gitignore`:

```bash
mkdir -p backups
echo "backups/*.dump" >> .gitignore
```

---

## §2 — Pre-migration / Pre-promotion Snapshot

Run this before any Alembic migration or before promoting to live mode:

```bash
# Named snapshot — keep these indefinitely
docker exec docker-postgres-1 pg_dump \
  -U apis \
  --format=custom \
  --compress=9 \
  apis \
  > "backups/apis_premigration_$(date +%Y%m%d_%H%M%S).dump"
```

---

## §3 — Restore from Backup

```bash
# 1. Stop the API and worker to prevent writes during restore
docker stop docker-api-1 docker-worker-1

# 2. Drop and recreate the database
docker exec -e PGPASSWORD=<password> docker-postgres-1 \
  psql -U apis -c "DROP DATABASE IF EXISTS apis;"
docker exec -e PGPASSWORD=<password> docker-postgres-1 \
  psql -U apis -c "CREATE DATABASE apis;"

# 3. Restore from dump
docker exec -i docker-postgres-1 pg_restore \
  -U apis \
  --dbname=apis \
  --format=custom \
  --no-owner \
  --exit-on-error \
  < backups/apis_<timestamp>.dump

# 4. Restart services
docker start docker-api-1 docker-worker-1

# 5. Verify
curl -s http://localhost:8000/health | python -m json.tool
```

---

## §4 — Backup Verification

Periodically verify backups are valid and restorable:

```bash
# Test restore to a throwaway database
docker exec -e PGPASSWORD=<password> docker-postgres-1 \
  psql -U apis -c "CREATE DATABASE apis_restore_test;"

docker exec -i docker-postgres-1 pg_restore \
  -U apis \
  --dbname=apis_restore_test \
  --format=custom \
  --no-owner \
  < backups/apis_<timestamp>.dump

# Quick sanity check — count rows in key tables
docker exec -e PGPASSWORD=<password> docker-postgres-1 \
  psql -U apis -d apis_restore_test \
  -c "SELECT schemaname, tablename, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 10;"

# Clean up
docker exec -e PGPASSWORD=<password> docker-postgres-1 \
  psql -U apis -c "DROP DATABASE apis_restore_test;"
```

---

## §5 — Offsite / Cloud Backup (future)

For production use, pipe dumps directly to cloud storage:

```bash
# AWS S3
docker exec docker-postgres-1 pg_dump -U apis --format=custom --compress=9 apis \
  | aws s3 cp - "s3://your-bucket/apis-backups/apis_$(date +%Y%m%d_%H%M%S).dump"

# Azure Blob Storage
docker exec docker-postgres-1 pg_dump -U apis --format=custom --compress=9 apis \
  | az storage blob upload --container-name backups \
      --name "apis_$(date +%Y%m%d_%H%M%S).dump" \
      --file /dev/stdin
```

---

## §6 — Checklist Before Live Mode Promotion

- [ ] Daily backup job is running and files are being written
- [ ] At least one restore test has been performed successfully
- [ ] Backup files are stored offsite (S3 or equivalent)
- [ ] Retention policy is enforced (14 days for daily, indefinite for pre-migration)
- [ ] `PGPASSWORD` / credentials are not hardcoded in scripts; use environment variables
- [ ] Backup location is included in disaster recovery documentation
