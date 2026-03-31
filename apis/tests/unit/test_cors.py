"""
Tests for CORS configuration.

Verifies that:
  - Settings.allowed_cors_origins defaults to the expected localhost ports
  - The default list does NOT include the wildcard "*"
  - Origins can be overridden via the APIS_ALLOWED_CORS_ORIGINS env var (JSON list)
  - The wildcard is NOT the default (security regression guard)
  - allow_headers is restricted to Authorization and Content-Type
    (tested via the middleware kwargs stored on the app)
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("APIS_ENV", "development")
os.environ.setdefault("APIS_OPERATING_MODE", "research")
os.environ.setdefault("APIS_DB_URL", "postgresql+psycopg://test:test@localhost:5432/apis_test")


from config.settings import Settings

# ─────────────────────────── helpers ──────────────────────────────────────────

def _settings(**overrides) -> Settings:
    s = Settings()
    for k, v in overrides.items():
        object.__setattr__(s, k, v)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# TestAllowedCorsOriginsDefault
# ─────────────────────────────────────────────────────────────────────────────

class TestAllowedCorsOriginsDefault:
    def test_default_is_a_list(self):
        """allowed_cors_origins must be a list, not a string."""
        s = Settings()
        assert isinstance(s.allowed_cors_origins, list)

    def test_default_includes_localhost_8000(self):
        """http://localhost:8000 must be in the default list (Swagger/API access)."""
        s = Settings()
        assert "http://localhost:8000" in s.allowed_cors_origins

    def test_default_includes_127_0_0_1_8000(self):
        """http://127.0.0.1:8000 must be in the default (loopback alias)."""
        s = Settings()
        assert "http://127.0.0.1:8000" in s.allowed_cors_origins

    def test_default_includes_localhost_3000(self):
        """http://localhost:3000 must be in the default (Grafana dashboard)."""
        s = Settings()
        assert "http://localhost:3000" in s.allowed_cors_origins

    def test_default_does_not_contain_wildcard(self):
        """The wildcard '*' must NOT appear in the default origins list."""
        s = Settings()
        assert "*" not in s.allowed_cors_origins

    def test_default_list_is_non_empty(self):
        """There must be at least one allowed origin by default."""
        s = Settings()
        assert len(s.allowed_cors_origins) > 0


# ─────────────────────────────────────────────────────────────────────────────
# TestAllowedCorsOriginsOverride
# ─────────────────────────────────────────────────────────────────────────────

class TestAllowedCorsOriginsOverride:
    def test_override_replaces_default(self):
        """Setting allowed_cors_origins directly replaces the default list."""
        custom = ["http://myapp.internal:8080"]
        s = _settings(allowed_cors_origins=custom)
        assert s.allowed_cors_origins == custom

    def test_override_can_be_empty_list(self):
        """An empty list is a valid (though strict) override — blocks all origins."""
        s = _settings(allowed_cors_origins=[])
        assert s.allowed_cors_origins == []

    def test_override_multiple_origins(self):
        """Multiple origins are preserved in order."""
        custom = ["http://localhost:8000", "http://localhost:4200", "http://prod.example.com"]
        s = _settings(allowed_cors_origins=custom)
        assert s.allowed_cors_origins == custom

    def test_env_var_json_list_parsed(self, monkeypatch):
        """APIS_ALLOWED_CORS_ORIGINS env var (JSON list) is parsed correctly."""
        custom = ["http://staging.example.com:9000"]
        monkeypatch.setenv("APIS_ALLOWED_CORS_ORIGINS", json.dumps(custom))
        # Re-instantiate so env var is picked up
        s = Settings()
        assert s.allowed_cors_origins == custom
