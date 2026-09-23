"""Public metadata cannot carry arbitrary content or expose private resources."""
import pytest
from app.models.schemas import PublicResource
from tests.conftest import TestSessionLocal


@pytest.mark.parametrize('public,owner,expected', [(True,'test-agent-alpha',200),(False,'test-agent-alpha',403),(True,'someone-else',403)])
async def test_publication_boundary(client,registered_agent,public,owner,expected,mock_redis):
    async with TestSessionLocal() as db, db.begin():
        db.add(PublicResource(contract_id='meeting-actions',contract_version='1.0.0',owner_agent_id=owner,public=public))
    body={'event_type':'contract.updated','contract_id':'meeting-actions','contract_version':'1.0.0'}
    r=await client.post('/api/v1/topics/publish',headers=registered_agent['auth_header'],json=body)
    assert r.status_code==expected
    assert bool(mock_redis._channels)==(expected==200)


@pytest.mark.parametrize('extra',[{'content':{'email':'synthetic@example.com'}},{'topic':'anything'},{'event_type':'arbitrary.event'},{'contract_id':'free text'}])
async def test_free_text_rejected(client,registered_agent,extra,mock_redis):
    body={'event_type':'contract.updated','contract_id':'meeting-actions','contract_version':'1.0.0',**extra}
    r=await client.post('/api/v1/topics/publish',headers=registered_agent['auth_header'],json=body)
    assert r.status_code==422 and not mock_redis._channels


async def test_subscription_cannot_reopen_legacy_stream(client,registered_agent):
    r=await client.get('/api/v1/topics/subscribe',headers=registered_agent['auth_header'])
    assert r.status_code==410
