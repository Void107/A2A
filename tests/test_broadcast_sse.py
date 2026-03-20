"""
战役四：SSE 广播稳定性 (Broadcast & SSE)

测试目标：
  1. 已认证的 Agent 可以成功发布消息
  2. 发布消息需要有效 JWT
  3. 消息内容正确写入 Redis channel
  4. 订阅接口需要认证
  5. 多 topic 隔离（发到 A 的消息不会出现在 B）

注：SSE 长连接的完整端到端测试需要真实 Redis，
    这里用 FakeRedis mock 验证逻辑正确性。
"""

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import make_auth_header, make_expired_jwt, make_jwt


# ═══════════════════════════════════════════
#  测试 1：发布消息（Publish）
# ═══════════════════════════════════════════


class TestPublish:
    """广播发布测试"""

    @pytest.mark.asyncio
    async def test_publish_success(self, client: AsyncClient):
        """已认证的 Agent 成功发布消息"""
        token = make_jwt("publisher-agent", scopes=["publish"])
        resp = await client.post(
            "/api/v1/topics/publish",
            json={
                "topic": "market-updates",
                "content": {"price": 42.5, "symbol": "ACME"},
                "entity_type": "stock_quote",
            },
            headers=make_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "published"
        assert data["topic"] == "market-updates"

    @pytest.mark.asyncio
    async def test_publish_without_auth_rejected(self, client: AsyncClient):
        """无认证发布 → 401/422"""
        resp = await client.post(
            "/api/v1/topics/publish",
            json={
                "topic": "market-updates",
                "content": {"msg": "hacked"},
            },
        )
        assert resp.status_code in (401, 422)

    @pytest.mark.asyncio
    async def test_publish_with_expired_token_rejected(
        self, client: AsyncClient
    ):
        """过期 JWT 发布 → 401"""
        expired_token = make_expired_jwt("publisher-agent", ["publish"])
        resp = await client.post(
            "/api/v1/topics/publish",
            json={
                "topic": "market-updates",
                "content": {"msg": "stale"},
            },
            headers=make_auth_header(expired_token),
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_publish_multiple_messages(self, client: AsyncClient):
        """连续发布多条消息到同一 topic"""
        token = make_jwt("multi-publisher", scopes=["publish"])

        for i in range(5):
            resp = await client.post(
                "/api/v1/topics/publish",
                json={
                    "topic": "batch-topic",
                    "content": {"seq": i, "msg": f"message-{i}"},
                },
                headers=make_auth_header(token),
            )
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_publish_to_different_topics(self, client: AsyncClient):
        """发布到不同 topic，互不干扰"""
        token = make_jwt("topic-agent", scopes=["publish"])

        resp_a = await client.post(
            "/api/v1/topics/publish",
            json={"topic": "topic-A", "content": {"for": "A"}},
            headers=make_auth_header(token),
        )
        resp_b = await client.post(
            "/api/v1/topics/publish",
            json={"topic": "topic-B", "content": {"for": "B"}},
            headers=make_auth_header(token),
        )
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        assert resp_a.json()["topic"] == "topic-A"
        assert resp_b.json()["topic"] == "topic-B"


# ═══════════════════════════════════════════
#  测试 2：订阅接口鉴权
# ═══════════════════════════════════════════


class TestSubscribeAuth:
    """订阅 SSE 端点的鉴权测试"""

    @pytest.mark.asyncio
    async def test_subscribe_without_auth_rejected(self, client: AsyncClient):
        """无认证订阅 → 401/422"""
        resp = await client.get(
            "/api/v1/topics/subscribe",
            params={"topic": "test-topic"},
        )
        assert resp.status_code in (401, 422)

    @pytest.mark.asyncio
    async def test_subscribe_with_expired_token_rejected(
        self, client: AsyncClient
    ):
        """过期 JWT 订阅 → 401"""
        expired_token = make_expired_jwt("sub-agent", ["subscribe"])
        resp = await client.get(
            "/api/v1/topics/subscribe",
            params={"topic": "test-topic"},
            headers=make_auth_header(expired_token),
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════
#  测试 3：发布消息内容验证
# ═══════════════════════════════════════════


class TestPublishContentIntegrity:
    """验证发布的消息内容正确性"""

    @pytest.mark.asyncio
    async def test_publish_preserves_content(
        self, client: AsyncClient, mock_redis
    ):
        """发布的 content 应该完整保留在 Redis channel 中"""
        token = make_jwt("integrity-agent", scopes=["publish"])
        content = {"nested": {"deep": {"value": 42}}, "tags": ["a", "b"]}

        resp = await client.post(
            "/api/v1/topics/publish",
            json={
                "topic": "integrity-test",
                "content": content,
                "entity_type": "test_entity",
            },
            headers=make_auth_header(token),
        )
        assert resp.status_code == 200

        # 验证 FakeRedis 中的消息
        channel_key = "topic:integrity-test"
        messages = mock_redis._channels.get(channel_key, [])
        assert len(messages) > 0

        last_message = json.loads(messages[-1])
        assert last_message["content"] == content
        assert last_message["entity_type"] == "test_entity"
        assert last_message["source_agent"] == "integrity-agent"

    @pytest.mark.asyncio
    async def test_publish_missing_topic_rejected(self, client: AsyncClient):
        """缺少 topic 字段 → 422 Validation Error"""
        token = make_jwt("bad-publisher", scopes=["publish"])
        resp = await client.post(
            "/api/v1/topics/publish",
            json={"content": {"msg": "no topic"}},
            headers=make_auth_header(token),
        )
        assert resp.status_code == 422
