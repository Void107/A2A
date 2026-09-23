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
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.adapters.opa import OPAClient
from app.adapters.presidio import PresidioClient
from app.adapters.upstream import UpstreamClient, Endpoint
from app.core.signing import Signer
from app.api.delivery import router as delivery_router
from app.api.contracts import router as contracts_router
from app.api.admin import router as admin_router
from app.api.receipts import router as receipts_router
from app.api.agents import router as agents_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.query import router as query_router
from app.api.topics import router as topics_router
from app.core.redis_pool import close_redis, get_redis, init_redis
from app.database import AsyncSessionLocal
from app.services.receipts import consumer_loop as audit_consumer_loop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    用 lifespan 替代已弃用的 on_event("startup"/"shutdown")。
    统一管理外部资源的初始化与清理。
    """
    # ── startup ──
    app.state.opa = OPAClient(settings.OPA_URL)
    app.state.presidio = PresidioClient(settings.PRESIDIO_URL) if settings.PRESIDIO_URL else None
    app.state.upstream = UpstreamClient({k: Endpoint(**v) for k, v in settings.UPSTREAM_ENDPOINTS.items()},
        Signer.from_file(settings.HUB_SIGNING_KEY_FILE, settings.HUB_SIGNING_KEY_ID)) if settings.HUB_SIGNING_KEY_FILE else None
    await init_redis()
    logger.info("Redis 连接池已初始化")

    audit_task = asyncio.create_task(audit_consumer_loop())
    logger.info("审计消费者已启动（PostgreSQL outbox → audit）")
    logger.info("服务启动完成（请确保已执行 alembic upgrade head）")

    try:
        yield
    finally:
        audit_task.cancel()
        with suppress(asyncio.CancelledError):
            await audit_task
        await close_redis()
        await app.state.opa.close()
        if app.state.upstream is not None:
            await app.state.upstream.close()
        if app.state.presidio is not None:
            await app.state.presidio.close()
    logger.info("Redis 连接池已关闭")


app = FastAPI(
    title="A2A-Contract-Hub",
    description="受控数据契约执行层（alpha 开发中）",
    version="0.3.0-alpha",
    lifespan=lifespan,
)

# ── 挂载所有路由 ──
app.include_router(delivery_router)
app.include_router(contracts_router)
app.include_router(admin_router)
app.include_router(receipts_router)
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
    """Data delivery readiness; safe codes only, no connection strings."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from app.adapters.bounded_http import post_json
    from app.adapters.opa import POLICY_REVISION
    errors = []
    try:
        expected = ScriptDirectory.from_config(Config('alembic.ini')).get_current_head()
        async with AsyncSessionLocal() as session:
            actual = (await session.execute(text('SELECT version_num FROM alembic_version'))).scalar_one()
            if actual != expected: errors.append('MIGRATION_REQUIRED')
    except Exception:
        errors.append('DATABASE_UNAVAILABLE_OR_UNMIGRATED')
    if app.state.upstream is None:
        errors.append('UPSTREAM_NOT_CONFIGURED')
    try:
        result = await post_json(app.state.opa.client, app.state.opa.url, {'input': {
            'view_id': 'readiness', 'contract_digest': 'readiness', 'identity': {},
            'contract': {'policies': [], 'views': []}}})
        decision = result['result']
        if decision.get('policy_revision') != POLICY_REVISION or decision.get('allow') is not False:
            errors.append('POLICY_NOT_READY')
    except Exception:
        errors.append('POLICY_NOT_READY')
    try:
        if app.state.presidio is None or await app.state.presidio.redact('probe@example.com') != '[EMAIL]':
            errors.append('PROFILE_NOT_READY')
    except Exception:
        errors.append('PROFILE_NOT_READY')
    if errors:
        return JSONResponse(status_code=503, content={'status': 'not_ready', 'errors': errors})
    return {'status': 'ready'}


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request, error):
    # Never echo invalid API keys or caller data through Pydantic's input field.
    return JSONResponse(status_code=422, content={'detail': {'code': 'REQUEST_INVALID'}})


if settings.A2A_ENABLED:
    from app.adapters.a2a_transport import mount_hub
    mount_hub(app, settings.A2A_URL)
