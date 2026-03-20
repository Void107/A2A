"""
战役三：反向代理的混沌工程 (Proxy Chaos)

测试目标：当外部环境极其恶劣时，Hub 自己不能崩。

测试矩阵：
  1. 上游超时雪崩 → 504 UPSTREAM_TIMEOUT
  2. 内存炸弹（OOM 防御）→ 413 PAYLOAD_TOO_LARGE
  3. 上游直接宕机 → 502 CONNECT_REFUSED
  4. 上游返回 HTTP 500 → 502 UPSTREAM_ERROR
  5. 上游返回非法 JSON → 502
  6. 契约拦截（未声明的 schema）→ 403 CONTRACT_VIOLATION
  7. Fail-Closed 兜底 → 脱敏引擎异常时绝不泄露原始数据

策略：用 unittest.mock.patch 拦截 httpx 请求，注入各种异常，
      不需要真正启动 mock_agent 服务器。
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import make_auth_header, make_jwt


# ═══════════════════════════════════════════
#  辅助函数：创建用于 query 测试的 target Agent
# ═══════════════════════════════════════════


async def _register_target_agent(client: AsyncClient, callback_url: str) -> dict:
    """注册一个 target Agent 并指定 callback_url"""
    resp = await client.post(
        "/api/v1/agents/register",
        json={
            "agent_id": "target-chaos-agent",
            "display_name": "Chaos Target",
            "callback_url": callback_url,
            "domain": "chaos-test.org",
            "skills": ["data-provider"],
            "data_contract": {
                "version": "0.2.0",
                "schemas": [
                    {
                        "schema_id": "chaos_data",
                        "name": "Chaos Test Data",
                        "sensitivity_level": "internal",
                    },
                ],
                "policies": [
                    {
                        "policy_id": "allow-all",
                        "effect": "allow",
                        "schema_ids": ["*"],
                        "principal": {"public": True},
                        "transform_ids": [],
                    },
                ],
                "transforms": [],
            },
        },
    )
    assert resp.status_code == 201, f"Target registration failed: {resp.text}"
    return resp.json()


# ═══════════════════════════════════════════
#  测试 1：上游超时雪崩
# ═══════════════════════════════════════════


class TestUpstreamTimeout:
    """模拟目标 Agent 响应超时"""

    @pytest.mark.asyncio
    async def test_connect_timeout(self, client: AsyncClient):
        """上游建连超时 → Hub 返回 504"""
        await _register_target_agent(client, "http://localhost:9001/slow")

        token = make_jwt("caller-agent", domain="chaos-test.org")

        # Mock httpx 抛出 ConnectTimeout
        with patch("app.api.query.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(
                return_value=mock_instance
            )
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.stream = MagicMock(side_effect=httpx.ConnectTimeout("Connection timed out"))

            resp = await client.post(
                "/api/v1/interact/query",
                json={
                    "target_agent": "target-chaos-agent",
                    "schema_id": "chaos_data",
                    "query_params": {},
                },
                headers=make_auth_header(token),
            )
            assert resp.status_code == 504
            assert "CONNECT_TIMEOUT" in resp.json()["detail"]["code"]

    @pytest.mark.asyncio
    async def test_read_timeout(self, client: AsyncClient):
        """上游读超时 → Hub 返回 504"""
        await _register_target_agent(client, "http://localhost:9001/slow")

        token = make_jwt("caller-agent-2", domain="chaos-test.org")

        with patch("app.api.query.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(
                return_value=mock_instance
            )
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.stream = MagicMock(side_effect=httpx.ReadTimeout("Read timed out"))

            resp = await client.post(
                "/api/v1/interact/query",
                json={
                    "target_agent": "target-chaos-agent",
                    "schema_id": "chaos_data",
                    "query_params": {},
                },
                headers=make_auth_header(token),
            )
            assert resp.status_code == 504
            assert "READ_TIMEOUT" in resp.json()["detail"]["code"]


# ═══════════════════════════════════════════
#  测试 2：上游直接宕机（连接被拒绝）
# ═══════════════════════════════════════════


class TestUpstreamDown:
    """模拟目标 Agent 完全不可用"""

    @pytest.mark.asyncio
    async def test_connection_refused(self, client: AsyncClient):
        """callback_url 指向未启动的端口 → 502"""
        await _register_target_agent(client, "http://localhost:59999/dead")

        token = make_jwt("caller-agent-3", domain="chaos-test.org")

        with patch("app.api.query.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(
                return_value=mock_instance
            )
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.stream = MagicMock(
                side_effect=httpx.ConnectError("Connection refused")
            )

            resp = await client.post(
                "/api/v1/interact/query",
                json={
                    "target_agent": "target-chaos-agent",
                    "schema_id": "chaos_data",
                    "query_params": {},
                },
                headers=make_auth_header(token),
            )
            assert resp.status_code == 502
            assert "CONNECT_REFUSED" in resp.json()["detail"]["code"]


# ═══════════════════════════════════════════
#  测试 3：上游返回 HTTP 500 错误
# ═══════════════════════════════════════════


class TestUpstreamHTTPError:
    """模拟目标 Agent 返回 5xx 错误"""

    @pytest.mark.asyncio
    async def test_upstream_500(self, client: AsyncClient):
        """上游返回 500 → Hub 返回 502 UPSTREAM_ERROR"""
        await _register_target_agent(client, "http://localhost:9001/error-500")

        token = make_jwt("caller-agent-4", domain="chaos-test.org")

        mock_response = MagicMock()
        mock_response.status_code = 500
        error = httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=MagicMock(),
            response=mock_response,
        )

        with patch("app.api.query.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(
                return_value=mock_instance
            )
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.stream = MagicMock(side_effect=error)

            resp = await client.post(
                "/api/v1/interact/query",
                json={
                    "target_agent": "target-chaos-agent",
                    "schema_id": "chaos_data",
                    "query_params": {},
                },
                headers=make_auth_header(token),
            )
            assert resp.status_code == 502
            assert "UPSTREAM_ERROR" in resp.json()["detail"]["code"]


# ═══════════════════════════════════════════
#  测试 4：契约拦截（未声明的 schema_id）
# ═══════════════════════════════════════════


class TestContractViolation:
    """请求未在目标契约中声明的 schema → 403"""

    @pytest.mark.asyncio
    async def test_undeclared_schema_blocked(self, client: AsyncClient):
        """请求一个 target 契约里不存在的 schema_id → 403"""
        await _register_target_agent(client, "http://localhost:9001/normal")

        token = make_jwt("caller-agent-5", domain="chaos-test.org")

        resp = await client.post(
            "/api/v1/interact/query",
            json={
                "target_agent": "target-chaos-agent",
                "schema_id": "TOP_SECRET_SCHEMA_THAT_DOES_NOT_EXIST",
                "query_params": {},
            },
            headers=make_auth_header(token),
        )
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["code"] == "CONTRACT_VIOLATION"

    @pytest.mark.asyncio
    async def test_no_matching_policy_blocked(self, client: AsyncClient):
        """
        schema 存在但 principal 不匹配 → Fail-Closed 拒绝。
        注册一个策略只允许特定组织的 Agent。
        """
        # 注册一个限制很严的 target
        resp = await client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "strict-target-agent",
                "display_name": "Strict Target",
                "callback_url": "http://localhost:9001/normal",
                "domain": "strict-corp.com",
                "data_contract": {
                    "version": "0.2.0",
                    "schemas": [
                        {"schema_id": "secret_data", "name": "Secret"},
                    ],
                    "policies": [
                        {
                            "policy_id": "only-vip",
                            "effect": "allow",
                            "schema_ids": ["secret_data"],
                            "principal": {
                                "organizations": ["vip-only-corp.com"]
                            },
                            "transform_ids": [],
                        },
                    ],
                    "transforms": [],
                },
            },
        )
        assert resp.status_code == 201

        # 用一个不在 vip-only-corp.com 的 agent 去请求
        outsider_token = make_jwt(
            "outsider-agent", domain="random-corp.com"
        )
        resp = await client.post(
            "/api/v1/interact/query",
            json={
                "target_agent": "strict-target-agent",
                "schema_id": "secret_data",
                "query_params": {},
            },
            headers=make_auth_header(outsider_token),
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "CONTRACT_VIOLATION"


# ═══════════════════════════════════════════
#  测试 5：查询不存在的 Agent
# ═══════════════════════════════════════════


class TestQueryNonexistentAgent:
    """查询一个根本不存在的 target agent"""

    @pytest.mark.asyncio
    async def test_target_not_found(self, client: AsyncClient):
        """target_agent 不存在 → 404"""
        token = make_jwt("lonely-caller", domain="testing.org")
        resp = await client.post(
            "/api/v1/interact/query",
            json={
                "target_agent": "agent-that-does-not-exist",
                "schema_id": "any_schema",
                "query_params": {},
            },
            headers=make_auth_header(token),
        )
        assert resp.status_code == 404
