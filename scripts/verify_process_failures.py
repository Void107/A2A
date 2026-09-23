"""Actual PostgreSQL rollback/recovery when production receipt workers exit."""
import asyncio
import json
import os
import subprocess
import sys
import uuid
from verify_real_baseline import ROOT


async def child(mode, metadata, grant):
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from app.services.receipts import persist_receipt,ReceiptMetadata,consume_one
    hook='after_commit' if mode=='consume-after' else 'after_flush'
    event.listen(Session,hook,lambda *args:os._exit(23))
    if mode=='persist':await persist_receipt(ReceiptMetadata.model_validate(metadata),grant,1,1)
    else:await consume_one()
    raise AssertionError('crash hook not reached')


async def main():
    from check_test_services import main as probe
    await probe()
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=ROOT,check=True)
    from app.database import AsyncSessionLocal,engine
    from app.models.schemas import Agent,AccessGrant,ContractVersion,DeliveryReceipt,OutboxEvent,DeliveryAudit
    from app.services.receipts import ReceiptMetadata,persist_receipt,consume_one
    from app.contracts.loader import contract_digest
    from sqlalchemy import select,func
    # Other verification jobs are sequential; drain prior work before inserting this job's event.
    while await consume_one():pass
    suffix=uuid.uuid4().hex[:10];actor='crash-'+suffix;gid='crash-grant-'+suffix;cid='crash-contract-'+suffix
    document=json.loads((ROOT/'docs/implementation/examples/contract.meeting.json').read_text());document['contract_id']=cid
    digest=contract_digest(document)
    async with AsyncSessionLocal() as db,db.begin():
        db.add(Agent(agent_id=actor,display_name='Synthetic crash test',callback_url='',domain='org-test',roles=[],scopes=['query'],data_contract={},api_key_hash='unused',hub_shared_secret_hash=''))
        db.add(AccessGrant(grant_id=gid,agent_id=actor,contract_id=cid,view_id='internal-project',allowed_meeting_ids=['meeting-001'],active=True,revision=1))
        db.add(ContractVersion(contract_id=cid,contract_version='1.0.0',owner_agent_id=actor,provider_agent_id='synthetic-provider',document=document,digest=digest,state='active'))
    def meta():return ReceiptMetadata(request_id=uuid.uuid4().hex,source_agent=actor,target_agent='synthetic-provider',contract_id=cid,
        contract_version='1.0.0',contract_digest=digest,view_id='internal-project',meeting_id='meeting-001',policy_revision='contract-policy-1',profile_revision='none',completed_processors=[])
    aborted=meta()
    code=subprocess.run([sys.executable,__file__,'persist',json.dumps(aborted.model_dump()),gid],cwd=ROOT).returncode
    assert code==23
    async with AsyncSessionLocal() as db:
        assert await db.get(DeliveryReceipt,aborted.request_id) is None
        assert await db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.receipt_id==aborted.request_id))==0
    delivered=meta();await persist_receipt(delivered,gid,1,1)
    async with AsyncSessionLocal() as db:
        event_id=await db.scalar(select(OutboxEvent.event_id).where(OutboxEvent.receipt_id==delivered.request_id))
    assert subprocess.run([sys.executable,__file__,'consume-before','{}',gid],cwd=ROOT).returncode==23
    async with AsyncSessionLocal() as db:
        assert not (await db.get(OutboxEvent,event_id)).processed
        assert await db.get(DeliveryAudit,event_id) is None
    assert subprocess.run([sys.executable,__file__,'consume-after','{}',gid],cwd=ROOT).returncode==23
    async with AsyncSessionLocal() as db:
        assert (await db.get(OutboxEvent,event_id)).processed
        assert await db.get(DeliveryAudit,event_id) is not None
    assert not await consume_one()
    print('PASS: receipt process exits after real flush before commit: no receipt/outbox; consumer exits before commit: retained event/no audit; exits after commit: exactly one durable audit, restart has no lost work')
    await engine.dispose()


if __name__=='__main__':
    asyncio.run(child(sys.argv[1],json.loads(sys.argv[2]),sys.argv[3]) if len(sys.argv)>1 else main())
