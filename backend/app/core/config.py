"""Application configuration.

Secrets resolution per environment:

  local              → env vars injected directly by docker-compose (no AWS call)
  dev / staging / prod → JSON secret pulled from AWS Secrets Manager at startup,
                         then merged into os.environ before Settings is instantiated.

AWS Secrets Manager secret name: ``uscheduler/{ENVIRONMENT}/app``
Expected secret format (JSON string):
  {
    "DATABASE_URL":               "postgresql+asyncpg://...",
    "REDIS_URL":                  "redis://...",
    "SECRET_KEY":                 "<32+ random bytes, hex>",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "30",
    "ALLOWED_ORIGINS":            "[\"https://app.example.com\"]"
  }

The ECS task role must have ``secretsmanager:GetSecretValue`` on that secret ARN.
"""

import json
import os

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_aws_secrets() -> None:
    """Pull the environment's secret from AWS Secrets Manager and inject into os.environ.

    Runs once at module import time. No-op when ENVIRONMENT=local or TESTING=true.
    Any key already present in os.environ takes precedence (ECS task-level overrides).
    """
    environment = os.getenv("ENVIRONMENT", "local")
    if environment == "local" or os.getenv("TESTING", "").lower() == "true":
        return

    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError as exc:
        raise RuntimeError(
            "boto3 is required in non-local environments. "
            "Add the [aws] extra: pip install 'uscheduler[aws]'"
        ) from exc

    secret_name = f"uscheduler/{environment}/app"
    region = os.getenv("AWS_REGION", "us-east-1")

    client = boto3.client("secretsmanager", region_name=region)
    try:
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError as exc:
        raise RuntimeError(
            f"Failed to load secrets from AWS Secrets Manager "
            f"(secret={secret_name!r}, region={region!r}): {exc}"
        ) from exc

    for key, value in json.loads(response["SecretString"]).items():
        # setdefault: env vars already in the process (e.g. ECS task overrides) win
        os.environ.setdefault(key, str(value))


_load_aws_secrets()


class Settings(BaseSettings):
    # No env_file — secrets come from the process environment only.
    model_config = SettingsConfigDict(extra="ignore")

    # Required fields — missing values raise a clear Pydantic validation error at startup.
    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str

    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ENVIRONMENT: str = "local"
    LOG_LEVEL: str = "INFO"
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # Set to true in test fixtures; disables AWS SM call (handled above).
    TESTING: bool = False

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_must_be_strong(cls, v: str) -> str:
        if os.getenv("ENVIRONMENT", "local") != "local" and len(v) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters in non-local environments"
            )
        return v


settings = Settings()
