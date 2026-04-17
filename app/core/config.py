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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
