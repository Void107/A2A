"""Final authorization linearization and durable work, independent of Redis."""
import asyncio
import uuid
from datetime import datetime, timedelta
from typing import List

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.database import AsyncSessionLocal
from app.models.schemas import Agent, AccessGrant, DeliveryReceipt, OutboxEvent, DeliveryAudit, ContractVersion


class ReceiptFailure(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ReceiptMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    source_agent: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    target_agent: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    contract_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    contract_version: str = Field(pattern=r'^[0-9]+\.[0-9]+\.[0-9]+$')
    contract_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    view_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    meeting_id: str = Field(pattern=r'^meeting-[0-9]{3}$')
    policy_revision: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    profile_revision: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    completed_processors: List[str] = Field(max_length=256)


async def persist_receipt(meta: ReceiptMetadata, grant_id, identity_revision, grant_revision):
    """Caller invokes only after OPA, input, processors and output validation.

    Lock ordering matches administrator mutations: subject, then grant. No
    successful return until PostgreSQL commit. Response bytes are sent afterward.
    """
    try:
        async with AsyncSessionLocal() as db, db.begin():
            subject = (await db.execute(select(Agent).where(Agent.agent_id == meta.source_agent).with_for_update())).scalar_one_or_none()
            grant = await db.get(AccessGrant, grant_id, with_for_update=True)
            if (not subject or not subject.is_active or 'query' not in (subject.scopes or [])
                    or subject.authorization_revision != identity_revision or not grant or not grant.active
                    or grant.revision != grant_revision or grant.agent_id != subject.agent_id
                    or grant.contract_id != meta.contract_id or grant.view_id != meta.view_id
                    or meta.meeting_id not in grant.allowed_meeting_ids):
                raise ReceiptFailure('ACCESS_DENIED')
            version = await db.get(ContractVersion, (meta.contract_id, meta.contract_version), with_for_update=True)
            if (not version or version.state != 'active' or version.digest != meta.contract_digest
                    or version.provider_agent_id != meta.target_agent):
                raise ReceiptFailure('CONTRACT_VERSION_UNAVAILABLE')
            db.add(DeliveryReceipt(**meta.model_dump(), status='ready_to_send'))
            db.add(OutboxEvent(event_id=uuid.uuid4().hex, receipt_id=meta.request_id))
        return meta.request_id
    except ReceiptFailure:
        raise
    except Exception:
        raise ReceiptFailure('AUDIT_PERSISTENCE_UNAVAILABLE') from None


async def consume_one():
    event_id = None
    try:
        async with AsyncSessionLocal() as db, db.begin():
            event = (await db.execute(select(OutboxEvent).where(
                OutboxEvent.processed.is_(False), OutboxEvent.attempts < 20,
                OutboxEvent.next_attempt <= datetime.utcnow()).order_by(OutboxEvent.next_attempt)
                .with_for_update(skip_locked=True).limit(1))).scalar_one_or_none()
            if event is None:
                return False
            event_id = event.event_id
            await db.execute(insert(DeliveryAudit).values(event_id=event_id, receipt_id=event.receipt_id,
                                                         indexed_at=datetime.utcnow()).on_conflict_do_nothing())
            event.processed = True
        return True
    except asyncio.CancelledError:
        raise
    except Exception:
        if event_id is not None:
            # A failed attempt retains its source row; after 20 attempts an
            # operator can inspect/requeue it. Never acknowledge failed work.
            async with AsyncSessionLocal() as db, db.begin():
                await db.execute(update(OutboxEvent).where(OutboxEvent.event_id == event_id,
                    OutboxEvent.processed.is_(False)).values(attempts=OutboxEvent.attempts + 1,
                        next_attempt=datetime.utcnow() + timedelta(seconds=5)))
        raise ReceiptFailure('OUTBOX_PROCESSING_UNAVAILABLE') from None


async def consumer_loop():
    while True:
        try:
            worked = await consume_one()
            if not worked:
                await asyncio.sleep(1)
        except ReceiptFailure:
            await asyncio.sleep(1)


async def record_failure(request_id, actor, code, diagnostics=None):
    from app.models.schemas import FailureRecord
    from app.services.diagnostics import FailureDiagnostics
    try:
        safe = FailureDiagnostics.model_validate(diagnostics.model_dump()).safe_dump() if diagnostics is not None else None
        async with AsyncSessionLocal() as db, db.begin():
            db.add(FailureRecord(request_id=request_id, source_agent=actor, code=code, diagnostics=safe))
        return True
    except Exception:
        return False  # No claim that a failure was persisted while PG is unavailable.
