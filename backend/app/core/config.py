from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    POSTGRES_USER: str = "scalistai"
    POSTGRES_PASSWORD: str = "scalistai_dev"
    POSTGRES_DB: str = "scalistai"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # development | production — en production un JWT_SECRET débil aborta el arranque
    ENVIRONMENT: str = "development"

    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # Login brute-force: N intentos por IP dentro de la ventana (0 = desactivado)
    LOGIN_RATE_LIMIT_MAX: int = 10
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 60

    STORAGE_DIR: str = "./storage"
    CORS_ORIGINS: str = "http://localhost:3000"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.strip().lower() in ("production", "prod")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
