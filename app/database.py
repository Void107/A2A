"""
异步数据库引擎与会话工厂。

生产级要点：
- 连接池参数显式配置，避免默认值在高并发下成为瓶颈
- expire_on_commit=False 防止 commit 后访问属性时触发隐式 IO
- get_db 作为 FastAPI Depends 注入，每个请求独享一个 session
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,           # 生产环境关闭 SQL 打印；调试时改 True
    pool_size=20,         # 连接池常驻连接数
    max_overflow=10,      # 突发流量时最多额外开 10 个连接
    pool_pre_ping=True,   # 每次取连接前 ping 一下，自动剔除断连
    pool_recycle=3600,    # 1 小时回收连接，避免被数据库侧超时断开
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """所有 ORM Model 的基类"""
    pass


async def get_db():
    """FastAPI 依赖注入：每个请求一个独立的数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
