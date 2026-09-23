"""Database-backed identity. Signed JWT claims never grant organization or roles."""
import asyncio
import hashlib
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_jwt, decode_jwt, verify_api_key
from app.database import get_db
from app.core.redis_pool import get_redis
from app.models.schemas import Agent

router = APIRouter(prefix='/api/v1/auth', tags=['认证'])
# Single-process alpha limit; cross-process global quotas are not claimed.
_token_slots = asyncio.Semaphore(4)


def denied(code='ACCESS_DENIED', status=403):
    return HTTPException(status_code=status, detail={'code': code})


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    agent_id: str = Field(min_length=1, max_length=64)
    api_key: str = Field(min_length=1, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    expires_in: int
    token_type: str = 'Bearer'


@router.post('/token', response_model=TokenResponse)
async def get_token(body: TokenRequest, db: AsyncSession = Depends(get_db)):
    try:
        key = hashlib.sha256(body.agent_id.encode()).hexdigest()
        script = 'local n=redis.call("INCR",KEYS[1]); if n==1 then redis.call("EXPIRE",KEYS[1],60) end; return n'
        global_count = await asyncio.wait_for(get_redis().eval(script, 1, 'auth:global'), 2)
        count = await asyncio.wait_for(get_redis().eval(script, 1, 'auth:subject:' + key), 2)
    except Exception:
        raise denied('AUTHENTICATION_UNAVAILABLE', 503) from None
    if count > 20 or global_count > 300:
        raise denied('RATE_LIMITED', 429)
    if _token_slots.locked():
        raise denied('RATE_LIMITED', 429)
    async with _token_slots:
        result = await db.execute(select(Agent).where(Agent.agent_id == body.agent_id))
        agent = result.scalar_one_or_none()
        if not agent or not agent.is_active:
            raise denied('AUTHENTICATION_REQUIRED', 401)
        verified_hash, verified_revision = agent.api_key_hash, agent.credential_revision
        if not await asyncio.to_thread(verify_api_key, body.api_key, verified_hash):
            raise denied('AUTHENTICATION_REQUIRED', 401)
        # Refetch after expensive hashing to avoid minting stale credentials.
        await db.refresh(agent)
        if not agent.is_active or agent.credential_revision != verified_revision or agent.api_key_hash != verified_hash:
            raise denied('AUTHENTICATION_REQUIRED', 401)
        return TokenResponse(access_token=create_jwt(agent.agent_id, [], revision=agent.credential_revision),
                             expires_in=settings.JWT_EXPIRE_MINUTES * 60)


async def require_auth(authorization: Optional[str] = Header(None),
                       db: AsyncSession = Depends(get_db)) -> dict:
    authentication_started = time.perf_counter()
    if not authorization or not authorization.startswith('Bearer '):
        raise denied('AUTHENTICATION_REQUIRED', 401)
    try:
        payload = decode_jwt(authorization[7:])
    except Exception:
        raise denied('AUTHENTICATION_REQUIRED', 401) from None
    result = await db.execute(select(Agent).where(Agent.agent_id == payload['sub']))
    agent = result.scalar_one_or_none()
    if (not agent or not agent.is_active or
            type(payload.get('credential_revision')) is not int or
            payload['credential_revision'] != agent.credential_revision):
        raise denied('AUTHENTICATION_REQUIRED', 401)
    return {'authentication_ms': (time.perf_counter()-authentication_started)*1000, 'sub': agent.agent_id, 'domain': agent.domain, 'organization_id': agent.domain,
            'roles': list(agent.roles or []), 'scopes': list(agent.scopes or []),
            'authorization_revision': agent.authorization_revision,
            'credential_revision': agent.credential_revision, 'is_active': agent.is_active}


def require_scope(scope):
    async def dependency(agent=Depends(require_auth)):
        if scope not in agent['scopes']:
            raise denied()
        return agent
    return dependency
