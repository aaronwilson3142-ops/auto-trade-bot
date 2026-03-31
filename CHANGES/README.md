# APIS — Improvement Change Log

Each session's changes are stored in their own folder with:
- `README.md`        — what changed, why, and how to revert
- `originals/`       — exact copy of every changed file *before* the session
- `*.patch`          — unified diff of every changed file (for review or `patch -R` revert)

To revert any session, either copy the originals back or apply the patches in reverse
(`patch -R file < file.patch`). Revert in reverse session order if multiple sessions
have touched the same file.

---

## Sessions

| Session | Folder | Status | Summary |
|---------|--------|--------|---------|
| 001 | `session_001_kill_switch/` | ✅ Applied | Fix runtime kill switch gap in RiskEngineService + ExecutionEngineService |
| 002 | `session_002_idempotency/` | ✅ Applied | Fix idempotency key to be deterministic |
| 003 | `session_003_monthly_drawdown/` | ✅ Applied | Add monthly drawdown limit to Settings + RiskEngineService |
| 004 | `session_004_daily_position_cap/` | ✅ Applied | Add max new positions per day limit |
| 005 | `session_005_sector_thematic/` | ✅ Applied | Sector/thematic checks in validate_action |
| 006 | `session_006_api_auth/` | ✅ Applied | API-wide operator token authentication |
| 007 | `session_007_cors/` | ✅ Applied | Tighten CORS from wildcard |
| 008 | `session_008_ci_lint/` | ⏳ Pending | Make ruff blocking + add mypy CI job |
| 009 | `session_009_coverage/` | ⏳ Pending | Add coverage enforcement in CI |
| 010 | `session_010_integration_ci/` | ⏳ Pending | Add integration test CI job |
| 011 | `session_011_worker_healthcheck/` | ⏳ Pending | Worker healthcheck in docker-compose |
| 012 | `session_012_db_backup/` | ⏳ Pending | DB backup runbook and cron strategy |
| 013 | `session_013_grafana_password/` | ⏳ Pending | Remove Grafana default password fallback |
| 014 | `session_014_config_stubs/` | ⏳ Pending | Fill out or remove empty config stubs |
| 015 | `session_015_type_hints/` | ⏳ Pending | Modernize Optional[X] to X \| None |
