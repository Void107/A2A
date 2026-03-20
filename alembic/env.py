"""
Alembic 迁移环境 —— 异步版本。

关键点：
1. 从 app.config 读取 DATABASE_URL，保证和应用使用同一个数据源
2. 使用 asyncpg 异步驱动跑迁移，和运行时引擎一致
3. 导入所有 Model 让 autogenerate 能发现表结构变更
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Alembic Config 对象 ──
config = context.config

# 配置 Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── 从 app.config 读取数据库 URL ──
from app.config import settings

# 将 async URL 设到 alembic config 里，供下面的引擎工厂使用
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# ── 导入所有 Model，让 autogenerate 能检测到表结构 ──
from app.database import Base
from app.models.schemas import Agent, ContractHistory, AuditLog  # noqa: F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 脚本，不实际连库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """在已有连接上执行迁移。"""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """异步在线模式：用 asyncpg 引擎执行迁移。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """在线模式入口 —— 桥接 sync Alembic 和 async engine。"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
