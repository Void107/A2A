"""T04 real PG transactions, retry, concurrency and revocation ordering."""
import asyncio
import subprocess
import sys
import uuid
from datetime import datetime

from verify_real_baseline import ROOT


async def main():
    from check_test_services import main as probe
    await probe()
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT, check=True)
    from app.database import AsyncSessionLocal, engine
    from app.models.schemas import Agent, AccessGrant, DeliveryReceipt, OutboxEvent, DeliveryAudit, ContractVersion
    from app.services.receipts import ReceiptMetadata, persist_receipt, consume_one, ReceiptFailure
    from sqlalchemy import select, func, text, update
    suffix = uuid.uuid4().hex[:12]
    actor = 'receipt-' + suffix
    cid = 'receipt-contract-' + suffix
    import json
    from app.contracts.loader import contract_digest
    document = json.loads((ROOT / 'docs/implementation/examples/contract.meeting.json').read_text())
    document['contract_id'] = cid
    digest = contract_digest(document)
    gid = 'grant-' + suffix
    async with AsyncSessionLocal() as db, db.begin():
        db.add(Agent(agent_id=actor, display_name='Synthetic', callback_url='', data_contract={},
                     domain='org-test', api_key_hash='unused', hub_shared_secret_hash='', scopes=['query'], roles=[]))
        db.add(ContractVersion(contract_id=cid, contract_version='1.0.0', owner_agent_id=actor,
            provider_agent_id='synthetic-provider', document=document, digest=digest, state='active'))
        db.add(AccessGrant(grant_id=gid, agent_id=actor, contract_id=cid, view_id='internal-project',
                           allowed_meeting_ids=['meeting-001'], active=True, revision=1))
    def metadata():
        return ReceiptMetadata(request_id=uuid.uuid4().hex, source_agent=actor, target_agent='synthetic-provider',
            contract_id=cid, contract_version='1.0.0', contract_digest=digest,
            view_id='internal-project', meeting_id='meeting-001', policy_revision='policy-1',
            profile_revision='none', completed_processors=[])
    first = metadata()
    await persist_receipt(first, gid, 1, 1)
    # Repeated ID violates real PostgreSQL uniqueness and must not leave a second outbox row.
    try: await persist_receipt(first, gid, 1, 1)
    except ReceiptFailure as e: assert e.code == 'AUDIT_PERSISTENCE_UNAVAILABLE'
    else: raise AssertionError('duplicate transaction accepted')
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.receipt_id == first.request_id)) == 1
        event = (await db.execute(select(OutboxEvent).where(OutboxEvent.receipt_id == first.request_id))).scalar_one()
        event_id = event.event_id
    # Inject a real DB write failure only for this test receipt, then recover.
    function = 'fail_receipt_' + suffix
    async with engine.begin() as conn:
        await conn.execute(text("CREATE FUNCTION " + function + "() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.receipt_id = '" + first.request_id + "' THEN RAISE EXCEPTION 'synthetic audit failure'; END IF; RETURN NEW; END $$"))
        await conn.execute(text('CREATE TRIGGER ' + function + ' BEFORE INSERT ON delivery_audit FOR EACH ROW EXECUTE FUNCTION ' + function + '()'))
    try:
        while True:
            try:
                if not await consume_one(): raise AssertionError('event missing')
            except ReceiptFailure: break
        async with AsyncSessionLocal() as db:
            event = await db.get(OutboxEvent, event_id)
            assert not event.processed and event.attempts == 1
            assert await db.get(DeliveryAudit, event_id) is None
    finally:
        async with engine.begin() as conn:
            await conn.execute(text('DROP TRIGGER ' + function + ' ON delivery_audit'))
            await conn.execute(text('DROP FUNCTION ' + function + '()'))
    async with AsyncSessionLocal() as db, db.begin():
        await db.execute(update(OutboxEvent).where(OutboxEvent.event_id == event_id).values(next_attempt=datetime.utcnow()))
    for _ in range(5):
        await asyncio.gather(consume_one(), consume_one())
    async with AsyncSessionLocal() as db:
        assert (await db.get(OutboxEvent, event_id)).processed
        assert await db.get(DeliveryAudit, event_id) is not None
        assert await db.scalar(select(func.count()).select_from(DeliveryAudit).where(DeliveryAudit.receipt_id == first.request_id)) == 1
    # Hold the same subject lock the delivery uses, commit revocation, then check
    # that the queued permission transaction rejects its old revision.
    async with AsyncSessionLocal() as db:
        async with db.begin():
            subject = (await db.execute(select(Agent).where(Agent.agent_id == actor).with_for_update())).scalar_one()
            subject.authorization_revision += 1
            grant = await db.get(AccessGrant, gid, with_for_update=True)
            grant.active, grant.revision = False, 2
            waiting = asyncio.create_task(persist_receipt(metadata(), gid, 1, 1))
        try: await waiting
        except ReceiptFailure as e: assert e.code == 'ACCESS_DENIED'
        else: raise AssertionError('revocation bypassed')
    async with AsyncSessionLocal() as db:
        row = await db.get(DeliveryReceipt, first.request_id)
        assert row.status == 'ready_to_send'
        assert await db.scalar(select(func.count()).select_from(DeliveryReceipt).where(DeliveryReceipt.source_agent == actor)) == 1
    async with AsyncSessionLocal() as db, db.begin():
        await db.execute(update(OutboxEvent).where(OutboxEvent.event_id == event_id).values(processed=False))
    # A separate worker process must recover pending/duplicate work without Redis.
    subprocess.run(['docker', 'compose', '-f', 'compose.test.yaml', 'stop', 'redis'], cwd=ROOT, check=True)
    try:
        subprocess.run([sys.executable, __file__, '--consume'], cwd=ROOT, check=True)
        async with AsyncSessionLocal() as db:
            assert (await db.get(OutboxEvent, event_id)).processed
            assert await db.scalar(select(func.count()).select_from(DeliveryAudit).where(DeliveryAudit.receipt_id == first.request_id)) == 1
    finally:
        subprocess.run(['docker', 'compose', '-f', 'compose.test.yaml', 'up', '-d', '--wait', 'redis'], cwd=ROOT, check=True)
    await engine.dispose()
    print('PASS: process restart and Redis outage; PG receipt/outbox atomicity, DB failure retention, retry, two-consumer idempotency, current grant revocation, ready_to_send semantics')


if __name__ == '__main__':
    if '--consume' in sys.argv:
        async def worker():
            from app.services.receipts import consume_one
            from app.database import engine
            while await consume_one():
                pass
            await engine.dispose()
        asyncio.run(worker())
    else:
        asyncio.run(main())
