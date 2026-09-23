"""Additional acceptance matrix against the actual running Hub and PostgreSQL."""
import copy
import uuid
import time
import jwt


async def verify(http, admin, provider, identities, project, partner, contract, request):
    from app.database import AsyncSessionLocal
    from app.models.schemas import ContractVersion
    from app.config import settings
    from sqlalchemy import select
    mutations = {
        'effect': lambda c: c['policies'][0].update(effect='unknown'),
        'condition': lambda c: c['policies'][0].update(conditions={'purpose': 'private-test'}),
        'duplicate_view': lambda c: c['views'].append(copy.deepcopy(c['views'][0])),
        'duplicate_policy': lambda c: c['policies'].append(copy.deepcopy(c['policies'][0])),
        'missing_processor': lambda c: c['views'][1].update(processors=[]),
        'path': lambda c: c['views'][1]['processors'][0].update(paths=['**.secret']),
        'spec': lambda c: c.update(spec_version='future'),
        'reference': lambda c: c['source_schema'].update({'$ref': 'https://example.com/private'}),
        'language': lambda c: c['views'][1]['processors'][0].update(language='zh'),
        'entity': lambda c: c['views'][1]['processors'][0].update(entities=['PERSON']),
    }
    for name, mutate in mutations.items():
        c = copy.deepcopy(contract); c['contract_id'] = 'negative-' + uuid.uuid4().hex[:12]; mutate(c)
        response = await http.post('/api/v2/contracts', headers=admin, json={'provider_agent_id': provider, 'contract': c})
        assert response.status_code == 422 and response.json()['detail']['code'] == 'CONTRACT_INVALID', name
        assert response.json()['detail']['rule']
        # Simulate corrupted/malicious persisted drafts: activation must revalidate,
        # even if a client/state importer claims they were already validated.
        for state, action in [('draft', 'validate'), ('validated', 'activate')]:
            c['contract_id'] = 'negative-' + uuid.uuid4().hex[:12]
            async with AsyncSessionLocal() as db, db.begin():
                db.add(ContractVersion(contract_id=c['contract_id'], contract_version='1.0.0',
                    owner_agent_id=provider, provider_agent_id=provider, document=c, digest='0'*64, state=state))
            response = await http.post('/api/v2/contracts/' + c['contract_id'] + '/1.0.0/' + action, headers=admin)
            assert response.status_code == 422 and response.json()['detail']['code'] == 'CONTRACT_INVALID', (name, action)
            async with AsyncSessionLocal() as db:
                assert (await db.get(ContractVersion, (c['contract_id'], '1.0.0'))).state != 'active'
    assert (await http.post('/api/v2/contracts', headers=admin, json={
        'provider_agent_id': provider, 'contract': contract, 'validated': True})).status_code == 422
    print('PASS AC-01: 10 invalid variants x save/validate/activate; forged validated flag; no active row', flush=True)
    no_id = 'no-scope-' + uuid.uuid4().hex[:10]
    response = await http.put('/api/v2/admin/identities/' + no_id, headers=admin,
        json=dict(agent_id=no_id, organization_id='org-partner', roles=[], scopes=[], is_active=True))
    assert response.status_code == 200
    key = response.json()['api_key']
    login = await http.post('/api/v1/auth/token', json={'agent_id': no_id, 'api_key': key})
    assert login.status_code == 200
    none = {'Authorization': 'Bearer ' + login.json()['access_token']}
    routes = [('GET', '/api/v2/contracts/discover', None), ('POST', '/api/v2/query', request('internal-project')),
        ('POST', '/api/v2/contracts', {'provider_agent_id': provider, 'contract': contract}),
        ('GET', '/api/v1/audit/logs', None), ('POST', '/api/v1/topics/publish',
            {'event_type': 'contract.updated', 'contract_id': contract['contract_id'], 'contract_version': '1.0.0'})]
    for method, path, body in routes:
        assert (await http.request(method, path, headers=none, json=body)).status_code == 403
    token = identities[partner]['Authorization'][7:]
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=['HS256'])
    invalid = [{}, {'Authorization': 'Bearer invalid'},
        {'Authorization': 'Bearer ' + jwt.encode(dict(payload, exp=int(time.time())-10), settings.JWT_SECRET, algorithm='HS256')},
        {'Authorization': 'Bearer ' + jwt.encode(payload, 'synthetic-wrong-secret-at-least-32-bytes', algorithm='HS256')}]
    for headers in invalid:
        for method, path, body in routes:
            assert (await http.request(method, path, headers=headers, json=body)).status_code == 401
    claimed = dict(payload, domain='org-acme', organization_id='org-acme', roles=['project-agent'], scopes=['admin','contracts:write','query'])
    headers = {'Authorization': 'Bearer ' + jwt.encode(claimed, settings.JWT_SECRET, algorithm='HS256')}
    assert (await http.post('/api/v2/query', headers=headers, json=request('internal-project'))).status_code == 403
    visible = (await http.get('/api/v2/contracts/discover', headers=headers)).json()
    assert visible and all(v['view_id']=='external-collaboration' for v in visible)
    assert (await http.post('/api/v2/contracts', headers=headers, json={'provider_agent_id': provider, 'contract': contract})).status_code == 403
    assert (await http.post('/api/v1/agents/register', json={'domain':'org-acme','roles':['admin']})).status_code == 403
    assert (await http.post('/api/v1/auth/token', json={'agent_id': no_id, 'api_key':key, 'domain':'org-acme'})).status_code == 422
    print('PASS AC-02/03: 5 endpoints x missing/tampered/expired/wrong-signature/no-scope; signed self-claimed roles cannot override database identity', flush=True)

    # Current scopes do not grant ownership of another provider's contract.
    update=dict(agent_id=no_id, organization_id='org-partner', roles=[], scopes=['contracts:write','publish','audit'], is_active=True)
    assert (await http.put('/api/v2/admin/identities/'+no_id,headers=admin,json=update)).status_code==200
    assert (await http.post('/api/v2/contracts',headers=none,json={'provider_agent_id':no_id,'contract':contract})).status_code==403
    assert (await http.post('/api/v2/contracts/'+contract['contract_id']+'/1.0.0/retire',headers=none)).status_code==403
    assert (await http.put('/api/v2/admin/identities/'+no_id,headers=admin,json=dict(update,is_active=False))).status_code==200
    for method,path,body in routes:
        assert (await http.request(method,path,headers=none,json=body)).status_code==401
    print('PASS AC-02/03: current write scope cannot override contract ownership; disabled identity rejected on every endpoint',flush=True)
