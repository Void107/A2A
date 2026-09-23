"""
测试基建 conftest.py —— 所有测试共享的 Fixtures。

核心策略：
1. 用 SQLite (aiosqlite) 做内存数据库，无需真实 PostgreSQL
2. 用 FakeRedis 纯 Python mock，无需真实 Redis
3. 用 httpx.AsyncClient 直连 ASGI app，无需启动 uvicorn
4. 每个测试函数独享干净的数据库（function scope fixture）

🔴 关键技术点：
   app.database 在模块加载时就创建 PG 引擎（带 pool_size 等参数），
   必须在 import app 之前用 monkeypatch 替换掉，否则 SQLite 会报错。
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import StaticPool

# ═══════════════════════════════════════════
#  第 0 步：在 import app 之前设置环境变量
# ═══════════════════════════════════════════

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["JWT_SECRET"] = "test-secret-key-for-unit-tests-only"
os.environ["JWT_EXPIRE_MINUTES"] = "60"
os.environ["MAX_RESPONSE_BYTES"] = "5242880"

# ═══════════════════════════════════════════
#  第 1 步：创建 SQLite 测试引擎（替代 PG 引擎）
# ═══════════════════════════════════════════

TEST_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)

TestSessionLocal = sessionmaker(
    bind=TEST_ENGINE,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ═══════════════════════════════════════════
#  第 2 步：Monkey-patch app.database 模块
#  在 app.database 被 import 之前，先创建一个假模块占位
# ═══════════════════════════════════════════

# 先 import Base 需要的基类
class Base(DeclarativeBase):
    """测试用 ORM 基类"""
    pass

# 创建一个 mock database 模块
import types
mock_database = types.ModuleType("app.database")
mock_database.engine = TEST_ENGINE
mock_database.AsyncSessionLocal = TestSessionLocal
mock_database.Base = Base

async def _mock_get_db():
    async with TestSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

mock_database.get_db = _mock_get_db

# 注入到 sys.modules，让后续 from app.database import ... 都走这个 mock
sys.modules["app.database"] = mock_database

# ═══════════════════════════════════════════
#  第 3 步：现在可以安全 import app 了
# ═══════════════════════════════════════════

from app.config import settings
from app.core.security import create_jwt, generate_api_key, hash_api_key
from app.database import Base, get_db
from app.main import app


# ═══════════════════════════════════════════
#  数据库 Fixtures
# ═══════════════════════════════════════════

@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """每个测试前建表，测试后清表 —— 保证测试隔离"""
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# 全局替换 FastAPI 的数据库依赖
app.dependency_overrides[get_db] = _mock_get_db


# ═══════════════════════════════════════════
#  Redis Mock
# ═══════════════════════════════════════════

class FakeRedis:
    """
    轻量 Redis Mock —— 模拟 publish / subscribe / xadd 等操作。
    不依赖 fakeredis 库，用纯 Python dict 实现核心接口。
    """

    def __init__(self):
        self._data = {}
        self._streams = {}
        self._channels = {}
        self._stream_id_counter = 0

    async def ping(self):
        return True

    async def publish(self, channel: str, message: str) -> int:
        if channel not in self._channels:
            self._channels[channel] = []
        self._channels[channel].append(message)
        return len(self._channels.get(channel, []))

    async def xadd(self, stream: str, fields: dict, **kwargs):
        if stream not in self._streams:
            self._streams[stream] = []
        self._stream_id_counter += 1
        msg_id = f"0-{self._stream_id_counter}"
        self._streams[stream].append((msg_id, fields))
        return msg_id

    async def xread(self, streams: dict, count: int = 100, block: int = 0):
        result = []
        for stream_name, last_id in streams.items():
            if stream_name in self._streams:
                messages = self._streams[stream_name]
                result.append((stream_name, messages))
        return result if result else []

    async def xdel(self, stream: str, *msg_ids):
        if stream in self._streams:
            self._streams[stream] = [
                (mid, fields)
                for mid, fields in self._streams[stream]
                if mid not in msg_ids
            ]

    def pubsub(self):
        return FakePubSub(self)

    async def aclose(self):
        pass


class FakePubSub:
    """模拟 Redis PubSub"""

    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._subscribed_channels = []

    async def subscribe(self, channel: str):
        self._subscribed_channels.append(channel)

    async def unsubscribe(self, channel: str):
        if channel in self._subscribed_channels:
            self._subscribed_channels.remove(channel)

    async def listen(self):
        for channel in self._subscribed_channels:
            for msg in self._redis._channels.get(channel, []):
                yield {"type": "message", "data": msg, "channel": channel}

    async def aclose(self):
        pass


_fake_redis = FakeRedis()


@pytest.fixture(autouse=True)
def mock_redis():
    """
    全局 mock Redis 连接池，每个测试重置状态。

    🔴 关键：必须 patch 所有「使用点」，而不仅是源模块。
    因为 `from app.core.redis_pool import get_redis` 会在目标模块创建本地引用，
    只 patch 源模块不会影响已导入的引用。
    """
    _fake_redis._channels.clear()
    _fake_redis._streams.clear()
    _fake_redis._stream_id_counter = 0

    with patch("app.core.redis_pool.get_redis", return_value=_fake_redis), \
         patch("app.api.topics.get_redis", return_value=_fake_redis), \
         patch("app.services.audit_writer.get_redis", return_value=_fake_redis), \
         patch("app.core.redis_pool.init_redis", new_callable=AsyncMock), \
         patch("app.core.redis_pool.close_redis", new_callable=AsyncMock):
        yield _fake_redis


# ═══════════════════════════════════════════
#  HTTP Client Fixture
# ═══════════════════════════════════════════

@pytest_asyncio.fixture
async def client():
    """
    异步 HTTP 测试客户端 —— 直连 ASGI app，不起 uvicorn。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ═══════════════════════════════════════════
