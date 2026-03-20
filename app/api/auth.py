"""
认证接口 + 鉴权依赖。

🔴 核心性能修正（相比指南原版）：
   /token 接口强制要求传 agent_id + api_key。
   先用 agent_id 做 O(1) 索引精确查询，只取出一条记录，
   再对这一条做 bcrypt 比对。
   绝不遍历全表 —— bcrypt 故意慢（~250ms/次），1000 Agent 就是 4 分钟。
"""

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_jwt, decode_jwt, verify_api_key
from app.database import get_db
from app.models.schemas import Agent

router = APIRouter(prefix="/api/v1/auth", tags=["认证"])


# ── 请求体用 Pydantic Model，比裸 dict 安全 ──

class TokenRequest(BaseModel):
    agent_id: str
    api_key: str


class TokenResponse(BaseModel):
    access_token: str
    expires_in: int
    token_type: str = "Bearer"


@router.post("/token", response_model=TokenResponse)
async def get_token(body: TokenRequest, db: AsyncSession = Depends(get_db)):
    """
    用 agent_id + api_key 换取短期 JWT 令牌。

    流程：
    1. 用 agent_id 做索引查询（O(1)），拿到唯一记录
    2. 对该记录做一次 bcrypt 比对
    3. 签发 JWT，携带 scopes 和 domain
    """
    # O(1) 精确查询，走 ix_agents_agent_id 索引
    result = await db.execute(
        select(Agent).where(
            Agent.agent_id == body.agent_id,
            Agent.is_active.is_(True),
        )
    )
    agent = result.scalar_one_or_none()

    # agent_id 不存在 或 api_key 不匹配，返回同一个错误
    # 防止攻击者通过不同错误信息探测有效 agent_id
    if not agent or not verify_api_key(body.api_key, agent.api_key_hash):
        raise HTTPException(
            status_code=401,
            detail="认证失败：agent_id 或 api_key 无效",
        )

    token = create_jwt(agent.agent_id, agent.scopes, agent.domain)
    return TokenResponse(
        access_token=token,
        expires_in=settings.JWT_EXPIRE_MINUTES * 60,
    )


# ═══════════════════════════════════════════
#  鉴权依赖 —— 加在需要登录的路由上
# ═══════════════════════════════════════════

async def require_auth(authorization: str = Header(...)) -> dict:
    """
    FastAPI 依赖注入：从 Authorization header 提取并验证 JWT。
    用法：在路由参数里加 agent=Depends(require_auth)
    返回 JWT payload dict，包含 sub / scopes / domain 等字段。
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="格式错误，需要 Bearer <token>")

    token = authorization.removeprefix("Bearer ")
    try:
        return decode_jwt(token)
    except Exception:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
