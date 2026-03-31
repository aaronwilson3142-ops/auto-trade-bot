"""
Production secrets management for APIS.

Provides a ``SecretManager`` abstraction so all code accesses secrets through
a single consistent interface regardless of the runtime environment.

Environment mapping
-------------------
  development / staging  →  ``EnvSecretManager``  (env vars; zero extra deps)
  production             →  ``AWSSecretManager``  (AWS Secrets Manager scaffold)

Usage
-----
    from config.secrets import get_secret_manager

    sm = get_secret_manager(env="development")
    api_key = sm.get("ALPACA_API_KEY")
    optional_val = sm.get_optional("SOME_SECRET", default="")

Security properties
-------------------
- Secrets are never logged.
- ``EnvSecretManager.get()`` raises ``KeyError`` when the variable is absent
  or empty, preventing accidentally passing empty strings as credentials.
- ``AWSSecretManager`` is a scaffold — it raises ``NotImplementedError``
  until implemented with ``boto3``.

Spec references
---------------
- APIS_MASTER_SPEC.md §3.4 — Auditability (all secrets flow into the system
  through a traceable, validated path)
- 04_APIS_BUILD_RUNBOOK.md §3 (config and environment strategy)
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod

from config.settings import Environment

# Implementation guidance for operators extending the AWS scaffold
_AWS_NOT_IMPL_MSG = (
    "AWSSecretManager is a scaffold.  Install boto3 and implement as follows:\n"
    "\n"
    "    import boto3, json\n"
    "    client = boto3.client('secretsmanager', region_name=self._region)\n"
    "    resp = client.get_secret_value(SecretId=self._secret_name)\n"
    "    secrets = json.loads(resp['SecretString'])\n"
    "    if key not in secrets:\n"
    "        raise KeyError(f\"Key '{key}' not found in secret '{self._secret_name}'\")\n"
    "    return secrets[key]\n"
    "\n"
    "Tip: cache the parsed JSON dict in self._cache after first fetch to avoid "
    "repeated AWS API calls."
)


class SecretManager(ABC):
    """Abstract interface for secret retrieval.

    All concrete implementations must override ``get()``.
    ``get_optional()`` is provided as a concrete helper built on top of ``get()``.
    """

    @abstractmethod
    def get(self, key: str) -> str:
        """Retrieve a required secret by key.

        Args:
            key: Secret identifier (e.g. environment variable name or JSON key).

        Returns:
            The secret value as a string.

        Raises:
            KeyError: If the secret is not found or is empty.
        """
        ...

    def get_optional(self, key: str, default: str = "") -> str:
        """Retrieve a secret, returning ``default`` if not found.

        Args:
            key:     Secret identifier.
            default: Value to return when the secret is absent (default: ``""``)

        Returns:
            The secret value, or ``default`` if the secret is not found.
        """
        try:
            return self.get(key)
        except KeyError:
            return default


class EnvSecretManager(SecretManager):
    """Reads secrets from OS environment variables.

    Suitable for:
    - Local development (secrets loaded from ``.env`` via Docker or direnv)
    - CI/CD pipelines with injected env vars
    - Kubernetes with environment variables backed by Kubernetes Secrets

    Security note: This implementation deliberately raises ``KeyError`` for
    absent or empty environment variables to prevent silent credential
    misconfigurations.
    """

    def get(self, key: str) -> str:
        """Read ``key`` from the OS environment.

        Args:
            key: Environment variable name (case-sensitive on Linux/macOS).

        Returns:
            The environment variable value.

        Raises:
            KeyError: If the variable is not set or is an empty string.
        """
        value = os.environ.get(key)
        if not value:
            raise KeyError(
                f"Secret '{key}' not found in environment variables. "
                f"Ensure the variable is set before starting the service."
            )
        return value


class AWSSecretManager(SecretManager):
    """Concrete AWS Secrets Manager implementation using boto3.

    All secrets are expected to be stored as a single JSON object under one
    secret name (e.g. ``apis/production/secrets``).  The JSON blob is fetched
    once on first access and cached in memory for the lifetime of this object,
    avoiding repeated ``GetSecretValue`` API calls.

    IAM permissions required for the executing role/user::

        secretsmanager:GetSecretValue on arn:aws:secretsmanager:<region>:<acct>:secret:<name>

    Args:
        secret_name: AWS Secrets Manager secret name or ARN.
        region_name: AWS region where the secret is stored.
    """

    def __init__(
        self,
        secret_name: str = "apis/production/secrets",
        region_name: str = "us-east-1",
    ) -> None:
        self._secret_name = secret_name
        self._region = region_name
        self._cache: dict[str, str] = {}

    @property
    def secret_name(self) -> str:
        return self._secret_name

    @property
    def region_name(self) -> str:
        return self._region

    def get(self, key: str) -> str:
        """Retrieve a secret from AWS Secrets Manager.

        On first call, fetches and parses the entire JSON secret blob and
        caches it in memory.  Subsequent calls read from the in-memory cache.

        Args:
            key: JSON field name within the secret object.

        Returns:
            The secret value string.

        Raises:
            KeyError: When the key is not present in the secret JSON.
            RuntimeError: If boto3 is unavailable or AWS credentials are missing.
        """
        if not self._cache:
            self._cache = self._fetch_from_aws()

        if key not in self._cache:
            raise KeyError(
                f"Key '{key}' not found in AWS secret '{self._secret_name}'. "
                f"Available keys: {sorted(self._cache.keys())}"
            )
        return self._cache[key]

    def _fetch_from_aws(self) -> dict[str, str]:
        """Fetch and parse the secret JSON blob from AWS Secrets Manager."""
        try:
            import boto3  # type: ignore[import]
            import json
        except ImportError as exc:
            raise RuntimeError(
                "boto3 is required for AWSSecretManager. "
                "Install it with: pip install boto3"
            ) from exc

        try:
            client = boto3.client("secretsmanager", region_name=self._region)
            resp = client.get_secret_value(SecretId=self._secret_name)
        except Exception as exc:
            # Re-raise with a clear message — never swallow AWS credential errors
            raise RuntimeError(
                f"Failed to fetch secret '{self._secret_name}' from AWS "
                f"Secrets Manager (region={self._region}): {exc}"
            ) from exc

        secret_string = resp.get("SecretString")
        if not secret_string:
            raise RuntimeError(
                f"AWS secret '{self._secret_name}' has no SecretString payload.  "
                "Binary secrets are not supported."
            )

        try:
            import json
            parsed = json.loads(secret_string)
        except Exception as exc:
            raise RuntimeError(
                f"AWS secret '{self._secret_name}' is not valid JSON: {exc}"
            ) from exc

        if not isinstance(parsed, dict):
            raise RuntimeError(
                f"AWS secret '{self._secret_name}' must be a JSON object (dict), "
                f"got {type(parsed).__name__}."
            )

        return {str(k): str(v) for k, v in parsed.items()}

    def invalidate_cache(self) -> None:
        """Force the next ``get()`` call to re-fetch from AWS.

        Use this after secret rotation to pick up the new values without
        restarting the process.
        """
        self._cache = {}


def get_secret_manager(env: str | Environment = "development") -> SecretManager:
    """Factory that returns the appropriate ``SecretManager`` for the environment.

    Args:
        env: Environment name string or ``Environment`` enum value.
             - ``"development"`` or ``"staging"``  →  ``EnvSecretManager``
             - ``"production"``                     →  ``AWSSecretManager``

    Returns:
        A ``SecretManager`` instance appropriate for the requested environment.
    """
    env_str = env.value if isinstance(env, Environment) else str(env)
    if env_str == Environment.PRODUCTION.value:
        return AWSSecretManager()
    return EnvSecretManager()
