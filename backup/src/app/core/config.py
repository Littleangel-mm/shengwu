from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Research Platform API"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_reload: bool = False
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    docs_enabled: bool = True
    app_secret: SecretStr = SecretStr("development-only-change-me")
    access_token_expire_minutes: int = Field(default=720, ge=5, le=43200)
    allow_actor_header: bool = True

    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_user: str = "research_app"
    db_password: SecretStr = SecretStr("")
    db_name: str = "research_platform"
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=200)

    storage_root: Path = Path("data")
    max_upload_size_mb: int = Field(default=200, ge=1, le=2048)
    allowed_extensions: str = "pdf,docx,txt,md,xlsx,xls,zip"
    zip_max_entries: int = Field(default=500, ge=1, le=5000)
    zip_max_uncompressed_mb: int = Field(default=1000, ge=1, le=10240)
    zip_max_compression_ratio: float = Field(default=100, ge=1, le=10000)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    worker_poll_seconds: float = Field(default=2.0, ge=0.2, le=60)
    worker_batch_size: int = Field(default=1, ge=1, le=20)
    ocr_enabled: bool = True
    ocr_python: Path = Path(".venv-ocr/Scripts/python.exe")
    ocr_detection_model_name: str = "PP-OCRv5_mobile_det"
    ocr_recognition_model_name: str = "PP-OCRv5_mobile_rec"
    ocr_detection_model_dir: Path = Path("models/paddleocr/PP-OCRv5_mobile_det")
    ocr_recognition_model_dir: Path = Path("models/paddleocr/PP-OCRv5_mobile_rec")
    ocr_dpi: int = Field(default=200, ge=120, le=400)
    ocr_min_confidence: float = Field(default=0.5, ge=0, le=1)
    ocr_timeout_seconds: int = Field(default=1800, ge=30, le=7200)
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_model: str = "deepseek-chat"

    @field_validator("api_v1_prefix")
    @classmethod
    def normalize_api_prefix(cls, value: str) -> str:
        value = "/" + value.strip("/")
        return value.rstrip("/")

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg2",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )

    @property
    def allowed_extension_set(self) -> set[str]:
        return {
            item.strip().lower().lstrip(".")
            for item in self.allowed_extensions.split(",")
            if item.strip()
        }

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @model_validator(mode="after")
    def validate_production_secret(self) -> "Settings":
        if (
            self.app_env.lower() == "production"
            and self.app_secret.get_secret_value() == "development-only-change-me"
        ):
            raise ValueError("APP_SECRET must be configured in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
