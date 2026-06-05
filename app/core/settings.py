from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _get_env(name: str, default: str = "") -> str:
    import os

    return os.getenv(name, default).strip()


def _get_int_env(name: str, default: int) -> int:
    value = _get_env(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_cors_origins() -> list[str]:
    raw = _get_env("CORS_ORIGINS", "*")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or ["*"]


@dataclass(frozen=True)
class Settings:
    app_name: str = _get_env("APP_NAME", "Personal Chief API")
    app_description: str = _get_env("APP_DESCRIPTION", "AI personal chef assistant")
    app_version: str = _get_env("APP_VERSION", "0.1.0")
    host: str = _get_env("HOST", "127.0.0.1")
    port: int = _get_int_env("PORT", 8001)
    cors_origins: tuple[str, ...] = tuple(_get_cors_origins())

    model_name: str = _get_env("MODEL_NAME", "qwen3.6-plus")
    model_provider: str = _get_env("MODEL_PROVIDER", "openai")
    dashscope_api_key: str = _get_env("DASHSCOPE_API_KEY")
    base_url: str = _get_env("BASE_URL")
    tavily_api_key: str = _get_env("TAVILY_API_KEY")

    oss_region: str = _get_env("OSS_REGION", "cn-beijing")
    oss_endpoint: str = _get_env("OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com")
    oss_bucket: str = _get_env("OSS_BUCKET")
    oss_presign_expires_seconds: int = _get_int_env("OSS_PRESIGN_EXPIRES_SECONDS", 3600)

    database_dir: Path = Path(_get_env("DATABASE_DIR", "database"))
    memory_db_path: Path = database_dir / _get_env("MEMORY_DB_NAME", "memory.db")
    chef_memory_db_path: Path = database_dir / _get_env("CHEF_MEMORY_DB_NAME", "chef_memory.db")

    @property
    def llm_ready(self) -> bool:
        return bool(self.dashscope_api_key and self.base_url)

    @property
    def search_ready(self) -> bool:
        return bool(self.tavily_api_key)

    @property
    def oss_ready(self) -> bool:
        return bool(self.oss_bucket)


settings = Settings()
