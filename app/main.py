"""
A2A-Contract-Hub 应用入口。

路由清单：
  POST /api/v1/auth/token         ← 换取 JWT
  POST /api/v1/agents/register    ← Agent 注册
  GET  /api/v1/agents/discover    ← 发现 Agent
  POST /api/v1/topics/publish     ← 广播发布
  GET  /api/v1/topics/subscribe   ← SSE 订阅
  POST /api/v1/interact/query     ← 跨 Agent 查询
  GET  /api/v1/audit/logs         ← 审计日志查询
  GET  /health                    ← 存活探针（K8s liveness）
  GET  /ready                     ← 就绪探针（K8s readiness）
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.api.agents import router as agents_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.query import router as query_router
from app.api.topics import router as topics_router
from app.core.redis_pool import close_redis, get_redis, init_redis
from app.database import AsyncSessionLocal
from app.services.audit_writer import audit_consumer_loop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    用 lifespan 替代已弃用的 on_event("startup"/"shutdown")。
    统一管理外部资源的初始化与清理。
    """
    # ── startup ──
    await init_redis()
    logger.info("Redis 连接池已初始化")

    audit_task = asyncio.create_task(audit_consumer_loop())
    logger.info("审计消费者已启动（Redis Stream → PostgreSQL）")
    logger.info("服务启动完成（请确保已执行 alembic upgrade head）")

    yield  # 应用运行中

    # ── shutdown ──
    audit_task.cancel()
    await close_redis()
    logger.info("Redis 连接池已关闭")


app = FastAPI(
    title="A2A-Contract-Hub",
    description="AI Agent 数据契约交换枢纽（v0.2.0）",
    version="0.2.0",
    lifespan=lifespan,
)

# ── 挂载所有路由 ──
app.include_router(auth_router)      # /api/v1/auth
app.include_router(agents_router)    # /api/v1/agents
app.include_router(topics_router)    # /api/v1/topics
app.include_router(query_router)     # /api/v1/interact
app.include_router(audit_router)     # /api/v1/audit


# ═══════════════════════════════════════════
#  健康探针
# ═══════════════════════════════════════════

@app.get("/health")
async def health():
    """存活探针：只要进程活着就返回 ok"""
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    """
    就绪探针：检查 PostgreSQL + Redis 都可达。
    🔴 复用全局 Redis 连接池的 ping()，不新建连接。
    """
    errors = []

    # 检查数据库
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        errors.append(f"PostgreSQL: {e}")

    # 检查 Redis（复用全局连接池，不 from_url 新建！）
    try:
        redis = get_redis()
        await redis.ping()
    except Exception as e:
        errors.append(f"Redis: {e}")

    if errors:
        return {"status": "not_ready", "errors": errors}
    return {"status": "ready"}
