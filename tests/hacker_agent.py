"""Default-collected attack regressions against current authentication boundaries."""
import pytest
from sqlalchemy import select
from tests.conftest import make_jwt,make_auth_header,make_expired_jwt,TestSessionLocal
from app.models.schemas import Agent


@pytest.mark.parametrize('token',[make_jwt('unregistered',['admin','query'],domain='org-acme'),
                                  make_expired_jwt('unregistered'),'forged-token'])
async def test_untrusted_claims_never_create_identity(client,token):
    r=await client.get('/api/v2/contracts/discover',headers=make_auth_header(token))
    assert r.status_code==401


async def test_old_token_after_disable_denied(client,registered_agent):
    async with TestSessionLocal() as db,db.begin():
        actor=await db.scalar(select(Agent).where(Agent.agent_id == registered_agent['agent_id'])); actor.is_active=False
    r=await client.get('/api/v2/contracts/discover',headers=registered_agent['auth_header'])
    assert r.status_code==401


async def test_no_scope_cannot_read_audit_or_publish(client,provision_identity):
    actor=await provision_identity('restricted',scopes=[])
    r=await client.get('/api/v1/audit/logs',headers=actor['auth_header'])
    assert r.status_code==403
    r=await client.post('/api/v1/topics/publish',headers=actor['auth_header'],json={'event_type':'contract.updated','contract_id':'meeting-actions','contract_version':'1.0.0'})
    assert r.status_code==403
