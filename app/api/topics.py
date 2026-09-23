"""Public, administrator-approved metadata only; no free-text broadcast route."""
import asyncio
import json
from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import denied, require_scope
from app.core.redis_pool import get_redis
from app.database import get_db
from app.models.schemas import PublicResource

router = APIRouter(prefix='/api/v1/topics', tags=['Public metadata'])


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    event_type: Literal['contract.updated']
    contract_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    contract_version: str = Field(pattern=r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')


@router.post('/publish')
async def publish(body: PublishRequest, agent=Depends(require_scope('publish')),
                  db: AsyncSession = Depends(get_db)):
    resource = await db.get(PublicResource, (body.contract_id, body.contract_version))
    if not resource or not resource.public or resource.owner_agent_id != agent['sub']:
        raise denied()
    try:
        receivers = await asyncio.wait_for(get_redis().publish('public:contract.updated', json.dumps(body.model_dump())), 3)
    except Exception:
        raise denied('PROCESSING_UNAVAILABLE', 503) from None
    return {'status': 'published', 'receivers': receivers}


@router.get('/subscribe')
async def subscribe(agent=Depends(require_scope('subscribe'))):
    # No legacy arbitrary topic stream. A bounded metadata feed is introduced
    # with the delivery outbox; this endpoint cannot expose legacy content.
    raise denied('LEGACY_SUBSCRIPTION_DISABLED', 410)
