from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Video Analyzer API"
    
    # Database
    DATABASE_URL: str
    
    # Redis / Celery
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str
    
    # MinIO
    MINIO_ENDPOINT: str
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_SECURE: bool = False
    MINIO_BUCKET_NAME: str
    
    # APIs
    NVIDIA_API_KEY: str
    OPENROUTER_API_KEY: str

    # JWT Authentication
    JWT_SECRET_KEY: str = "9a7f34c2ee10915f019b8ea03d77d70409a63fc6522c03848b813fdc7e1919b2"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 1 day

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

