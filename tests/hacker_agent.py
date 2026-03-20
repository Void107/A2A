"""
Hacker Agent —— 自动化攻击测试脚本。

这个"黑客 Agent"模拟一个恶意 Agent 的全套攻击流程：
  1. 合法注册进入系统，拿到 Token
  2. 尝试越权查询别的 Agent 的敏感数据（Query 攻击）
  3. 尝试向全网广播虚假数据（Publish 攻击）
  4. 尝试使用过期 / 伪造的 Token 绕过认证
  5. 尝试打爆速率限制

验证 Hub 是否像预期那样无情地把它挡在门外。

运行方式：
    pytest tests/hacker_agent.py -v --tb=short
"""

import asyncio
import json
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import make_auth_header, make_expired_jwt, make_jwt


# ═══════════════════════════════════════════
#  Phase 0：Hacker Agent 的注册和基础设施
# ═══════════════════════════════════════════


@pytest_asyncio.fixture
async def hacker_setup(client: AsyncClient):
    """
    完整的黑客测试场景搭建：
    1. 注册一个 "victim" Agent（有敏感数据）
    2. 注册一个 "hacker" Agent（企图窃取数据）
    """
    # ── 受害者 Agent ──
    victim_resp = await client.post(
        "/api/v1/agents/register",
        json={
            "agent_id": "victim-corp-hr",
            "display_name": "Victim Corp HR System",
            "callback_url": "http://localhost:9001/normal",
            "domain": "victim-corp.com",
            "skills": ["hr-data", "payroll"],
            "data_contract": {
                "version": "0.2.0",
                "schemas": [
                    {
                        "schema_id": "employee_salary",
                        "name": "Employee Salary Data",
                        "sensitivity_level": "restricted",
                    },
                    {
                        "schema_id": "public_directory",
                        "name": "Public Employee Directory",
                        "sensitivity_level": "public",
                    },
                ],
                "policies": [
                    {
                        "policy_id": "salary-internal-only",
                        "effect": "allow",
                        "schema_ids": ["employee_salary"],
                        "principal": {
                            "organizations": ["victim-corp.com"]
                        },
                        "transform_ids": [],
                    },
                    {
                        "policy_id": "directory-public",
                        "effect": "allow",
                        "schema_ids": ["public_directory"],
                        "principal": {"public": True},
                        "transform_ids": ["mask-phone"],
                    },
                    {
                        "policy_id": "block-competitor",
                        "effect": "deny",
                        "schema_ids": ["*"],
                        "principal": {
                            "organizations": ["evil-hacker.com"]
                        },
                    },
                ],
                "transforms": [
                    {
                        "transform_id": "mask-phone",
                        "type": "mask",
                        "applies_to_fields": ["phone"],
                    }
                ],
            },
        },
    )
    assert victim_resp.status_code == 201

    # ── 黑客 Agent ──
    hacker_resp = await client.post(
        "/api/v1/agents/register",
        json={
            "agent_id": "hacker-bot-001",
            "display_name": "Totally Legitimate Agent",
            "callback_url": "http://localhost:6666/evil",
            "domain": "evil-hacker.com",
            "skills": ["data-mining"],
            "data_contract": {
                "version": "0.2.0",
                "schemas": [
                    {"schema_id": "stolen_data", "name": "Stolen Data"},
                ],
                "policies": [],
                "transforms": [],
            },
        },
    )
    assert hacker_resp.status_code == 201

    victim_data = victim_resp.json()
    hacker_data = hacker_resp.json()

    return {
        "victim": {
            "agent_id": victim_data["agent_id"],
            "api_key": victim_data["api_key"],
            "token": victim_data["access_token"],
        },
        "hacker": {
            "agent_id": hacker_data["agent_id"],
            "api_key": hacker_data["api_key"],
            "token": hacker_data["access_token"],
        },
    }


# ═══════════════════════════════════════════
#  Phase 1：Query 攻击（窃取敏感数据）
# ═══════════════════════════════════════════


