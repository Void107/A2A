"""Real PG/Redis/OPA/Presidio/provider/Hub and official A2A client integration."""
import asyncio
import copy
import json
import os
import subprocess
import sys
import tempfile
import uuid
import time
from pathlib import Path
from verify_real_baseline import ROOT, OPA_BINARY, PRESIDIO_PYTHON


async def main():
    cold_started = time.perf_counter()
    from check_test_services import main as probe
    await probe()
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT, check=True)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    from app.core.signing import verify, PostgresNonceStore
    from app.core.security import generate_api_key, hash_api_key
    from app.database import AsyncSessionLocal, engine
    from app.models.schemas import Agent
    from redis.asyncio import Redis
    import httpx
    suffix = uuid.uuid4().hex[:8]
    provider, project, partner = ['delivery-' + n + '-' + suffix for n in ('provider', 'project', 'partner')]
    cid = 'meeting-' + suffix
    admin_key = generate_api_key()
    async with AsyncSessionLocal() as db, db.begin():
        db.add(Agent(agent_id=provider, display_name='Synthetic Provider', callback_url='', domain='org-acme',
            roles=['admin'], scopes=['admin', 'contracts:write', 'audit'], data_contract={},
            api_key_hash=hash_api_key(admin_key), hub_shared_secret_hash=''))
    fixture = ROOT / 'docs/implementation/examples'
    raw = json.loads((fixture / 'raw.meeting.json').read_text())
    state = {'raw': raw, 'calls': 0, 'hold': False}
    provider_waiting, release_provider = asyncio.Event(), asyncio.Event()
    state['release'] = release_provider
    from fault_proxy import FaultProxy
    opa_proxy = await FaultProxy('http://127.0.0.1:58181').start()
    presidio_proxy = await FaultProxy('http://127.0.0.1:58182').start()
    key = Ed25519PrivateKey.generate()
    redis = Redis(host='127.0.0.1', port=56379)
    async def provider_http(reader, writer):
        try:
            lines = (await reader.readuntil(b'\r\n\r\n')).decode().split('\r\n')
            method, path, _ = lines[0].split()
            headers = dict(line.split(': ', 1) for line in lines[1:] if ': ' in line)
            body = await reader.readexactly(int(headers.get('Content-Length', 0)))
            assert await verify(headers, method, path, body, {'test-key': key.public_key()}, PostgresNonceStore())
            state['calls'] += 1
            if state['hold']:
                provider_waiting.set()
                await release_provider.wait()
            data = state.get('bytes', json.dumps(state['raw']).encode())
            writer.write(b'HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: ' + str(len(data)).encode() + b'\r\n\r\n')
            if state.get('drip'):
                for byte in data:
                    writer.write(bytes([byte])); await writer.drain(); await asyncio.sleep(.2)
            else:
                writer.write(data)
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally: writer.close()
    server = await asyncio.start_server(provider_http, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    processes, logs = [], []
    with tempfile.TemporaryDirectory(prefix='a2a-delivery-') as temp:
        private = Path(temp) / 'hub.pem'
        private.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())); private.chmod(0o600)
        env = dict(os.environ, PRESIDIO_URL=presidio_proxy.url, OPA_URL=opa_proxy.url, HUB_SIGNING_KEY_FILE=str(private),
            HUB_SIGNING_KEY_ID='test-key', A2A_ENABLED='true',
            METRICS_FILE=str(ROOT / 'docs/verification/resume-core-metrics.jsonl') if os.environ.get('MEASURE_DELIVERY') else '',
            UPSTREAM_ENDPOINTS=json.dumps({provider: {'url': 'http://127.0.0.1:' + str(port) + '/meeting',
                'approved_addresses': ['127.0.0.1'], 'local_test': True}}))
        commands = [(OPA_BINARY, ['run', '--server', '--addr=127.0.0.1:58181', '--disable-telemetry', '--log-level=error', 'policies/contract.rego']),
            (PRESIDIO_PYTHON, ['-m', 'uvicorn', 'examples.presidio.service:app', '--host', '127.0.0.1', '--port', '58182', '--no-access-log']),
            (sys.executable, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '58185', '--no-access-log'])]
        try:
            for i, (executable, args) in enumerate(commands):
                log = (ROOT / ('docs/verification/delivery-service-' + str(i) + '.log')).open('w'); logs.append(log)
                processes.append(subprocess.Popen([executable] + args, cwd=ROOT, env=env, stdout=log, stderr=log))
            async with httpx.AsyncClient(base_url='http://127.0.0.1:58185', timeout=35) as http:
                for path in ['http://127.0.0.1:58185/ready', 'http://127.0.0.1:58182/ready', 'http://127.0.0.1:58181/health']:
                    for _ in range(600):
                        if any(p.poll() is not None for p in processes): raise RuntimeError('dependency process failed; see service logs')
                        try:
                            if (await http.get(path)).status_code == 200: break
                        except httpx.HTTPError: pass
                        await asyncio.sleep(.1)
                    else: raise RuntimeError('dependency timeout')
                async def login(who, key):
                    r = await http.post('/api/v1/auth/token', json={'agent_id': who, 'api_key': key})
                    assert r.status_code == 200, r.text
                    return {'Authorization': 'Bearer ' + r.json()['access_token']}
                admin = await login(provider, admin_key)
                identities = {}
                for who, organization, role in [(project, 'org-acme', 'project-agent'), (partner, 'org-partner', 'collaboration-agent')]:
                    r = await http.put('/api/v2/admin/identities/' + who, headers=admin, json={'agent_id': who,
                        'organization_id': organization, 'roles': [role], 'scopes': ['query', 'discover', 'audit'], 'is_active': True})
                    assert r.status_code == 200, r.text
                    identities[who] = await login(who, r.json()['api_key'])
                contract = json.loads((fixture / 'contract.meeting.json').read_text()); contract['contract_id'] = cid
                contract['policies'][1]['principal']['agent_ids'] = [partner]
                r = await http.post('/api/v2/contracts', headers=admin, json={'provider_agent_id': provider, 'contract': contract})
                assert r.status_code == 201, r.text
                base = '/api/v2/contracts/' + cid + '/1.0.0'
                assert (await http.post(base + '/activate', headers=admin)).status_code == 409
                assert (await http.post(base + '/validate', headers=admin)).status_code == 200
                from examples.meeting_views.consume import consume
                requirements = json.loads((fixture / 'consumer.requirements.json').read_text())['consumers']
                bundle = {'consumers': []}
                for spec, name in zip(requirements, ['expected.internal.json', 'expected.external.json']):
                    expected = json.loads((fixture / name).read_text())
                    bundle['consumers'].append({k: spec[k] for k in ['consumer_id','view_id','required_paths']})
                    bundle['consumers'][-1].update(source=raw, expected_output=expected,
                        expected_tasks=consume(expected, spec['view_id']), forbidden_paths=spec.get('forbidden_paths', []))
                checked = await http.post(base + '/check', headers=admin, json=bundle)
                assert checked.status_code == 200 and all(c['result'] == 'PASS' for c in checked.json()['consumers']), checked.text

                r = await http.post(base + '/activate', headers=admin); assert r.status_code == 200, r.text
                assert (await http.post(base + '/default', headers=admin)).status_code == 200
                assert (await http.post('/api/v2/contracts', headers=admin, json={'provider_agent_id': provider, 'contract': contract})).status_code == 409
                grants = {}
                for who, view in [(project, 'internal-project'), (partner, 'external-collaboration')]:
                    grant = {'agent_id': who, 'contract_id': cid, 'view_id': view, 'allowed_meeting_ids': ['meeting-001'], 'active': True}
                    grants[who] = grant
                    assert (await http.put('/api/v2/admin/grants/' + who, headers=admin, json=grant)).status_code == 200
                    views = (await http.get('/api/v2/contracts/discover', headers=identities[who])).json()
                    assert len(views) == 1 and views[0]['view_id'] == view
                def request(view):
                    return {'target_agent': provider, 'contract_id': cid, 'contract_version': '1.0.0', 'view_id': view, 'query': {'meeting_id': 'meeting-001'}}
                outputs = {}
                for who, view, expected in [(project, 'internal-project', 'expected.internal.json'), (partner, 'external-collaboration', 'expected.external.json')]:
                    r = await http.post('/api/v2/query', headers=identities[who], json=request(view))
                    assert r.status_code == 200, r.text
                    outputs[view] = r.json()
                    assert r.json()['data'] == json.loads((fixture / expected).read_text())
                    receipt = await http.get('/api/v2/receipts/' + r.json()['request_id'], headers=identities[who])
                    assert receipt.status_code == 200 and receipt.json()['status'] == 'ready_to_send'
                    assert receipt.json()['validation'] == dict(source='passed', output='passed', obligations='passed')
                    assert receipt.json()['policy_revision'] == 'contract-policy-1'
                if not os.environ.get('MEASURE_DELIVERY'):
                    from verify_api_matrix import verify as verify_matrix
                    await verify_matrix(http, admin, provider, identities, project, partner, contract, request)
                    from verify_boundaries import verify as verify_boundaries
                    await verify_boundaries(http, identities, project, partner, request, contract, state, raw, opa_proxy, presidio_proxy)
                    provider_waiting.clear(); release_provider.clear()
                # Repeat in reverse order through the public API; consume actual outputs.
                from examples.meeting_views.consume import consume
                consumer_results = {}
                for who, view in [(partner, 'external-collaboration'), (project, 'internal-project')]:
                    r = await http.post('/api/v2/query', headers=identities[who], json=request(view))
                    assert r.status_code == 200 and r.json()['data'] == outputs[view]['data']
                    consumer_results[view] = consume(r.json()['data'], view)
                assert len(consumer_results['internal-project']) == len(consumer_results['external-collaboration']) == 2
                assert [t['assignee'] for t in consumer_results['internal-project']] == ['alice@example.com', 'bob@example.com']
                for tasks in consumer_results.values():
                    assert [t['due_date'] for t in tasks] == ['2026-09-20', '2026-09-21']
                assert all(t['assignment_state'] == 'unassigned' for t in consumer_results['external-collaboration'])
                (ROOT / 'docs/verification/t08-consumers.json').write_text(json.dumps(consumer_results, indent=2)+'\n')
                for mutation in [lambda d: d['action_items'][0].update(private_note='synthetic'),
                                 lambda d: d['action_items'][0].update(due_date=12345),
                                 lambda d: d['action_items'][0].pop('owner_email'),
                                 lambda d: d.update(action_items={}),
                                 lambda d: d.update(meeting_id='email@example.com')]:
                    state['raw'] = copy.deepcopy(raw); mutation(state['raw'])
                    r = await http.post('/api/v2/query', headers=identities[partner], json=request('external-collaboration'))
                    assert r.status_code == 502 and r.json()['code'] == 'UPSTREAM_SCHEMA_MISMATCH' and 'data' not in r.json()
                state['raw'] = raw
                for query in [{}, {'meeting_id': 'meeting-001', 'extra': True}]:
                    invalid = request('external-collaboration'); invalid['query'] = query
                    assert (await http.post('/api/v2/query', headers=identities[partner], json=invalid)).status_code == 422
                assert (await http.post('/api/v2/query', headers=identities[partner], json=request('internal-project'))).status_code == 403
                before = state['calls']
                wrong = request('external-collaboration'); wrong['query']['meeting_id'] = 'meeting-002'
                assert (await http.post('/api/v2/query', headers=identities[partner], json=wrong)).status_code == 403
                assert state['calls'] == before
                state['raw'] = dict(raw, meeting_id='meeting-002')
                assert (await http.post('/api/v2/query', headers=identities[partner], json=request('external-collaboration'))).json()['code'] == 'UPSTREAM_RESOURCE_MISMATCH'
                state['raw'] = dict(raw, secret='synthetic')
                assert (await http.post('/api/v2/query', headers=identities[partner], json=request('external-collaboration'))).json()['code'] == 'UPSTREAM_SCHEMA_MISMATCH'
                state['raw'] = raw
                # A disconnected HTTP caller cannot turn a prepared receipt into a received acknowledgement.
                from sqlalchemy import select, func
                from app.models.schemas import DeliveryReceipt
                async with AsyncSessionLocal() as db:
                    before_receipts = set((await db.execute(select(DeliveryReceipt.request_id).where(DeliveryReceipt.source_agent == project))).scalars())
                state['hold'] = True
                reader, writer = await asyncio.open_connection('127.0.0.1', 58185)
                encoded = json.dumps(request('internal-project')).encode()
                header = ('POST /api/v2/query HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: ' + identities[project]['Authorization'] +
                          '\r\nContent-Type: application/json\r\nContent-Length: ' + str(len(encoded)) + '\r\nConnection: close\r\n\r\n').encode()
                writer.write(header + encoded); await writer.drain()
                await asyncio.wait_for(provider_waiting.wait(), 5)
                writer.close(); await writer.wait_closed(); release_provider.set()
                disconnected_ids = set()
                for _ in range(100):
                    async with AsyncSessionLocal() as db:
                        rows = (await db.execute(select(DeliveryReceipt).where(DeliveryReceipt.source_agent == project))).scalars().all()
                        disconnected_ids = {r.request_id for r in rows} - before_receipts
                        assert all(r.status == 'ready_to_send' for r in rows)
                    if disconnected_ids: break
                    await asyncio.sleep(.05)
                assert len(disconnected_ids) == 1
                state['hold'] = False; provider_waiting.clear(); release_provider.clear()
                retried = await http.post('/api/v2/query', headers=identities[project], json=request('internal-project'))
                assert retried.status_code == 200 and retried.json()['request_id'] not in disconnected_ids
                print('PASS: real client disconnect after authorization, durable ready_to_send only, retry creates a new reauthorized receipt')
                if os.environ.get('MEASURE_DELIVERY'):
                    cold_ms = (time.perf_counter() - cold_started) * 1000
                    samples, summaries = [], []
                    for who, view in [(project, 'internal-project'), (partner, 'external-collaboration')]:
                        for concurrency in [1, 5, 10]:
                            slots = asyncio.Semaphore(concurrency)
                            async def attempt(index, warmup=False):
                                async with slots:
                                    started = time.perf_counter()
                                    try:
                                        r = await http.post('/api/v2/query', headers=identities[who], json=request(view))
                                        status = r.status_code
                                    except httpx.HTTPError:
                                        status = 0
                                    return {'view_id':view,'concurrency':concurrency,'index':index,'warmup':warmup,
                                            'status':status,'milliseconds':(time.perf_counter()-started)*1000}
                            samples.extend(await asyncio.gather(*(attempt(i, True) for i in range(5))))
                            started = time.perf_counter()
                            batch = await asyncio.gather(*(attempt(i) for i in range(100)))
                            samples.extend(batch)
                            values = sorted(r['milliseconds'] for r in batch)
                            summaries.append({'view_id':view,'concurrency':concurrency,'attempts':100,
                                'successes':sum(r['status']==200 for r in batch), 'errors':sum(r['status']!=200 for r in batch),
                                'timeouts':sum(r['status'] in [0,504] for r in batch),
                                'p50_ms':values[49], 'p95_ms':values[94], 'throughput':100/(time.perf_counter()-started)})
                    from sqlalchemy import select, func
                    from app.models.schemas import OutboxEvent
                    async with AsyncSessionLocal() as db:
                        pending = await db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.processed.is_(False)))
                    report = {'environment':'macOS host Python 3.12.14, Docker PG17.6/Redis7.4.5, host OPA1.0.0 and separate Presidio2.2.360',
                              'cold_setup_and_first_views_ms':cold_ms, 'warmup_per_group':5,
                              'source_bytes':len(json.dumps(raw).encode()), 'samples':samples,'summaries':summaries,
                              'outbox_pending_at_finish':pending, 'limits':'local measurement; authorization phase measures OPA, excluding initial JWT/DB identity resolution; no production SLO'}
                    (ROOT / 'docs/verification/resume-performance.json').write_text(json.dumps(report, indent=2)+'\n')
                    print(json.dumps({'performance_summaries':summaries,'outbox_pending':pending}))
                    print('PASS: 600 measured attempts plus 30 warmup attempts recorded without dropping failures')
                    return
                # Official SDK in this process, actual Hub server in another.
                from a2a.client import A2AClient, A2ACardResolver
                from a2a.types import SendMessageRequest, MessageSendParams, Message, Part, DataPart
                from app.adapters.a2a_transport import EXTENSION
                async with httpx.AsyncClient(headers=dict(identities[partner], **{'X-A2A-Extensions': EXTENSION}), timeout=35) as ahttp:
                    card = await A2ACardResolver(ahttp, 'http://127.0.0.1:58185/a2a').get_agent_card()
                    client = A2AClient(ahttp, agent_card=card)
                    async def send(view):
                        return await client.send_message(SendMessageRequest(id=uuid.uuid4().hex, params=MessageSendParams(message=Message(
                            message_id=uuid.uuid4().hex, role='user', parts=[Part(root=DataPart(data=request(view)))]))))
                    response = await send('external-collaboration')
                    assert response.root.result.parts[0].root.data['data'] == outputs['external-collaboration']['data']
                    response = await send('internal-project'); assert response.root.error.message == 'ACCESS_DENIED'
                    denied_lookup = await http.get('/api/v2/receipts/' + response.root.error.data['request_id'], headers=identities[partner])
                    assert denied_lookup.json()['diagnostics']['stage'] == 'binding'
                    assert denied_lookup.json()['diagnostics']['contract_digest'] is None
                    ahttp.headers.update(identities[project])
                    response = await send('internal-project')
                    assert response.root.result.parts[0].root.data['data'] == outputs['internal-project']['data']
                    ahttp.headers.update(identities[partner])
                    ahttp.headers.pop('X-A2A-Extensions')
                    response = await send('external-collaboration'); assert response.root.error.code == -32602
                # EX-04: a real authenticated identity with a self-claimed internal role still lacks a current grant.
                stranger = 'untrusted-' + suffix
                r = await http.put('/api/v2/admin/identities/' + stranger, headers=admin, json={'agent_id':stranger,
                    'organization_id':'org-other','roles':['project-agent'],'scopes':['query'],'is_active':True})
                stranger_headers = await login(stranger, r.json()['api_key'])
                r = await http.post('/api/v2/query', headers=stranger_headers, json=request('external-collaboration'))
                assert r.status_code == 403 and 'data' not in r.json()
                # EX-10: real OPA process returns a malformed decision; no upstream fetch is permitted.
                policy_list = (await http.get('http://127.0.0.1:58181/v1/policies')).json()['result']
                assert len(policy_list) == 1
                policy_url = 'http://127.0.0.1:58181/v1/policies/' + policy_list[0]['id']
                try:
                    r = await http.put(policy_url, content='package hub.contract\nimport rego.v1\ndecision := {}')
                    assert r.status_code == 200
                    before = state['calls']
                    r = await http.post('/api/v2/query', headers=identities[project], json=request('internal-project'))
                    assert r.status_code == 503 and r.json()['code'] == 'PROCESSING_UNAVAILABLE' and state['calls'] == before
                finally:
                    assert (await http.put(policy_url, content=(ROOT / 'policies/contract.rego').read_bytes())).status_code == 200
                assert (await http.post('/api/v2/query', headers=identities[project], json=request('internal-project'))).status_code == 200
                # Server-side publication gates, with actual processing and consumer checks.
                async def draft_variant(document):
                    r = await http.post('/api/v2/contracts', headers=admin, json={'provider_agent_id': provider, 'contract': document})
                    assert r.status_code == 201, r.text
                    path = '/api/v2/contracts/' + cid + '/' + document['contract_version']
                    assert (await http.post(path + '/validate', headers=admin)).status_code == 200
                    return path
                compatible = copy.deepcopy(contract); compatible['contract_version'] = '1.0.1'
                path = await draft_variant(compatible)
                assert (await http.post(path + '/check', headers=admin, json=bundle)).status_code == 200
                assert (await http.post(path + '/activate', headers=admin)).status_code == 200
                # The default switches while an already-authorized old-version request is at the provider barrier.
                state['hold'] = True
                pinned = asyncio.create_task(http.post('/api/v2/query', headers=identities[project], json=request('internal-project')))
                await asyncio.wait_for(provider_waiting.wait(), 5)
                assert (await http.post(path + '/default', headers=admin)).status_code == 200
                release_provider.set()
                pinned_result = await pinned
                assert pinned_result.json()['contract_version'] == '1.0.0' and pinned_result.json()['data'] == outputs['internal-project']['data']
                state['hold'] = False; provider_waiting.clear(); release_provider.clear()
                # Removing owner_name preserves the registered assignment task but changes structure.
                breaking = copy.deepcopy(contract); breaking['contract_version'] = '1.1.0'
                v = breaking['views'][0]; v['projection'].remove('action_items[*].owner_name')
                item = v['output_schema']['properties']['action_items']['items']
                item['properties'].pop('owner_name'); item['required'].remove('owner_name')
                migrated = copy.deepcopy(bundle); migrated['migration_id'] = 'synthetic-owner-name-removal'
                for item in migrated['consumers'][0]['expected_output']['action_items']: item.pop('owner_name')
                path = await draft_variant(breaking)
                check = (await http.post(path + '/check', headers=admin, json=migrated)).json()
                r = await http.post(path + '/activate', headers=admin, json={'acknowledge_report_digest': check['report_digest']})
                assert r.status_code == 409 and r.json()['detail']['code'] == 'NEW_MAJOR_VERSION_REQUIRED', r.text
                breaking['contract_version'] = '2.0.0'; path = await draft_variant(breaking)
                check = (await http.post(path + '/check', headers=admin, json=migrated)).json()
                assert (await http.post(path + '/activate', headers=admin)).status_code == 409
                r = await http.post(path + '/activate', headers=admin, json={'acknowledge_report_digest': check['report_digest']})
                assert r.status_code == 200, r.text
                assert (await http.post(path + '/default', headers=admin)).status_code == 409
                check = (await http.post(path + '/check?default=true', headers=admin, json=migrated)).json()
                assert (await http.post(path + '/default', headers=admin, json={'acknowledge_report_digest': check['report_digest']})).status_code == 200
                # Current request explicitly pins 1.0.0 despite a new default.
                assert (await http.post('/api/v2/query', headers=identities[project], json=request('internal-project'))).json()['data'] == outputs['internal-project']['data']
                unknown = copy.deepcopy(contract); unknown['contract_version'] = '3.0.0'
                unknown['views'][1]['output_schema']['properties']['title']['maxLength'] = 500
                path = await draft_variant(unknown)
                assert (await http.post(path + '/activate', headers=admin)).status_code == 409
                invalid = copy.deepcopy(contract); invalid['contract_version'] = '9.0.0'; invalid['policies'][0]['conditions'] = {'unknown': True}
                assert (await http.post('/api/v2/contracts', headers=admin, json={'provider_agent_id': provider, 'contract': invalid})).status_code == 422
                print('PASS: publication consumer checks, compatible patch, breaking same-major rejection, explicit major migration and default acknowledgement, unknown change blocked, pinned old version')
                # Real in-flight revoke: provider barrier is reached only after OPA authorization.
                state['hold'] = True
                waiting_query = asyncio.create_task(http.post('/api/v2/query', headers=identities[partner], json=request('external-collaboration')))
                await asyncio.wait_for(provider_waiting.wait(), 5)
                assert (await http.put('/api/v2/admin/grants/' + partner, headers=admin, json=dict(grants[partner], active=False))).status_code == 200
                release_provider.set()
                denied_response = await waiting_query
                assert denied_response.status_code == 403 and 'data' not in denied_response.json()
                failure_lookup = await http.get('/api/v2/receipts/' + denied_response.json()['request_id'], headers=identities[partner])
                assert failure_lookup.status_code == 200 and failure_lookup.json()['status'] == 'failed'
                metadata = failure_lookup.json()['diagnostics']
                assert metadata['stage'] == 'receipt' and metadata['obligations'] == 'passed'
                assert metadata['source_validation'] == metadata['output_validation'] == 'passed'
                assert metadata['contract_digest'] and metadata['policy_revision'] and metadata['profile_revision']
                assert metadata['completed_processors'] == ['external-email-redaction']
                assert (await http.get('/api/v2/receipts/' + denied_response.json()['request_id'], headers=identities[project])).status_code == 404
                state['hold'] = False
                provider_waiting.clear(); release_provider.clear()
                # Redis is optional for existing-token delivery and outbox; provider nonce uses PG.
                await asyncio.to_thread(subprocess.run, ['docker', 'compose', '-f', 'compose.test.yaml', 'stop', 'redis'], cwd=ROOT, check=True)
                try:
                    r = await http.post('/api/v2/query', headers=identities[project], json=request('internal-project'))
                    assert r.status_code == 200, r.text
                finally:
                    await asyncio.to_thread(subprocess.run, ['docker', 'compose', '-f', 'compose.test.yaml', 'up', '-d', '--wait', 'redis'], cwd=ROOT, check=True)
                # PG stops after authenticated signed upstream request, before receipt persistence.
                state['hold'] = True
                pending = asyncio.create_task(http.post('/api/v2/query', headers=identities[project], json=request('internal-project')))
                await asyncio.wait_for(provider_waiting.wait(), 5)
                await asyncio.to_thread(subprocess.run, ['docker', 'compose', '-f', 'compose.test.yaml', 'stop', 'postgres'], cwd=ROOT, check=True)
                try:
                    release_provider.set()
                    r = await pending
                    assert r.status_code == 503 and r.json()['code'] == 'AUDIT_PERSISTENCE_UNAVAILABLE' and 'data' not in r.json()
                finally:
                    await asyncio.to_thread(subprocess.run, ['docker', 'compose', '-f', 'compose.test.yaml', 'up', '-d', '--wait', 'postgres'], cwd=ROOT, check=True)
                state['hold'] = False
                # Required processing and policy services fail closed after successful requests.
                assert (await http.put('/api/v2/admin/grants/' + partner, headers=admin, json=grants[partner])).status_code == 200
                processes[1].terminate(); processes[1].wait(timeout=5)
                r = await http.post('/api/v2/query', headers=identities[partner], json=request('external-collaboration'))
                assert r.status_code == 503 and r.json()['code'] == 'PROCESSING_UNAVAILABLE' and 'data' not in r.json()
                rest_failure = await http.get('/api/v2/receipts/' + r.json()['request_id'], headers=identities[partner])
                rest_diagnostics = rest_failure.json()['diagnostics']
                assert rest_diagnostics['stage'] == 'processing' and rest_diagnostics['profile_revision'] is None
                assert rest_diagnostics['source_validation'] == 'passed' and rest_diagnostics['output_validation'] == 'unknown'
                async with httpx.AsyncClient(headers=dict(identities[partner], **{'X-A2A-Extensions': EXTENSION}), timeout=35) as failed_http:
                    failed_client = A2AClient(failed_http, agent_card=card)
                    response = await failed_client.send_message(SendMessageRequest(id=uuid.uuid4().hex, params=MessageSendParams(message=Message(
                        message_id=uuid.uuid4().hex, role='user', parts=[Part(root=DataPart(data=request('external-collaboration')))]))))
                    assert response.root.error.message == 'PROCESSING_UNAVAILABLE'
                    failed_receipt = await http.get('/api/v2/receipts/' + response.root.error.data['request_id'], headers=identities[partner])
                    assert failed_receipt.json()['diagnostics'] == rest_diagnostics
                    print('PASS: persisted failure metadata, honest unexecuted stages, REST/official A2A diagnostic parity')
                processes[0].terminate(); processes[0].wait(timeout=5)
                r = await http.post('/api/v2/query', headers=identities[project], json=request('internal-project'))
                assert r.status_code == 503 and r.json()['code'] == 'PROCESSING_UNAVAILABLE' and 'data' not in r.json()
                executable, args = commands[0]
                processes[0] = subprocess.Popen([executable] + args, cwd=ROOT, env=env, stdout=logs[0], stderr=logs[0])
                for _ in range(100):
                    try:
                        if (await http.get('http://127.0.0.1:58181/health')).status_code == 200: break
                    except httpx.HTTPError: pass
                    await asyncio.sleep(.05)
                else: raise AssertionError('OPA restart not ready')
                assert (await http.post('/api/v2/query', headers=identities[project], json=request('internal-project'))).status_code == 200
                print('PASS AC-06: actual OPA process stop denies and restart authorizes new delivery', flush=True)
                assert (await http.put('/api/v2/admin/grants/' + partner, headers=admin, json=dict(grants[partner], active=False))).status_code == 200
                assert (await http.post('/api/v2/query', headers=identities[partner], json=request('external-collaboration'))).status_code == 403
                assert (await http.get('/api/v2/contracts/discover', headers=identities[partner])).json() == []
                r = await http.put('/api/v2/admin/identities/' + project, headers=admin, json={'agent_id':project,
                    'organization_id':'org-acme','roles':['project-agent'],'scopes':['query','discover','audit'],'is_active':False})
                assert r.status_code == 200
                r = await http.post('/api/v2/query', headers=identities[project], json=request('internal-project'))
                assert r.status_code == 401 and 'data' not in r.json()
                for log_index in range(len(logs)):
                    log_text = (ROOT / ('docs/verification/delivery-service-' + str(log_index) + '.log')).read_text()
                    assert 'alice@example.com' not in log_text and admin_key not in log_text
                    assert all(headers['Authorization'] not in log_text for headers in identities.values())
                print('PASS: failure receipt ownership and ordinary logs omit synthetic email, credentials and bearer tokens')
                print('PASS: EX-01..EX-10 with inactive identity represented by AUTHENTICATION_REQUIRED; in-flight pinned snapshot/default switch; malformed real OPA decision prevents fetch and recovers')
                (ROOT / 'docs/verification/t08-outputs.json').write_text(json.dumps(outputs, indent=2)+'\n')
                print('PASS: real in-flight revoke, Redis-off delivery, PG pre-receipt failure, Presidio/OPA outage; real full stack REST dual views, scoped discovery, immutable version, signed provider, resource/source rejection, receipts, revocation; official A2A BOTH views/deny/extension/dependency failure; API consumer effects/source mutations/reverse order')
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
            for log in logs: log.close()
            await opa_proxy.close(); await presidio_proxy.close()
    server.close(); await server.wait_closed()
    await redis.aclose(); await engine.dispose()


if __name__ == '__main__': asyncio.run(main())
