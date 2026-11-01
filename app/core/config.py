"""Application settings, loaded from environment variables with the ``MC_`` prefix."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Every field can be overridden with an environment variable, e.g.
    ``MC_DATABASE_URL`` or ``MC_MAX_PATHS``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MC_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "MonteCarlo Lab API"
    environment: str = "local"
    log_level: str = "INFO"
    cors_origins: list[str] = ["*"]

    database_url: str = "postgresql+psycopg://montecarlo:montecarlo@localhost:5432/montecarlo"

    # Workload guards: protect a single request from exhausting CPU or memory.
    max_paths: int = 20_000
    max_steps: int = 5_000
    max_cells: int = 2_500_000  # n_paths * n_steps

    # ETL guards.
    max_upload_bytes: int = 10 * 1024 * 1024
    max_dataset_rows: int = 200_000


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""
    return Settings()
