"""Record every synthetic attempt and match safe per-request server timings."""
import asyncio
import json
import time
from pathlib import Path
import httpx


def percentile(values,p):
    values=sorted(values)
    return values[min(len(values)-1,int((len(values)-1)*p))] if values else None


async def main():
    keys=json.loads(Path('/state/caller-keys.json').read_text());samples=[];summaries=[]
    async with httpx.AsyncClient(base_url='http://hub:8000',timeout=35,trust_env=False) as http:
        for actor,view in [('project-agent','internal-project'),('partner-agent','external-collaboration')]:
            login=await http.post('/api/v1/auth/token',json={'agent_id':actor,'api_key':keys[actor]});login.raise_for_status()
            headers={'Authorization':'Bearer '+login.json()['access_token']}
            request={'target_agent':'meeting-provider','contract_id':'meeting-actions','contract_version':'1.0.0','view_id':view,'query':{'meeting_id':'meeting-001'}}
            for concurrency in [1,5,10]:
                semaphore=asyncio.Semaphore(concurrency)
                async def attempt(index,warmup=False):
                    async with semaphore:
                        started=time.perf_counter();request_id=None;error=None
                        try:
                            response=await http.post('/api/v2/query',headers=headers,json=request)
                            status=response.status_code;body=response.json();request_id=body.get('request_id');error=body.get('code')
                        except httpx.TimeoutException: status=0;error='CLIENT_TIMEOUT'
                        except httpx.HTTPError: status=0;error='CLIENT_TRANSPORT_ERROR'
                        return dict(view=view,concurrency=concurrency,index=index,warmup=warmup,status=status,request_id=request_id,error=error,milliseconds=(time.perf_counter()-started)*1000)
                samples.extend(await asyncio.gather(*(attempt(i,True) for i in range(5))))
                started=time.perf_counter();batch=await asyncio.gather(*(attempt(i) for i in range(100)));elapsed=time.perf_counter()-started
                samples.extend(batch)
                metrics={row['request_id']:row for row in (json.loads(line) for line in Path('/measurements/core.jsonl').read_text().splitlines())}
                phases={}
                for phase in ['authentication_ms','binding_ms','authorization_ms','upstream_ms','validation_ms','detection_ms','pg_commit_ms']:
                    values=[metrics[s['request_id']][phase] for s in batch if s['request_id'] in metrics and phase in metrics[s['request_id']]]
                    phases[phase]={'samples':len(values),'p50':percentile(values,.5),'p95':percentile(values,.95)}
                errors=sum(s['status']!=200 for s in batch);timeouts=sum(s['status']==504 or s['error']=='CLIENT_TIMEOUT' for s in batch)
                summary=dict(view=view,concurrency=concurrency,attempts=100,errors=errors,error_rate=errors/100,timeouts=timeouts,timeout_rate=timeouts/100,
                    p50_ms=percentile([s['milliseconds'] for s in batch],.5),p95_ms=percentile([s['milliseconds'] for s in batch],.95),
                    throughput_per_second=100/elapsed,phases=phases)
                summaries.append(summary);print(json.dumps(summary),flush=True)
    from app.database import AsyncSessionLocal,engine
    from app.models.schemas import OutboxEvent
    from sqlalchemy import select,func
    backlog=[]
    for _ in range(31):
        async with AsyncSessionLocal() as db:
            pending=await db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.processed.is_(False)))
        backlog.append(dict(time=time.time(),pending=pending))
        if pending==0:break
        await asyncio.sleep(1)
    await engine.dispose()
    report=dict(samples=samples,summaries=summaries,outbox=backlog,warmup_per_group=5,
        source_bytes=len(json.dumps(json.loads(Path('docs/implementation/examples/raw.meeting.json').read_text()),separators=(',',':'),ensure_ascii=False).encode()),
        fixture_file_bytes=len(Path('docs/implementation/examples/raw.meeting.json').read_bytes()),
        notes='600 measured + 30 warmup; all failures included; phases report their actual sample counts; authentication includes current JWT/DB identity; authorization phase is OPA; no production SLO')
    Path('/measurements/requests.json').write_text(json.dumps(report,indent=2))
    assert len(samples)==630 and all(s['milliseconds']<35000 for s in samples)
    print('PASS AC-23: complete attempts, per-concurrency end-to-end/phase metrics and recovery backlog recorded',flush=True)

if __name__=='__main__':asyncio.run(main())
