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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
