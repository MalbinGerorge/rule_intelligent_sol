"""
Application settings, loaded from environment variables / .env.

Postgres connection is built from individual POSTGRES_* parts (host,
port, username, password, db name) rather than one raw DSN string, so
special characters in the password (@, :, *, etc.) are safely
URL-encoded rather than breaking the connection string.

QRADAR_* variables are only needed once ingestion services (subtask 2)
are implemented — per-customer QRadar host/token live in the
`customers` / `customer_credentials` tables, not here, since this is
multi-tenant.
"""
from urllib.parse import quote_plus

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

    postgres_username: str = "qradar"
    postgres_password: str = "qradar"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db_name: str = "rule_intelligent_sol"
    # used to encrypt/decrypt customer_credentials.token_encrypted via
    # Postgres pgcrypto (pgp_sym_encrypt/pgp_sym_decrypt). Change this in
    # every real environment — never use the default outside local dev.
    token_encryption_key: str = "change-me-dev-only"

    qradar_api_version: str = "20.0"
    # Neo4j — matches docker-compose.yml's default credentials for local
    # dev. Same rule as everything else here: change neo4j_password
    # before running against anything beyond your own machine.
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "Sillywilly79**"

    # Azure OpenAI — used by the AI/agentic layer (natural language ->
    # Cypher). Never hardcode these; always via .env. deployment_name
    # is the Azure DEPLOYMENT name you configured, not necessarily the
    # literal model name.
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = ""

    azure_openai_endpoint_4o: str = ""
    azure_openai_api_key_4o: str = ""
    azure_openai_deployment_4o: str = ""
    azure_openai_api_version_4o: str = ""
    redis_url: str = "redis://localhost:6379/0"
    @computed_field
    @property
    def pg_dsn(self) -> str:
        user = quote_plus(self.postgres_username)
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db_name}"
        )


settings = Settings()