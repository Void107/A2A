"""
Schema Registry —— Agent 注册 + 发现。

v0.2.0 要点：
- 注册时生成两个密钥：api_key（Agent→Hub）和 hub_shared_secret（Hub→Agent §2.2）
- 两个密钥只在注册响应中返回一次，库里只存 bcrypt 哈希
- data_contract 必须包含 schemas 字段（§1.2）
- 请求体用 Pydantic Model 做校验，拒绝脏数据进入业务层
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_auth
from app.core.security import (
    create_jwt,
    generate_api_key,
    generate_hub_secret,
    hash_api_key,
)
from app.database import get_db
from app.models.schemas import Agent, ContractHistory

router = APIRouter(prefix="/api/v1/agents", tags=["Agent 注册"])


# ── 请求 / 响应模型 ──

class RegisterRequest(BaseModel):
    agent_id: str
    display_name: str
    callback_url: str
    domain: Optional[str] = None
    skills: list = []
    data_contract: dict


class RegisterResponse(BaseModel):
    agent_id: str
    api_key: str
    hub_shared_secret: str
    access_token: str
    message: str


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register_agent(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """注册一个新 Agent，提交 Agent Card + 数据契约"""

    # 校验 data_contract 结构
    if "schemas" not in body.data_contract:
        raise HTTPException(
            status_code=422,
            detail="data_contract 必须包含 schemas 字段",
        )

    # 检查 agent_id 是否重复
    result = await db.execute(
        select(Agent).where(Agent.agent_id == body.agent_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="agent_id 已存在")

    # 生成两个密钥
    api_key = generate_api_key()
    hub_shared_secret = generate_hub_secret()

    # 创建 Agent 记录
    agent = Agent(
        agent_id=body.agent_id,
        display_name=body.display_name,
        callback_url=body.callback_url,
        skills=body.skills,
        data_contract=body.data_contract,
        domain=body.domain,
        api_key_hash=hash_api_key(api_key),
        hub_shared_secret_hash=hash_api_key(hub_shared_secret),
    )
    db.add(agent)

    # 记录第一个契约版本
    history = ContractHistory(
        agent_id=body.agent_id,
        version=body.data_contract.get("version", "0.2.0"),
        contract_data=body.data_contract,
    )
    db.add(history)

    await db.commit()

    # 签发首个 JWT
    token = create_jwt(agent.agent_id, agent.scopes, agent.domain)

    return RegisterResponse(
        agent_id=agent.agent_id,
        api_key=api_key,
        hub_shared_secret=hub_shared_secret,
        access_token=token,
        message=(
            "注册成功！请妥善保存 api_key 和 hub_shared_secret，它们不会再次显示。"
            " api_key 用于向 Hub 换取 JWT；"
            "hub_shared_secret 用于验证 Hub 转发给你的请求。"
        ),
    )


@router.get("/discover")
async def discover_agents(
    agent: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """发现所有活跃 Agent 及其数据契约摘要（需要登录）"""

    result = await db.execute(
        select(Agent).where(Agent.is_active.is_(True))
    )
    agents = result.scalars().all()

    return [
        {
            "agent_id": a.agent_id,
            "display_name": a.display_name,
            "domain": a.domain,
            "skills": a.skills,
            "schemas": [
                {
                    "schema_id": s["schema_id"],
                    "name": s.get("name", ""),
                    "sensitivity_level": s.get("sensitivity_level", "internal"),
                }
                for s in a.data_contract.get("schemas", [])
            ],
        }
        for a in agents
    ]
