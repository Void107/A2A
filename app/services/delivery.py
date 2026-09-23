"""Single complete JSON delivery path shared by REST and the A2A adapter."""
import asyncio
import copy
import uuid
import time
import json
from pathlib import Path
from app.config import settings

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from app.models.schemas import ContractVersion, AccessGrant
from app.contracts.loader import contract_digest
from app.services.receipts import ReceiptMetadata, persist_receipt
from app.services.view_processing import process_view
from app.services.diagnostics import FailureDiagnostics


class DeliveryFailure(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class MeetingQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    meeting_id: str = Field(pattern=r'^meeting-[0-9]{3}$')


class DeliveryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    target_agent: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    contract_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    contract_version: str = Field(pattern=r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')
    view_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    query: MeetingQuery


async def deliver(body, identity, db, runtime):
    request_id = uuid.uuid4().hex
    diagnostics = FailureDiagnostics(contract_id=body.contract_id,
        contract_version=body.contract_version, view_id=body.view_id)
    try:
        return await _deliver(body, identity, db, runtime, request_id, diagnostics)
    except Exception as error:
        failure = DeliveryFailure(getattr(error, 'code', 'PROCESSING_UNAVAILABLE'))
        failure.request_id = request_id
        failure.diagnostics = diagnostics
        raise failure from None


async def _deliver(body, identity, db, runtime, request_id, diagnostics):
    binding_started = time.perf_counter()
    if 'query' not in identity['scopes']:
        raise DeliveryFailure('ACCESS_DENIED')
    row = await db.get(ContractVersion, (body.contract_id, body.contract_version))
    if row is None or row.state != 'active':
        raise DeliveryFailure('CONTRACT_VERSION_UNAVAILABLE')
    if row.provider_agent_id != body.target_agent:
        raise DeliveryFailure('ACCESS_DENIED')
    contract = copy.deepcopy(row.document)
    digest = contract_digest(contract)
    if row.digest != digest:
        raise DeliveryFailure('CONTRACT_VERSION_UNAVAILABLE')
    grants = (await db.execute(select(AccessGrant).where(AccessGrant.agent_id == identity['sub'],
        AccessGrant.contract_id == body.contract_id, AccessGrant.view_id == body.view_id,
        AccessGrant.active.is_(True)))).scalars().all()
    if len(grants) != 1 or body.query.meeting_id not in grants[0].allowed_meeting_ids:
        raise DeliveryFailure('ACCESS_DENIED')
    diagnostics.contract_digest = digest
    grant = grants[0]
    snapshot = {k: copy.deepcopy(getattr(grant, k)) for k in ('agent_id', 'contract_id', 'view_id', 'allowed_meeting_ids', 'active')}
    grant_id, grant_revision = grant.grant_id, grant.revision
    # Release the initial read transaction; the final permission transaction
    # obtains fresh rows and serializes against revocation/retirement.
    await db.rollback()
    if getattr(runtime, 'upstream', None) is None:
        raise DeliveryFailure('PROCESSING_UNAVAILABLE')
    timings = {'view_id': body.view_id, 'request_id': request_id,
               'authentication_ms': identity.get('authentication_ms', 0),
               'binding_ms': (time.perf_counter()-binding_started)*1000}
    started = time.perf_counter()
    async def execute():
        phase = time.perf_counter()
        diagnostics.stage = 'authorization'
        decision = await runtime.opa.decide(contract, body.view_id, identity, snapshot, body.query.meeting_id)
        timings['authorization_ms'] = (time.perf_counter() - phase) * 1000
        diagnostics.policy_revision = decision['policy_revision']
        diagnostics.policy_decision = 'allowed' if decision['allow'] else 'denied'
        if not decision['allow']:
            raise DeliveryFailure('ACCESS_DENIED')
        phase = time.perf_counter()
        diagnostics.stage = 'upstream'
        raw = await runtime.upstream.fetch(body.target_agent, body.query.model_dump(),
                                          contract['delivery']['max_response_bytes'], contract['delivery']['total_timeout_seconds'])
        timings['upstream_ms'] = (time.perf_counter() - phase) * 1000
        processed = await process_view(contract, body.view_id, raw, runtime.presidio, body.query.meeting_id, diagnostics=diagnostics)
        timings['validation_ms'] = processed.validation_ms
        timings['detection_ms'] = processed.detection_ms
        diagnostics.stage = 'obligations'
        if processed.completed_processors != decision['required_processor_ids']:
            raise DeliveryFailure('OUTPUT_CONTRACT_VIOLATION')
        diagnostics.obligations = 'passed'
        meta = ReceiptMetadata(request_id=request_id, source_agent=identity['sub'], target_agent=body.target_agent,
            contract_id=body.contract_id, contract_version=body.contract_version, contract_digest=digest,
            view_id=body.view_id, meeting_id=body.query.meeting_id, policy_revision=decision['policy_revision'],
            profile_revision=processed.profile_revision, completed_processors=processed.completed_processors)
        phase = time.perf_counter()
        diagnostics.stage = 'receipt'
        await persist_receipt(meta, grant_id, identity['authorization_revision'], grant_revision)
        timings['pg_commit_ms'] = (time.perf_counter() - phase) * 1000
        timings['success'] = True
        return {'request_id': request_id, 'contract_id': body.contract_id, 'contract_version': body.contract_version,
                'contract_digest': digest, 'view_id': body.view_id, 'decision': 'delivered', 'data': processed.data}
    try:
        return await asyncio.wait_for(execute(), contract['delivery']['total_timeout_seconds'])
    except asyncio.TimeoutError:
        raise DeliveryFailure('DELIVERY_TIMEOUT') from None
    finally:
        if settings.METRICS_FILE:
            timings['core_total_ms'] = (time.perf_counter() - started) * 1000
            timings.setdefault('success', False)
            # Optional operator-local measurements contain no payload, identity or credentials.
            try:
                with Path(settings.METRICS_FILE).open('a') as stream:
                    stream.write(json.dumps(timings) + '\n')
            except OSError:
                pass  # Diagnostic measurement is not the required delivery receipt.

