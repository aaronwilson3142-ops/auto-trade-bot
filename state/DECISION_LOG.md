# APIS — Auto Health Check Decision Log

Auto-generated log of notable events and actions taken during daily health checks.

---

[2026-03-28 05:11] Auto health check: docker-worker-1 found unhealthy at check time. Applied Fix A (docker restart docker-worker-1). Container restarted successfully but remained in health:starting state. API broker shows not_connected. Manual intervention flagged.

[2026-03-28 12:13] Manual remediation session: Identified two root causes. (1) docker-compose.yml healthcheck used YAML folded scalar causing Python IndentationError on every health evaluation — fixed by rewriting test as CMD-SHELL list form. (2) Worker heartbeat key never written to Redis despite Redis being reachable — _heartbeat_client stays None at runtime due to unresolved startup exception; added PYTHONUNBUFFERED=1 for future diagnostics. (3) Alpaca API key unauthorized — needs manual rotation at https://app.alpaca.markets. Worker container recreated with fixed compose config. System remains DEGRADED pending Bug B and Alpaca key fix.

[2026-03-29 05:10] Auto health check: docker-worker-1 found unhealthy (Up 17h, health check failing — pre-existing Bug B). Applied Fix A (docker restart docker-worker-1). Container restarted but remained in health:starting with worker:heartbeat key absent from Redis — Bug B unresolved, Fix A ineffective for this root cause. broker:not_connected and scheduler:no_data persist (Alpaca key still unauthorized). Manual intervention still required for Bug B and Alpaca key rotation.