class TestHackerQueryAttack:
    """黑客尝试通过 Query Engine 窃取受害者的敏感数据"""

    @pytest.mark.asyncio
    async def test_steal_salary_data_blocked(
        self, client: AsyncClient, hacker_setup: dict
    ):
        """
        攻击：黑客尝试查询受害者的 employee_salary schema。
        预期：被 deny 策略 "block-competitor" 拦截 → 403。
        """
        hacker = hacker_setup["hacker"]
        resp = await client.post(
            "/api/v1/interact/query",
            json={
                "target_agent": "victim-corp-hr",
                "schema_id": "employee_salary",
                "query_params": {"employee_id": "all"},
            },
            headers=make_auth_header(hacker["token"]),
        )
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["code"] == "CONTRACT_VIOLATION"
        # 确保不返回任何实际数据
        assert "data" not in resp.json()

    @pytest.mark.asyncio
    async def test_steal_public_directory_also_blocked(
        self, client: AsyncClient, hacker_setup: dict
    ):
        """
        攻击：黑客尝试查询 public_directory（看似公开的数据）。
        预期：被 deny 策略 "block-competitor" 拦截 → 403。
              因为 deny 优先于 allow，即使 public_directory 有 public allow 策略，
              evil-hacker.com 的 deny 策略仍然生效。
        """
        hacker = hacker_setup["hacker"]
        resp = await client.post(
            "/api/v1/interact/query",
            json={
                "target_agent": "victim-corp-hr",
                "schema_id": "public_directory",
                "query_params": {},
            },
            headers=make_auth_header(hacker["token"]),
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "CONTRACT_VIOLATION"

    @pytest.mark.asyncio
    async def test_query_nonexistent_schema_blocked(
        self, client: AsyncClient, hacker_setup: dict
    ):
        """
        攻击：黑客猜测一个不存在的 schema 名。
        预期：403（schema 未声明，Fail-Closed）。
        """
        hacker = hacker_setup["hacker"]
        resp = await client.post(
            "/api/v1/interact/query",
            json={
                "target_agent": "victim-corp-hr",
                "schema_id": "super_secret_backdoor",
                "query_params": {},
            },
            headers=make_auth_header(hacker["token"]),
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════
#  Phase 2：Publish 攻击（广播虚假数据）
# ═══════════════════════════════════════════


class TestHackerPublishAttack:
    """黑客尝试通过广播系统散布虚假信息"""

    @pytest.mark.asyncio
    async def test_publish_fake_data_with_valid_token(
        self, client: AsyncClient, hacker_setup: dict
    ):
        """
        攻击：黑客用自己的合法 Token 向公共 topic 广播虚假数据。
        现状：当前版本没有 entity_type 契约校验，所以发布会成功。
        这里验证发布功能本身正常，后续版本应增加发布侧契约拦截。
        """
        hacker = hacker_setup["hacker"]
        resp = await client.post(
            "/api/v1/topics/publish",
            json={
                "topic": "market-alerts",
                "content": {
                    "alert": "FAKE: Company X is bankrupt!",
                    "severity": "critical",
                },
                "entity_type": "market_alert",
            },
            headers=make_auth_header(hacker["token"]),
        )
        # MVP 阶段发布没有契约拦截，所以 200 是预期行为
        # TODO: V2.0 应返回 403 CONTRACT_VIOLATION
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_publish_without_token_blocked(self, client: AsyncClient):
        """
        攻击：完全不带 Token 就发布。
        预期：无论如何都被拦截。
        """
        resp = await client.post(
            "/api/v1/topics/publish",
            json={
                "topic": "system-alerts",
                "content": {"msg": "HACKED!"},
            },
        )
        assert resp.status_code in (401, 422)


# ═══════════════════════════════════════════
#  Phase 3：Token 伪造攻击
# ═══════════════════════════════════════════


class TestHackerTokenForgery:
    """黑客尝试伪造或篡改 Token"""

    @pytest.mark.asyncio
    async def test_forged_jwt_blocked(self, client: AsyncClient):
        """
        攻击：用错误的 secret 签发 JWT，冒充管理员。
        预期：401。
        """
        import jwt as pyjwt

        forged_token = pyjwt.encode(
            {
                "sub": "admin-superuser",
                "iss": "a2a-contract-hub",
                "iat": datetime.utcnow(),
                "exp": datetime.utcnow() + timedelta(hours=24),
                "scopes": ["admin", "query", "publish", "discover", "audit"],
                "domain": "victim-corp.com",  # 冒充受害者的域
            },
            "i-guessed-the-wrong-secret",
            algorithm="HS256",
        )

        resp = await client.get(
            "/api/v1/agents/discover",
            headers=make_auth_header(forged_token),
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_stolen_token_blocked(
        self, client: AsyncClient, hacker_setup: dict
    ):
        """
        攻击：使用过期的 Token（模拟窃取了旧 Token）。
        预期：401。
        """
        expired = make_expired_jwt(
            hacker_setup["hacker"]["agent_id"],
            ["query", "publish"],
        )
        resp = await client.post(
            "/api/v1/interact/query",
            json={
                "target_agent": "victim-corp-hr",
                "schema_id": "employee_salary",
                "query_params": {},
            },
            headers=make_auth_header(expired),
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_tampered_token_scope_blocked(self, client: AsyncClient):
        """
        攻击：拿到合法 Token 后，篡改 payload 增加 scopes。
        预期：签名校验失败 → 401。
        """
        import base64

        # 先拿一个合法 token
        legit_token = make_jwt("normal-agent", scopes=["subscribe"])

        # 拆开 JWT，篡改 payload
        parts = legit_token.split(".")
        # 修改 payload（粗暴替换不修复签名）
        tampered_payload = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "sub": "normal-agent",
                    "scopes": ["admin", "query", "publish"],
                    "exp": 9999999999,
                }
            ).encode()
        ).decode().rstrip("=")

        tampered_token = f"{parts[0]}.{tampered_payload}.{parts[2]}"

        resp = await client.get(
            "/api/v1/agents/discover",
            headers=make_auth_header(tampered_token),
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════
#  Phase 4：信息侦察攻击
# ═══════════════════════════════════════════


class TestHackerReconnaissance:
    """黑客尝试通过各种手段搜集系统信息"""

    @pytest.mark.asyncio
    async def test_discover_reveals_no_secrets(
        self, client: AsyncClient, hacker_setup: dict
    ):
        """
        侦察：黑客用合法 Token 调用 /discover 查看所有 Agent。
        预期：可以看到公开摘要，但不应泄露 api_key / secret。
        """
        hacker = hacker_setup["hacker"]
        resp = await client.get(
            "/api/v1/agents/discover",
            headers=make_auth_header(hacker["token"]),
        )
        assert resp.status_code == 200
        agents = resp.json()

        for agent_info in agents:
            # 确保不泄露任何敏感凭证
            assert "api_key" not in str(agent_info)
            assert "api_key_hash" not in str(agent_info)
            assert "hub_shared_secret" not in str(agent_info)
            assert "hub_shared_secret_hash" not in str(agent_info)
            # 只应包含公开信息
            assert "agent_id" in agent_info
            assert "display_name" in agent_info

    @pytest.mark.asyncio
    async def test_wrong_api_key_no_information_leak(
        self, client: AsyncClient, hacker_setup: dict
    ):
        """
        侦察：用正确的 agent_id + 错误的 api_key 尝试换 Token。
        预期：错误信息不透露是 agent_id 不存在还是 api_key 错误。
        """
        # 用受害者的 agent_id + 随机 key
        resp1 = await client.post(
            "/api/v1/auth/token",
            json={
                "agent_id": "victim-corp-hr",
                "api_key": "wrong-key-guess",
            },
        )

        # 用不存在的 agent_id
        resp2 = await client.post(
            "/api/v1/auth/token",
            json={
                "agent_id": "nonexistent-agent-xyz",
                "api_key": "any-key",
            },
        )

        # 两种情况应返回完全相同的错误，防止枚举攻击
        assert resp1.status_code == 401
        assert resp2.status_code == 401
        assert resp1.json()["detail"] == resp2.json()["detail"]
