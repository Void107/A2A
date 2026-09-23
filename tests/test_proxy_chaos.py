"""Current adapter failures and closed legacy entry. Real HTTP: verify_upstream.py."""
import pytest
import httpx
from unittest.mock import AsyncMock
from app.adapters.upstream import UpstreamClient, UpstreamFailure, strict_json


@pytest.mark.parametrize('failure,code',[(httpx.ConnectTimeout('synthetic'),'UPSTREAM_TIMEOUT'),
    (httpx.ReadTimeout('synthetic'),'UPSTREAM_TIMEOUT'),(httpx.ConnectError('synthetic'),'UPSTREAM_UNAVAILABLE')])
async def test_transport_failure_does_not_return_data(failure,code):
    client=UpstreamClient({},None)
    client._fetch=AsyncMock(side_effect=failure)
    try:
        with pytest.raises(UpstreamFailure) as raised: await client.fetch('target',{},1000,1)
        assert raised.value.code==code
    finally: await client.close()


@pytest.mark.parametrize('raw',[b'{',b'{"a":1,"a":2}',b'{"value":NaN}',b'['*33+b']'*33])
def test_invalid_upstream_json_fails_closed(raw):
    with pytest.raises(UpstreamFailure): strict_json(raw)


async def test_legacy_query_is_closed_for_valid_current_identity(client,registered_agent):
    r=await client.post('/api/v1/interact/query',headers=registered_agent['auth_header'],json={'schema_id':'anything'})
    assert r.status_code==410 and r.json()['detail']['code']=='LEGACY_QUERY_DISABLED'
