import json
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Transcript Parser API"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    aws_region: str = "us-east-1"
    aws_profile: str | None = None
    aws_shared_credentials_file: str | None = None
    aws_config_file: str | None = None
    use_textract: bool = True
    use_bedrock: bool = True
    bedrock_model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    heuristic_min_char_count: int = 250
    heuristic_min_alpha_ratio: float = 0.55
    heuristic_min_line_count: int = 8
    heuristic_min_score: float = 0.65
    max_upload_mb: int = 15
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
