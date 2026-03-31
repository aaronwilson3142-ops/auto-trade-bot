"""
Tests for the operator bearer-token authentication dependency.

Covers require_operator_token() in apps.api.deps without requiring a running
FastAPI app or the fastapi[testclient] extras — only the dependency logic itself
is exercised here via direct calls.

Tests verify:
  - Returns 503 when APIS_OPERATOR_TOKEN is not configured (empty string)
  - Returns 401 when the wrong token is supplied
  - Returns 401 when no token is supplied at all
  - Passes silently when the correct token is supplied
  - Token comparison is NOT case-sensitive bypass (wrong case → 401)
  - Token comparison is NOT whitespace-bypass (extra space → 401)
"""
from __future__ import annotations

import os
import pytest

os.environ.setdefault("APIS_ENV", "development")
os.environ.setdefault("APIS_OPERATING_MODE", "research")
os.environ.setdefault("APIS_DB_URL", "postgresql+psycopg://test:test@localhost:5432/apis_test")


from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from apps.api.deps import require_operator_token, _token_matches
from config.settings import Settings


# ─────────────────────────── helpers ─────────────────────────────────────────

def _settings(**overrides) -> Settings:
    s = Settings()
    for k, v in overrides.items():
        object.__setattr__(s, k, v)
    return s


def _creds(token: str) -> HTTPAuthorizationCredentials:
    """Build a mock HTTPAuthorizationCredentials carrying the given token."""
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _call(token_setting: str, provided_token: str | None) -> None:
    """Invoke require_operator_token with the given configuration.

    Raises HTTPException on auth failure; returns None on success.
    """
    settings = _settings(operator_token=token_setting)
    creds = _creds(provided_token) if provided_token is not None else None
    require_operator_token(credentials=creds, settings=settings)


# ─────────────────────────────────────────────────────────────────────────────
# TestTokenMatches — unit tests for the constant-time comparison helper
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenMatches:
    def test_equal_tokens_match(self):
        assert _token_matches("secret", "secret") is True

    def test_different_tokens_do_not_match(self):
        assert _token_matches("secret", "wrong") is False

    def test_empty_strings_match(self):
        assert _token_matches("", "") is True

    def test_case_sensitive(self):
        assert _token_matches("Secret", "secret") is False

    def test_extra_whitespace_does_not_match(self):
        assert _token_matches("secret", "secret ") is False


# ─────────────────────────────────────────────────────────────────────────────
# TestRequireOperatorToken
# ─────────────────────────────────────────────────────────────────────────────

class TestRequireOperatorToken:
    def test_returns_503_when_token_not_configured(self):
        """Empty operator_token → 503 (misconfigured, not unauthorized)."""
        with pytest.raises(HTTPException) as exc_info:
            _call(token_setting="", provided_token="anything")
        assert exc_info.value.status_code == 503

    def test_returns_401_when_wrong_token(self):
        """Valid token configured, wrong token provided → 401."""
        with pytest.raises(HTTPException) as exc_info:
            _call(token_setting="my-secret", provided_token="wrong-token")
        assert exc_info.value.status_code == 401

    def test_returns_401_when_no_token_provided(self):
        """Valid token configured, no credentials at all → 401."""
        with pytest.raises(HTTPException) as exc_info:
            _call(token_setting="my-secret", provided_token=None)
        assert exc_info.value.status_code == 401

    def test_passes_with_correct_token(self):
        """Correct token provided → returns None (no exception)."""
        result = _call(token_setting="my-secret", provided_token="my-secret")
        assert result is None

    def test_returns_401_with_wrong_case(self):
        """Token comparison is case-sensitive."""
        with pytest.raises(HTTPException) as exc_info:
            _call(token_setting="MySecret", provided_token="mysecret")
        assert exc_info.value.status_code == 401

    def test_returns_401_with_extra_whitespace(self):
        """Token with extra trailing space does not match."""
        with pytest.raises(HTTPException) as exc_info:
            _call(token_setting="my-secret", provided_token="my-secret ")
        assert exc_info.value.status_code == 401

    def test_401_includes_www_authenticate_header(self):
        """401 responses must include WWW-Authenticate: Bearer for RFC 6750 compliance."""
        with pytest.raises(HTTPException) as exc_info:
            _call(token_setting="my-secret", provided_token="wrong")
        assert exc_info.value.headers is not None
        assert "WWW-Authenticate" in exc_info.value.headers
        assert exc_info.value.headers["WWW-Authenticate"] == "Bearer"

    def test_503_detail_mentions_env_var(self):
        """503 detail should mention APIS_OPERATOR_TOKEN so operators know what to set."""
        with pytest.raises(HTTPException) as exc_info:
            _call(token_setting="", provided_token=None)
        assert "APIS_OPERATOR_TOKEN" in exc_info.value.detail

    def test_long_token_handled_correctly(self):
        """A 64-char token works end-to-end."""
        long_token = "a" * 64
        result = _call(token_setting=long_token, provided_token=long_token)
        assert result is None

    def test_token_with_special_chars(self):
        """Tokens containing hyphens, underscores, dots are accepted."""
        token = "prod-token_v2.0"
        result = _call(token_setting=token, provided_token=token)
        assert result is None
