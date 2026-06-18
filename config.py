from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_NAME: str = "KYC Pipeline"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # Security
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/kyc_pipeline"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # AWS
    AWS_REGION: str = "ap-south-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET_NAME: str = "loanflow-kyc-documents"

    # Cross-service
    LOAN_SERVICE_URL: str = "http://localhost:8000"
    LOAN_SERVICE_TIMEOUT: int = 5

    # Feature Flags
    USE_AWS_S3: bool = False
    USE_REAL_OCR: bool = False

    # Upload limits
    MAX_FILE_SIZE_MB: int = 5
    ALLOWED_EXTENSIONS: str = "pdf,jpg,jpeg,png"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False
    )

    @property
    def allowed_extensions_list(self) -> list[str]:
        return [e.strip().lower() for e in self.ALLOWED_EXTENSIONS.split(",")]

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

