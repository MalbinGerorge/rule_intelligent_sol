"""
Application settings, loaded from environment variables / .env.

Postgres and Redis connection URLs are built from individual parts
(host, port, username, password, db) rather than one raw DSN string, so
special characters in the password (@, :, *, etc.) are safely
URL-encoded rather than breaking the connection string.

Secrets have NO defaults: a missing POSTGRES_PASSWORD, NEO4J_PASSWORD,
REDIS_PASSWORD or TOKEN_ENCRYPTION_KEY fails at startup instead of
silently falling back to a value that's committed to a public repo.
They're SecretStr so they never show up in logs, reprs or tracebacks --
call .get_secret_value() only at the point of use.

Outside ENVIRONMENT=development, known placeholder or short secrets are
rejected at startup too.

Per-customer QRadar host/token live in the `customers` /
`customer_credentials` tables, not here, since this is multi-tenant.
"""

from urllib.parse import quote_plus

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SECRET_LENGTH = 16
KNOWN_WEAK_SECRETS = {
    "",
    "change-me",
    "change-me-dev-only",
    "changeme",
    "password",
    "postgres",
    "neo4j",
    "qradar",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"
    chroma_host: str = "localhost"
    chroma_port: int = 8001

    postgres_username: str = "postgres"
    postgres_password: SecretStr
    postgres_host: str = "localhost"
    postgres_port: int = 5434
    postgres_db_name: str = "rule_intelligent_sol"
    # used to encrypt/decrypt customer_credentials.token_encrypted via
    # Postgres pgcrypto (pgp_sym_encrypt/pgp_sym_decrypt). Changing it
    # makes every stored QRadar token undecryptable unless they're
    # re-encrypted with the new key first.
    token_encryption_key: SecretStr

    qradar_api_version: str = "20.0"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: SecretStr

    # Azure OpenAI — used by the AI/agentic layer. deployment is the
    # Azure DEPLOYMENT name you configured, not necessarily the literal
    # model name.
    azure_openai_endpoint: str = ""
    azure_openai_api_key: SecretStr = SecretStr("")
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = ""

    azure_openai_endpoint_4o: str = ""
    azure_openai_api_key_4o: SecretStr = SecretStr("")
    azure_openai_deployment_4o: str = ""
    azure_openai_api_version_4o: str = ""

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: SecretStr

    @model_validator(mode="after")
    def _reject_weak_secrets_outside_dev(self) -> "Settings":
        if self.environment == "development":
            return self
        weak = [
            name
            for name in (
                "postgres_password",
                "neo4j_password",
                "redis_password",
                "token_encryption_key",
            )
            if (value := getattr(self, name).get_secret_value()).lower() in KNOWN_WEAK_SECRETS
            or len(value) < MIN_SECRET_LENGTH
        ]
        if weak:
            raise ValueError(
                f"Weak or placeholder secrets are not allowed when ENVIRONMENT={self.environment!r}: "
                f"{', '.join(weak)} (minimum length {MIN_SECRET_LENGTH})"
            )
        return self

    # Plain properties, not computed fields: these embed the password, so
    # they must never appear in the settings model's repr or model_dump().
    @property
    def pg_dsn(self) -> str:
        user = quote_plus(self.postgres_username)
        password = quote_plus(self.postgres_password.get_secret_value())
        return (
            f"postgresql://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db_name}"
        )

    @property
    def redis_url(self) -> str:
        password = quote_plus(self.redis_password.get_secret_value())
        return f"redis://:{password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"


settings = Settings()