#  Agent 注册 + JWT 工厂 Fixtures
# ═══════════════════════════════════════════

@pytest_asyncio.fixture
async def registered_agent(client: AsyncClient):
    """
    注册一个标准测试 Agent，返回完整注册信息。
    """
    register_data = {
        "agent_id": "test-agent-alpha",
        "display_name": "Test Agent Alpha",
        "callback_url": "http://localhost:9001/normal",
        "domain": "testing.org",
        "skills": ["query", "report"],
        "data_contract": {
            "version": "0.2.0",
            "schemas": [
                {
                    "schema_id": "user_profile",
                    "name": "User Profile",
                    "sensitivity_level": "confidential",
                    "fields": [
                        {"name": "name", "type": "string"},
                        {"name": "email", "type": "string"},
                        {"name": "phone", "type": "string"},
                    ],
                },
                {
                    "schema_id": "financial_report",
                    "name": "Financial Report",
                    "sensitivity_level": "restricted",
                    "fields": [
                        {"name": "q3_revenue", "type": "number"},
                    ],
                },
            ],
            "policies": [
                {
                    "policy_id": "allow-public-read",
                    "effect": "allow",
                    "schema_ids": ["user_profile"],
                    "principal": {"public": True},
                    "transform_ids": ["mask-email"],
                },
                {
                    "policy_id": "allow-finance-internal",
                    "effect": "allow",
                    "schema_ids": ["financial_report"],
                    "principal": {"organizations": ["testing.org"]},
                    "transform_ids": ["generalize-revenue"],
                },
            ],
            "transforms": [
                {
                    "transform_id": "mask-email",
                    "type": "redact",
                    "applies_to_fields": ["user.email"],
                },
                {
                    "transform_id": "generalize-revenue",
                    "type": "generalize",
                    "applies_to_fields": ["financials.q3_revenue"],
                },
            ],
        },
    }

    resp = await client.post("/api/v1/agents/register", json=register_data)
    assert resp.status_code == 201, f"Agent registration failed: {resp.text}"

    data = resp.json()
    return {
        "agent_id": data["agent_id"],
        "api_key": data["api_key"],
        "access_token": data["access_token"],
        "hub_shared_secret": data["hub_shared_secret"],
        "auth_header": {"Authorization": f"Bearer {data['access_token']}"},
    }


@pytest_asyncio.fixture
async def second_agent(client: AsyncClient):
    """注册第二个 Agent（作为查询目标）"""
    register_data = {
        "agent_id": "test-agent-beta",
        "display_name": "Test Agent Beta (Target)",
        "callback_url": "http://localhost:9001/normal",
        "domain": "other-corp.com",
        "skills": ["data-provider"],
        "data_contract": {
            "version": "0.2.0",
            "schemas": [
                {
                    "schema_id": "candidate_info",
                    "name": "Candidate Info",
                    "sensitivity_level": "restricted",
                    "fields": [
                        {"name": "name", "type": "string"},
                        {"name": "salary", "type": "number"},
                    ],
                },
            ],
            "policies": [
                {
                    "policy_id": "allow-testing-org",
                    "effect": "allow",
                    "schema_ids": ["candidate_info"],
                    "principal": {"organizations": ["testing.org"]},
                    "transform_ids": [],
                },
            ],
            "transforms": [],
        },
    }

    resp = await client.post("/api/v1/agents/register", json=register_data)
    assert resp.status_code == 201
    data = resp.json()
    return {
        "agent_id": data["agent_id"],
        "api_key": data["api_key"],
        "access_token": data["access_token"],
        "auth_header": {"Authorization": f"Bearer {data['access_token']}"},
    }


def make_jwt(
    agent_id: str = "test-agent",
    scopes: list = None,
    domain: str = "testing.org",
    expire_minutes: int = 60,
) -> str:
    """
    工厂函数：快速签发自定义 JWT 用于测试。
    """
    if scopes is None:
        scopes = ["publish", "query", "discover", "subscribe", "audit"]
    return create_jwt(agent_id, scopes, domain)


def make_expired_jwt(
    agent_id: str = "test-agent",
    scopes: list = None,
    domain: str = "testing.org",
) -> str:
    """签发一个已过期的 JWT（用于测试过期拒绝）"""
    import jwt as pyjwt

    now = datetime.utcnow()
    payload = {
        "sub": agent_id,
        "iss": "a2a-contract-hub",
        "iat": now - timedelta(hours=2),
        "exp": now - timedelta(hours=1),  # 1 小时前已过期
        "scopes": scopes or ["query"],
        "domain": domain,
    }
    return pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def make_auth_header(token: str) -> dict:
    """快捷生成 Authorization header"""
    return {"Authorization": f"Bearer {token}"}
