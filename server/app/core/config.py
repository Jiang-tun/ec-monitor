from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    app_name: str = "ecom-monitor"
    app_env: str = "dev"
    debug: bool = False
    secret_key: str = "change-me-in-prod"
    access_token_expire_min: int = 720

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "ecom"
    mysql_password: str = "ecom123"
    mysql_db: str = "ecom_monitor"

    redis_url: str = "redis://127.0.0.1:6379/0"

    scheduler_tick_sec: int = 10
    scheduler_enabled: bool = True
    queue_lag_threshold: int = 500
    scheduler_leader_ttl: int = 30
    dead_threshold: int = 3

    node_api_key: str = "dev-node-api-key"
    crypto_key_id: str = "v1"

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}"
            "?charset=utf8mb4"
        )

    @property
    def redis_url_compat(self) -> str:
        """强制 RESP2：兼容不支持 HELLO 握手的旧版 Redis。"""
        if "protocol=" in self.redis_url:
            return self.redis_url
        sep = "&" if "?" in self.redis_url else "?"
        return f"{self.redis_url}{sep}protocol=2"


@lru_cache
def get_settings() -> Settings:
    return Settings()
