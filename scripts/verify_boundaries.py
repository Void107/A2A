"""Controlled faults through the public delivery endpoint with real dependencies."""
import asyncio
import json
import time

async def verify(http, identities, project, partner, request, contract, state, raw, opa, presidio):
    headers=identities[project]
    for proxy, actor, view in [(opa,project,'internal-project'),(presidio,partner,'external-collaboration')]:
        for mode in ['error','invalid','delay']:
            proxy.mode=mode; before=state['calls']; start=time.perf_counter()
            response=await http.post('/api/v2/query',headers=identities[actor],json=request(view))
            assert response.status_code==503 and response.json()['code']=='PROCESSING_UNAVAILABLE' and 'data' not in response.json(), (mode,response.status_code)
            assert time.perf_counter()-start<5
            if proxy is opa: assert state['calls']==before
            proxy.mode='normal'; before_calls=proxy.calls
            assert (await http.post('/api/v2/query',headers=identities[actor],json=request(view))).status_code==200
            assert proxy.calls>before_calls
    # Restore during an already-waiting request; it must obtain a fresh real decision.
    opa.mode='barrier';opa.entered.clear();opa.release.clear()
    pending=asyncio.create_task(http.post('/api/v2/query',headers=headers,json=request('internal-project')))
    await asyncio.wait_for(opa.entered.wait(),2);opa.mode='normal';opa.release.set()
    assert (await pending).status_code==200
    print('PASS AC-06/13: real TCP dependency HTTP errors/invalid JSON/deadlines; new requests reauthorize; recovery during request',flush=True)
    limit=contract['delivery']['max_response_bytes']; encoded=json.dumps(raw).encode()
    for size in [limit-1,limit,limit+1]:
        state['bytes']=encoded+b' '*(size-len(encoded))
        response=await http.post('/api/v2/query',headers=headers,json=request('internal-project'))
        assert response.status_code==(200 if size<=limit else 413)
        if size>limit: assert response.json()['code']=='PAYLOAD_TOO_LARGE' and 'data' not in response.json()
    state['bytes']=b'invalid synthetic body'
    response=await http.post('/api/v2/query',headers=headers,json=request('internal-project'))
    assert response.status_code==502 and response.json()['code']=='UPSTREAM_INVALID_JSON'
    state.pop('bytes')
    state['drip']=True; started=time.perf_counter()
    response=await http.post('/api/v2/query',headers=headers,json=request('internal-project'))
    assert response.status_code==504 and response.json()['code'] in ('UPSTREAM_TIMEOUT','DELIVERY_TIMEOUT') and 'data' not in response.json()
    assert time.perf_counter()-started<contract['delivery']['total_timeout_seconds']+3
    state['drip']=False
    state['hold']=True; state['release'].clear(); before=state['calls']
    pending=[asyncio.create_task(http.post('/api/v2/query',headers=headers,json=request('internal-project'))) for _ in range(8)]
    try:
        for _ in range(100):
            if state['calls']==before+8:break
            await asyncio.sleep(.02)
        assert state['calls']==before+8
        response=await http.post('/api/v2/query',headers=headers,json=request('internal-project'))
        assert response.status_code==429 and response.json()['code']=='CONCURRENCY_LIMIT' and 'data' not in response.json()
    finally:
        state['hold']=False;state['release'].set()
        responses=await asyncio.gather(*pending)
    assert all(r.status_code==200 for r in responses)
    assert (await http.post('/api/v2/query',headers=headers,json=request('internal-project'))).status_code==200
    print('PASS AC-13: public API size limit -1/exact/+1, invalid JSON, continuous trickle deadline, 8 held slots/9th rejected, slots recover',flush=True)
