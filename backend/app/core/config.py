from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    POSTGRES_USER: str = "scalistai"
    POSTGRES_PASSWORD: str = "scalistai_dev"
    POSTGRES_DB: str = "scalistai"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    STORAGE_DIR: str = "./storage"
    CORS_ORIGINS: str = "http://localhost:3000"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # --- ML Detection ---
    # Path al checkpoint del modelo entrenado por scripts/train_model.py sobre
    # las variaciones sintéticas generadas a partir de los planos del usuario.
    # Si el archivo no existe el detector ML queda deshabilitado y el sistema
    # usa solo la detección clásica.
    ML_MODEL_PATH: str = "./storage/models/scalistai_seg_v1.pt"
    # Encender / apagar el detector ML aunque el modelo esté presente.
    ENABLE_ML_DETECTION: bool = True
    # Device para PyTorch: "auto" detecta CUDA si está, sino CPU.
    ML_DEVICE: str = "auto"
    # Cuando un usuario activa un proyecto y consintió `allow_training_data`,
    # generamos automáticamente variaciones sintéticas para el corpus de
    # entrenamiento. Si está False, el snapshot automático queda apagado y
    # solo se generan variaciones vía el endpoint manual.
    AUTO_GENERATE_TRAINING_DATA: bool = True
    # Directorio con el dataset PROCEDURAL (planos inventados por código, ver
    # scripts/gen_procedural.py). Va SOLO al train, nunca al holdout/val. Si el
    # directorio existe y tiene samples, el training (UI y CLI) lo incluye.
    PROCEDURAL_DATA_DIR: str = "storage/procedural"

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
