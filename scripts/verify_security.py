"""T02 actual HTTP handlers backed by dedicated PostgreSQL and Redis."""
import asyncio
import subprocess
import sys
import uuid

from verify_real_baseline import ROOT  # installs fixed test-only environment


async def main():
    from check_test_services import main as probe
    await probe()
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT, check=True)
    from app.main import app
    from app.database import AsyncSessionLocal, engine
    from app.models.schemas import Agent, AuditLog, AccessGrant
    from app.core.security import generate_api_key, hash_api_key, create_jwt
    from httpx import AsyncClient, ASGITransport
    from sqlalchemy import select
    suffix = uuid.uuid4().hex[:10]
    admin_id, member_id, outsider_id = ['test-' + n + '-' + suffix for n in ('admin', 'member', 'outsider')]
    admin_key = generate_api_key()
    async with AsyncSessionLocal() as db:
        db.add(Agent(agent_id=admin_id, display_name='Synthetic administrator', callback_url='',
                     data_contract={}, domain='test-org', scopes=['admin', 'audit', 'publish', 'discover', 'query'],
                     roles=['administrator'], api_key_hash=hash_api_key(admin_key), hub_shared_secret_hash=''))
        await db.commit()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            async def token(who, key):
                r = await client.post('/api/v1/auth/token', json={'agent_id': who, 'api_key': key})
                assert r.status_code == 200, r.status_code
                return {'Authorization': 'Bearer ' + r.json()['access_token']}
            admin = await token(admin_id, admin_key)
            assert (await client.post('/api/v1/agents/register', json={'domain': 'trusted'})).status_code == 403
            assert (await client.get('/api/v1/audit/logs')).status_code == 401
            body = {'agent_id': member_id, 'organization_id': 'test-org', 'roles': ['reader'],
                    'scopes': ['audit', 'publish', 'discover', 'query'], 'is_active': True}
            r = await client.put('/api/v2/admin/identities/' + member_id, headers=admin, json=body)
            assert r.status_code == 200, r.status_code
            member_key = r.json()['api_key']
            member = await token(member_id, member_key)
            assert (await client.put('/api/v2/admin/identities/' + member_id, headers=member, json=body)).status_code == 403
            outsider_body = dict(body, agent_id=outsider_id, scopes=[])
            r = await client.put('/api/v2/admin/identities/' + outsider_id, headers=admin, json=outsider_body)
            outsider = await token(outsider_id, r.json()['api_key'])
            assert (await client.get('/api/v1/audit/logs', headers=outsider)).status_code == 403
            async with AsyncSessionLocal() as db:
                db.add_all([AuditLog(source_agent=member_id, target_agent=admin_id, request_id='owned-' + suffix),
                            AuditLog(source_agent=outsider_id, target_agent=outsider_id, request_id='other-' + suffix)])
                await db.commit()
            records = (await client.get('/api/v1/audit/logs', headers=member)).json()['results']
            assert any(r['request_id'] == 'owned-' + suffix for r in records)
            assert not any(r['request_id'] == 'other-' + suffix for r in records)
            assert (await client.get('/api/v1/audit/logs', headers=member, params={'agent_id': outsider_id})).json()['total'] == 0
            grant_id = 'grant-' + suffix
            grant = dict(agent_id=member_id, contract_id='meeting-actions', view_id='internal-project',
                         allowed_meeting_ids=['meeting-001'], active=True)
            assert (await client.put('/api/v2/admin/grants/' + grant_id, headers=admin, json=grant)).status_code == 200
            r = await client.put('/api/v2/admin/grants/' + grant_id, headers=admin, json=dict(grant, active=False))
            assert r.status_code == 200 and r.json()['revision'] == 2
            async with AsyncSessionLocal() as db:
                row = await db.get(AccessGrant, grant_id)
                assert not row.active and row.allowed_meeting_ids == ['meeting-001']
            event = {'event_type': 'contract.updated', 'contract_id': 'test-' + suffix, 'contract_version': '1.0.0'}
            assert (await client.post('/api/v1/topics/publish', headers=member, json=event)).status_code == 403
            uri = '/api/v2/admin/public-resources/' + event['contract_id'] + '/1.0.0'
            assert (await client.put(uri, headers=admin, json={'owner_agent_id': member_id, 'public': True})).status_code == 200
            assert (await client.post('/api/v1/topics/publish', headers=member, json=event)).status_code == 200
            assert (await client.post('/api/v1/topics/publish', headers=admin, json=event)).status_code == 403
            r = await client.post('/api/v1/topics/publish', headers=member, json=dict(event, content={'secret': 'synthetic-private-text'}))
            assert r.status_code == 422 and 'synthetic-private-text' not in r.text
            assert (await client.post('/api/v1/interact/query', headers=member, json={'target_agent': admin_id, 'schema_id': 's'})).status_code == 410
            # Credential rotation invalidates old tokens and old API keys.
            r = await client.post('/api/v2/admin/identities/' + member_id + '/rotate-key', headers=admin)
            assert r.status_code == 200
            new_key = r.json()['api_key']
            assert (await client.get('/api/v1/audit/logs', headers=member)).status_code == 401
            assert (await client.post('/api/v1/auth/token', json={'agent_id': member_id, 'api_key': member_key})).status_code == 401
            member = await token(member_id, new_key)
            assert (await client.put('/api/v2/admin/identities/' + member_id, headers=admin, json=dict(body, is_active=False))).status_code == 200
            assert (await client.get('/api/v1/audit/logs', headers=member)).status_code == 401
            # Even signed claims cannot turn an unregistered identity into an admin.
            forged_context = {'Authorization': 'Bearer ' + create_jwt('unregistered-' + suffix, ['admin'], 'test-org')}
            assert (await client.put('/api/v2/admin/identities/' + member_id, headers=forged_context, json=body)).status_code == 401
            for i in range(21):
                r = await client.post('/api/v1/auth/token', json={'agent_id': 'missing-' + suffix, 'api_key': 'invalid'})
            assert r.status_code == 429
            print('PASS: controlled identity, current scope, audit isolation, grant revisions, public metadata, rotation, disable, rate limit, legacy closure')
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
