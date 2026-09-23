"""
战役一：Auth 与零信任防线 (Security & Auth)

测试目标：确保没有任何请求能在没有有效 JWT 和 Scope 的情况下"裸奔"过关。

测试矩阵：
  1. 无 Token 裸奔请求 → 401 / 422
  2. Token 越权（Scope 不足）→ 403 INSUFFICIENT_SCOPE
  3. JWT 过期失效 → 401
  4. 伪造 / 篡改 Token → 401
  5. 密钥轮换阻断（旧 API Key）→ 401
  6. 防刷速率限制 → 429 RATE_LIMIT_EXCEEDED（如已实现）
"""

import asyncio
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import make_auth_header, make_expired_jwt, make_jwt


# ═══════════════════════════════════════════
#  测试 1：裸奔请求（无 Authorization Header）
# ═══════════════════════════════════════════


class TestNakedRequests:
    """没有任何认证信息的请求，全部应该被拦截"""

    @pytest.mark.asyncio
    async def test_query_without_token(self, client: AsyncClient):
        """裸奔请求 /interact/query → 应返回 401 或 422"""
        resp = await client.post(
            "/api/v1/interact/query",
            json={
                "target_agent": "some-agent",
                "schema_id": "user_profile",
                "query_params": {},
            },
        )
        assert resp.status_code in (401, 422)

    @pytest.mark.asyncio
    async def test_discover_without_token(self, client: AsyncClient):
        """裸奔请求 /agents/discover → 应返回 401 或 422"""
        resp = await client.get("/api/v1/agents/discover")
        assert resp.status_code in (401, 422)

    @pytest.mark.asyncio
    async def test_publish_without_token(self, client: AsyncClient):
        """裸奔请求 /topics/publish → 应返回 401 或 422"""
        resp = await client.post(
            "/api/v1/topics/publish",
            json={"topic": "test", "content": {"msg": "hello"}},
        )
        assert resp.status_code in (401, 422)

    @pytest.mark.asyncio
    async def test_audit_without_token(self, client: AsyncClient):
        """裸奔请求 /audit/logs → 应返回 401 或 422"""
        resp = await client.get("/api/v1/audit/logs")
        assert resp.status_code in (401, 422)


# ═══════════════════════════════════════════
#  测试 2：JWT 过期失效
# ═══════════════════════════════════════════


class TestExpiredJWT:
    """已过期的 JWT 不应该通过任何鉴权"""

    @pytest.mark.asyncio
    async def test_expired_jwt_on_query(self, client: AsyncClient):
        """用已过期 JWT 请求 /interact/query → 401"""
        expired_token = make_expired_jwt("test-agent", ["query"])
        resp = await client.post(
            "/api/v1/interact/query",
            json={
                "target_agent": "any-agent",
                "schema_id": "user_profile",
                "query_params": {},
            },
            headers=make_auth_header(expired_token),
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_jwt_on_discover(self, client: AsyncClient):
        """用已过期 JWT 请求 /agents/discover → 401"""
        expired_token = make_expired_jwt("test-agent", ["discover"])
        resp = await client.get(
            "/api/v1/agents/discover",
            headers=make_auth_header(expired_token),
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_jwt_on_publish(self, client: AsyncClient):
        """用已过期 JWT 请求 /topics/publish → 401"""
        expired_token = make_expired_jwt("test-agent", ["publish"])
        resp = await client.post(
            "/api/v1/topics/publish",
            json={"topic": "test", "content": {"data": 1}},
            headers=make_auth_header(expired_token),
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════
#  测试 3：伪造 / 篡改 Token
# ═══════════════════════════════════════════


class TestForgedToken:
    """伪造或篡改的 JWT 不应通过鉴权"""

    @pytest.mark.asyncio
    async def test_completely_fake_token(self, client: AsyncClient):
        """完全捏造的字符串当 Token → 401"""
        resp = await client.get(
            "/api/v1/agents/discover",
            headers={"Authorization": "Bearer this.is.a.fake.token"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_secret_token(self, client: AsyncClient):
        """用错误密钥签发的 JWT → 401"""
        import jwt as pyjwt

        payload = {
            "sub": "hacker-agent",
            "iss": "a2a-contract-hub",
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(hours=1),
            "scopes": ["query", "publish", "discover"],
            "domain": "evil.com",
        }
        fake_token = pyjwt.encode(payload, "wrong-secret-key", algorithm="HS256")

        resp = await client.get(
            "/api/v1/agents/discover",
            headers=make_auth_header(fake_token),
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_authorization_header(self, client: AsyncClient):
        """Authorization header 格式错误（没有 Bearer 前缀）→ 401"""
        token = make_jwt("test-agent")
        resp = await client.get(
            "/api/v1/agents/discover",
            headers={"Authorization": f"Token {token}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_bearer_token(self, client: AsyncClient):
        """Bearer 后面是空字符串 → 401"""
        resp = await client.get(
            "/api/v1/agents/discover",
            headers={"Authorization": "Bearer "},
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════
#  测试 4：Token 换取流程
# ═══════════════════════════════════════════


class TestTokenExchange:
    """API Key 换 JWT 的流程测试"""

    @pytest.mark.asyncio
    async def test_valid_api_key_gets_token(
        self, client: AsyncClient, registered_agent: dict
    ):
        """正确的 agent_id + api_key → 成功拿到 JWT"""
        resp = await client.post(
            "/api/v1/auth/token",
            json={
                "agent_id": registered_agent["agent_id"],
                "api_key": registered_agent["api_key"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "Bearer"
        assert data["expires_in"] > 0

    @pytest.mark.asyncio
    async def test_wrong_api_key_rejected(
        self, client: AsyncClient, registered_agent: dict
    ):
        """正确 agent_id + 错误 api_key → 401"""
        resp = await client.post(
            "/api/v1/auth/token",
            json={
                "agent_id": registered_agent["agent_id"],
                "api_key": "this-is-a-completely-wrong-key",
            },
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_nonexistent_agent_rejected(self, client: AsyncClient):
        """不存在的 agent_id → 401（不透露是 ID 不存在还是 Key 错误）"""
        resp = await client.post(
            "/api/v1/auth/token",
            json={
                "agent_id": "ghost-agent-does-not-exist",
                "api_key": "any-key",
            },
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════
#  测试 5：Agent 注册安全
# ═══════════════════════════════════════════


class TestRegistrationSecurity:
    """The legacy self-registration contract was explicitly removed."""
    @pytest.mark.parametrize('body', [
        {'agent_id':'new-agent','domain':'org-acme','roles':['admin']},
        {'agent_id':'test-agent-alpha'}, {'data_contract':{'policies':[]}},
    ])
    async def test_self_registration_cannot_issue_credentials(self, client, registered_agent, body):
        response=await client.post('/api/v1/agents/register',json=body)
        assert response.status_code==403
        assert not {'api_key','access_token','hub_shared_secret'} & response.json().keys()

    async def test_current_scope_overrides_signed_claims(self,client,provision_identity):
        actor=await provision_identity('no-scope',scopes=[])
        token=make_jwt('no-scope',['query','admin'],domain='org-acme')
        response=await client.post('/api/v1/interact/query',headers=make_auth_header(token),json={})
        assert response.status_code==403
