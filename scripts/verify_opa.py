"""Actual OPA HTTP service plus malformed-response/timeout rejection."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from verify_real_baseline import ROOT, OPA_BINARY, PRESIDIO_PYTHON


async def main():
    import httpx
    from app.adapters.opa import OPAClient, PolicyUnavailable
    contract = json.loads((ROOT / 'docs/implementation/examples/contract.meeting.json').read_text())
    identity = {'sub': 'project-agent', 'organization_id': 'org-acme', 'roles': ['project-agent'], 'is_active': True}
    grant = {'agent_id': 'project-agent', 'contract_id': 'meeting-actions', 'view_id': 'internal-project',
             'allowed_meeting_ids': ['meeting-001'], 'active': True}
    proc = subprocess.Popen([OPA_BINARY, 'run', '--server', '--addr=127.0.0.1:58181',
                             '--disable-telemetry', '--log-level=error', 'policies/contract.rego'], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    opa = OPAClient('http://127.0.0.1:58181', timeout=.5)
    try:
        for _ in range(50):
            if proc.poll() is not None:
                raise RuntimeError('OPA startup failed')
            try:
                result = await opa.decide(contract, 'internal-project', identity, grant, 'meeting-001')
                break
            except PolicyUnavailable:
                await asyncio.sleep(.05)
        else: raise AssertionError('OPA not ready')
        assert result['allow'] is True
        assert not (await opa.decide(contract, 'internal-project', dict(identity, roles=['wrong']), grant, 'meeting-001'))['allow']
        assert not (await opa.decide(contract, 'internal-project', identity, dict(grant, active=False), 'meeting-001'))['allow']
        assert not (await opa.decide(contract, 'internal-project', identity, grant, 'meeting-002'))['allow']
        proc.terminate(); proc.wait(timeout=5)
        try: await opa.decide(contract, 'internal-project', identity, grant, 'meeting-001')
        except PolicyUnavailable: pass
        else: raise AssertionError('OPA offline allowed')
        await opa.close()
        for payload in [{}, {'result': None}, {'result': {}}, {'result': dict(result, allow='true')},
                        {'result': dict(result, contract_digest='other')}]:
            opa.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
            try: await opa.decide(contract, 'internal-project', identity, grant, 'meeting-001')
            except PolicyUnavailable: pass
            else: raise AssertionError('Malformed OPA response allowed')
            await opa.close()
        async def delayed(request):
            await asyncio.sleep(1)
            return httpx.Response(200, json={'result': result})
        opa.client = httpx.AsyncClient(transport=httpx.MockTransport(delayed))
        try: await opa.decide(contract, 'internal-project', identity, grant, 'meeting-001')
        except PolicyUnavailable: pass
        else: raise AssertionError('OPA deadline ignored')
        print('PASS: real OPA allow/deny/grant/resource/offline; empty/null/wrong-type/digest/deadline reject')
    finally:
        await opa.close()
        if proc.poll() is None:
            proc.terminate(); proc.wait(timeout=5)


if __name__ == '__main__':
    asyncio.run(main())
