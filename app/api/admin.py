"""Explicit administrator provisioning. There is no public self-registration."""
import asyncio
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import denied, require_scope
from app.core.security import generate_api_key, hash_api_key
from app.database import get_db
from app.models.schemas import Agent, AccessGrant, PublicResource

router = APIRouter(prefix='/api/v2/admin', tags=['Administrator'])
SCOPES = {'admin', 'query', 'discover', 'audit', 'publish', 'subscribe', 'contracts:write'}


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Identity(Closed):
    agent_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    organization_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    roles: List[str] = Field(max_length=32)
    scopes: List[str] = Field(max_length=16)
    is_active: bool = True


@router.put('/identities/{agent_id}')
async def provision(agent_id: str, body: Identity, actor=Depends(require_scope('admin')),
                    db: AsyncSession = Depends(get_db)):
    if agent_id != body.agent_id or not set(body.scopes) <= SCOPES:
        raise denied('INVALID_IDENTITY', 422)
    if any(not role or len(role) > 64 for role in body.roles):
        raise denied('INVALID_IDENTITY', 422)
    result = await db.execute(select(Agent).where(Agent.agent_id == agent_id).with_for_update())
    agent = result.scalar_one_or_none()
    key = None
    if agent is None:
        key = generate_api_key()
        agent = Agent(agent_id=agent_id, display_name=agent_id, callback_url='', data_contract={},
                      api_key_hash=await asyncio.to_thread(hash_api_key, key), hub_shared_secret_hash='',
                      authorization_revision=0, credential_revision=1)
        db.add(agent)
    agent.domain, agent.roles, agent.scopes = body.organization_id, body.roles, body.scopes
    agent.is_active = body.is_active
    agent.authorization_revision += 1
    await db.commit()
    result = {'agent_id': agent_id, 'authorization_revision': agent.authorization_revision}
    if key is not None:
        result['api_key'] = key
    return result


@router.post('/identities/{agent_id}/rotate-key')
async def rotate(agent_id: str, actor=Depends(require_scope('admin')), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Agent).where(Agent.agent_id == agent_id).with_for_update())
    agent = result.scalar_one_or_none()
    if agent is None:
        raise denied('IDENTITY_NOT_FOUND', 404)
    key = generate_api_key()
    agent.api_key_hash = await asyncio.to_thread(hash_api_key, key)
    agent.credential_revision += 1
    agent.authorization_revision += 1
    await db.commit()
    return {'api_key': key, 'credential_revision': agent.credential_revision}


class Grant(Closed):
    agent_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    contract_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    view_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    allowed_meeting_ids: List[str] = Field(max_length=1000)
    active: bool


@router.put('/grants/{grant_id}')
async def put_grant(grant_id: str, body: Grant, actor=Depends(require_scope('admin')),
                    db: AsyncSession = Depends(get_db)):
    import re
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', grant_id) or any(
            not re.fullmatch(r'meeting-[0-9]{3}', m) for m in body.allowed_meeting_ids):
        raise denied('INVALID_GRANT', 422)
    subject = (await db.execute(select(Agent).where(Agent.agent_id == body.agent_id).with_for_update())).scalar_one_or_none()
    if subject is None:
        raise denied('IDENTITY_NOT_FOUND', 404)
    grant = await db.get(AccessGrant, grant_id, with_for_update=True)
    if grant is not None and (grant.agent_id, grant.contract_id, grant.view_id) != (body.agent_id, body.contract_id, body.view_id):
        raise denied('GRANT_BINDING_IMMUTABLE', 409)
    if grant is None:
        grant = AccessGrant(grant_id=grant_id, revision=0)
        db.add(grant)
    for key, value in body.model_dump().items():
        setattr(grant, key, value)
    grant.revision += 1
    subject.authorization_revision += 1
    await db.commit()
    return {'grant_id': grant_id, 'revision': grant.revision}


class Publication(Closed):
    owner_agent_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    public: bool


@router.put('/public-resources/{contract_id}/{version}')
async def public_resource(contract_id: str, version: str, body: Publication,
                          actor=Depends(require_scope('admin')), db: AsyncSession = Depends(get_db)):
    import re
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', contract_id) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise denied('INVALID_RESOURCE', 422)
    if await db.scalar(select(Agent.agent_id).where(Agent.agent_id == body.owner_agent_id)) is None:
        raise denied('IDENTITY_NOT_FOUND', 404)
    resource = await db.get(PublicResource, (contract_id, version), with_for_update=True)
    if resource is None:
        resource = PublicResource(contract_id=contract_id, contract_version=version)
        db.add(resource)
    resource.owner_agent_id, resource.public = body.owner_agent_id, body.public
    await db.commit()
    return {'status': 'updated'}
