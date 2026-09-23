"""T07 real Presidio HTTP processing, structural failures and consumer effects."""
import asyncio
import copy
import json
import subprocess
import sys
from pathlib import Path
from verify_real_baseline import ROOT, OPA_BINARY, PRESIDIO_PYTHON


async def main():
    import httpx
    from app.adapters.presidio import PresidioClient
    from app.services.view_processing import process_view, ProcessingFailure
    ex = ROOT / 'docs/implementation/examples'
    load = lambda name: json.loads((ex / name).read_text())
    contract, raw = load('contract.meeting.json'), load('raw.meeting.json')
    service_log = (ROOT / 'docs/verification/t07-service.log').open('w')
    proc = subprocess.Popen([PRESIDIO_PYTHON, '-m', 'uvicorn',
                             'examples.presidio.service:app', '--host', '127.0.0.1', '--port', '58182', '--no-access-log'],
                             cwd=ROOT, stdout=subprocess.DEVNULL, stderr=service_log)
    presidio = PresidioClient('http://127.0.0.1:58182')
    try:
        async with httpx.AsyncClient() as health:
            for _ in range(600):
                if proc.poll() is not None:
                    raise RuntimeError('Presidio startup failed; see t07-service.log')
                try:
                    if (await health.get('http://127.0.0.1:58182/ready')).status_code == 200: break
                except httpx.HTTPError: pass
                await asyncio.sleep(.1)
            else: raise RuntimeError('Presidio not ready')
        before = copy.deepcopy(raw)
        for view, expected in [('external-collaboration', 'expected.external.json'),
                               ('internal-project', 'expected.internal.json')]:
            output = await process_view(contract, view, raw, presidio, 'meeting-001')
            assert output.data == load(expected)
        assert raw == before
        samples = [('Write a@example.com.', 'Write [EMAIL].'),
                   ('a@example.com and b@example.com', '[EMAIL] and [EMAIL]'),
                   ('No email here.', 'No email here.'),
                   ('Alice Example 电话 12345', 'Alice Example 电话 12345')]
        for source, expected in samples: assert await presidio.redact(source) == expected
        title = dict(raw, title='Contact title@example.com')
        assert (await process_view(contract, 'external-collaboration', title, presidio, 'meeting-001')).data['title'] == 'Contact [EMAIL]'
        for mutation in [lambda d: d.update(secret='synthetic'),
                         lambda d: d['action_items'][0].update(extra='synthetic'),
                         lambda d: d['action_items'][0].update(due_date='2026-02-30'),
                         lambda d: d['action_items'][0].pop('owner_email')]:
            data = copy.deepcopy(raw); mutation(data)
            try: await process_view(contract, 'external-collaboration', data, presidio, 'meeting-001')
            except ProcessingFailure as e: assert e.code == 'UPSTREAM_SCHEMA_MISMATCH'
            else: raise AssertionError('source drift accepted')
        try: await process_view(contract, 'external-collaboration', raw, presidio, 'meeting-002')
        except ProcessingFailure as e: assert e.code == 'UPSTREAM_RESOURCE_MISMATCH'
        else: raise AssertionError('wrong resource accepted')
        internal = (await process_view(contract, 'internal-project', raw, presidio, 'meeting-001')).data
        external = (await process_view(contract, 'external-collaboration', raw, presidio, 'meeting-001')).data
        tasks = [{'assignee': i['owner_email'], 'due_date': i['due_date']} for i in internal['action_items']]
        pending = [{'assignee': None, 'task': i['task'], 'due_date': i['due_date']} for i in external['action_items']]
        assert [t['assignee'] for t in tasks] == ['alice@example.com', 'bob@example.com']
        assert len(pending) == 2 and all(t['assignee'] is None for t in pending)
        (ROOT / 'docs/verification/t07-consumer-results.json').write_text(json.dumps({'internal': tasks, 'external': pending}, indent=2))
        proc.terminate(); proc.wait(timeout=5)
        try: await process_view(contract, 'external-collaboration', raw, presidio, 'meeting-001')
        except ProcessingFailure as e: assert e.code == 'PROCESSING_UNAVAILABLE'
        else: raise AssertionError('required processing skipped')
        print('PASS: actual Presidio email profile; golden dual views/input isolation/title/source drift/resource mismatch; local consumers; service failure closed')
        print('Quality scope: golden fixture plus 4 fixed texts; 2 negative texts unchanged. Exploratory span precision/recall NOT_RUN.')
    finally:
        await presidio.close()
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        service_log.close()


if __name__ == '__main__': asyncio.run(main())
