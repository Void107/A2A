"""
全局 Redis 连接池（受控生命周期）。

🔴 与指南的关键区别：
   指南里直接 `redis_client = aioredis.from_url(...)` 放在模块顶层。
   问题：
   1. 模块导入时就创建连接，此时 event loop 可能还不存在
   2. 没有 shutdown 清理，连接泄露
   3. K8s 健康检查每秒 ping，如果每次新建连接会耗尽端口

   正确做法：用 startup/shutdown 事件管理生命周期，全模块共享同一个池。
"""

from __future__ import annotations

from typing import Optional

import redis.asyncio as aioredis

from app.config import settings

# 模块级变量，启动前是 None，startup 后被赋值
_pool: Optional[aioredis.Redis] = None


async def init_redis() -> None:
    """在 FastAPI startup 事件中调用，初始化连接池。"""
    global _pool
    _pool = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        max_connections=50,        # 连接池上限
        socket_connect_timeout=5,  # 连接超时 5 秒
        socket_keepalive=True,     # TCP keepalive，防止被防火墙断开
    )


async def close_redis() -> None:
    """在 FastAPI shutdown 事件中调用，优雅释放连接。"""
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None


def get_redis() -> aioredis.Redis:
    """
    获取全局 Redis 客户端。
    如果在 startup 之前调用会抛异常，属于编程错误，应立即修复。
    """
    if _pool is None:
        raise RuntimeError(
            "Redis 未初始化。请确保 init_redis() 在 FastAPI startup 中被调用。"
        )
    return _pool
