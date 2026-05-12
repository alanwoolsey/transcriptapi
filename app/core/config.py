import json
from urllib.parse import quote_plus
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Transcript Parser API"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_allowed_origins: list[str] = ["*"]
    aws_region: str = "us-east-1"
    aws_profile: str | None = None
    aws_shared_credentials_file: str | None = None
    aws_config_file: str | None = None
    document_storage_backend: str = "local"
    document_storage_dir: str = ".document_storage"
    document_storage_bucket: str | None = None
    strands_enabled: bool = False
    strands_model_id: str = "us.amazon.nova-pro-v1:0"
    strands_temperature: float = 0.2
    strands_max_tokens: int = 4096
    cognito_user_pool_id: str | None = None
    cognito_app_client_id: str | None = None
    cognito_clock_skew_seconds: int = 60
    use_textract: bool = True
    use_bedrock: bool = True
    bedrock_model_id: str = "us.amazon.nova-2-lite-v1:0"
    bedrock_max_tokens: int = 4096
    bedrock_temperature: float = 0.0
    heuristic_min_char_count: int = 250
    heuristic_min_alpha_ratio: float = 0.55
    heuristic_min_line_count: int = 8
    heuristic_min_score: float = 0.65
    heuristic_parse_min_confidence: float = 0.75
    heuristic_course_min_confidence: float = 0.7
    heuristic_overall_min_confidence: float = 0.72
    heuristic_learning_enabled: bool = False
    heuristic_learning_dir: str = ".heuristics"
    max_upload_mb: int = 15
    upload_batch_max_workers: int = 4
    database_url: str | None = None
    database_secret_json: str | None = None
    database_host: str | None = None
    database_port: int = 5432
    database_name: str | None = None
    database_user: str | None = None
    database_password: str | None = None
    run_db_migrations_on_startup: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def resolved_database_url(self) -> str | None:
        if self.database_url:
            return self.database_url

        host = self.database_host
        port = self.database_port
        name = self.database_name
        user = self.database_user
        password = self.database_password

        if self.database_secret_json:
            secret = json.loads(self.database_secret_json)
            host = secret.get("host", host)
            port = int(secret.get("port", port or 5432))
            name = secret.get("dbname", name)
            user = secret.get("username", user)
            password = secret.get("password", password)

        if not all([host, port, name, user, password]):
            return None

        return f"postgresql+psycopg://{quote_plus(str(user))}:{quote_plus(str(password))}@{host}:{port}/{quote_plus(str(name))}"


settings = Settings()


def heuristic_learning_path() -> Path:
    return Path(settings.heuristic_learning_dir).resolve()
