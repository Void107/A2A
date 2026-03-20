"""
应用配置 —— 使用 pydantic-settings 做类型安全的环境变量管理。
比 os.getenv 的优势：启动时就校验类型和必填项，不会在运行时才炸。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── 数据库 ──
    DATABASE_URL: str  # 必填，启动时缺失直接报错

    # ── Redis ──
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── JWT ──
    JWT_SECRET: str  # 必填
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # ── Payload Guard（规范 §2.5） ──
    MAX_RESPONSE_BYTES: int = 5 * 1024 * 1024  # 5MB


# 全局单例 —— 整个应用 import 这一个实例即可
settings = Settings()
