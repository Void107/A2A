"""Owned, immutable versions; discovery delegates each grant to current OPA."""
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.auth import denied, require_scope
from app.database import get_db
from app.models.schemas import Agent, ContractVersion, AccessGrant, ContractResource, PublicationCheck
from app.contracts import load_contract, ContractInvalid
from app.contracts.loader import contract_digest
from app.contracts.changes import compare
from app.contracts.publication import PublicationInput, validate_consumers, enforce, report_digest
from app.adapters.opa import PolicyUnavailable

router = APIRouter(prefix='/api/v2/contracts', tags=['Contracts'])


class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    provider_agent_id: str
    contract: dict


class Activation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    acknowledge_report_digest: Optional[str] = Field(default=None, pattern=r'^[a-f0-9]{64}$')


async def build_report(row, bundle, request, db, default=False):
    query = select(ContractVersion).where(ContractVersion.contract_id == row.contract_id,
        ContractVersion.state == 'active', ContractVersion.contract_version != row.contract_version)
    if default:
        query = query.where(ContractVersion.is_default.is_(True))
    previous = (await db.execute(query)).scalars().all()
    reports, previous_ids, previous_results = [], set(), []
    for old in previous:
        report = compare(old.document, row.document)
        report['old_version'] = old.contract_version
        reports.append(report)
        registration = await db.get(PublicationCheck, (old.contract_id, old.contract_version))
        if registration:
            previous_ids.update(c['consumer_id'] for c in registration.bundle['consumers'])
            checked = await validate_consumers(row.document, PublicationInput.model_validate(registration.bundle), getattr(request.app.state, 'presidio', None))
            previous_results.extend(dict(c, old_version=old.contract_version) for c in checked)
    results = await validate_consumers(row.document, bundle, getattr(request.app.state, 'presidio', None))
    report = {'contract_digest': row.digest, 'comparisons': reports, 'consumers': results,
              'all_consumers_verified': False, 'scope': 'registered_synthetic_examples_only',
              'migration_id': bundle.migration_id, 'default_switch': default, 'previous_consumers': previous_results,
              'bundle_digest': report_digest(bundle.model_dump())}
    return report, previous_ids


async def publication_gate(row, request, db, body, default=False):
    check = await db.get(PublicationCheck, (row.contract_id, row.contract_version), with_for_update=True)
    bundle = PublicationInput.model_validate(check.bundle) if check else PublicationInput(consumers=[])
    report, previous_ids = await build_report(row, bundle, request, db, default)
    digest = report_digest(report)
    try:
        if all(r['classification'] == 'compatible' for r in report['comparisons']) and any(c['result'] != 'PASS' for c in report['previous_consumers']):
            raise ValueError('REGISTERED_CONSUMER_REGRESSION')
        enforce(report['comparisons'], report['consumers'], row.contract_version, bundle,
                body.acknowledge_report_digest if body else None, digest, default, previous_ids)
    except ValueError as error:
        raise denied(str(error), 409) from None
    if check:
        check.report = report
        check.acknowledged_digest = body.acknowledge_report_digest if body else None


@router.post('/{contract_id}/{version}/check')
async def check_publication(contract_id: str, version: str, body: PublicationInput, request: Request,
                            default: bool = False, actor=Depends(require_scope('contracts:write')),
                            db: AsyncSession = Depends(get_db)):
    resource = await db.get(ContractResource, contract_id, with_for_update=True)
    row = await db.get(ContractVersion, (contract_id, version), with_for_update=True)
    if not resource or resource.owner_agent_id != actor['sub'] or not row:
        raise denied()
    existing = await db.get(PublicationCheck, (contract_id, version), with_for_update=True)
    # Activated examples are immutable; rechecks may inspect but cannot replace evidence.
    if row.state in {'active', 'retired'} and (not existing or existing.bundle != body.model_dump()):
        raise denied('PUBLICATION_EVIDENCE_IMMUTABLE', 409)
    report, _ = await build_report(row, body, request, db, default)
    if existing:
        existing.report = report
        existing.bundle = body.model_dump()
    else:
        db.add(PublicationCheck(contract_id=contract_id, contract_version=version,
                               bundle=body.model_dump(), report=report))
    await db.commit()
    return dict(report, report_digest=report_digest(report))


@router.post('', status_code=201)
async def save(body: Draft, actor=Depends(require_scope('contracts:write')), db: AsyncSession = Depends(get_db)):
    try: document = load_contract(body.contract)
    except ContractInvalid as error:
        raise HTTPException(status_code=422, detail={'code': 'CONTRACT_INVALID', 'rule': error.rule}) from None
    provider = (await db.execute(select(Agent).where(Agent.agent_id == body.provider_agent_id).with_for_update())).scalar_one_or_none()
    if not provider or not provider.is_active or (provider.agent_id != actor['sub'] and 'admin' not in actor['scopes']):
        raise denied()
    await db.execute(insert(ContractResource).values(contract_id=document['contract_id'],
        owner_agent_id=actor['sub'], provider_agent_id=provider.agent_id).on_conflict_do_nothing())
    resource = await db.get(ContractResource, document['contract_id'], with_for_update=True)
    if resource.owner_agent_id != actor['sub'] or resource.provider_agent_id != provider.agent_id:
        raise denied()
    existing = (await db.execute(select(ContractVersion).where(ContractVersion.contract_id == document['contract_id']))).scalars().all()
    if any(row.owner_agent_id != actor['sub'] for row in existing):
        raise denied()
    if any(row.contract_version == document['contract_version'] for row in existing):
        raise denied('CONTRACT_VERSION_IMMUTABLE', 409)
    db.add(ContractVersion(contract_id=document['contract_id'], contract_version=document['contract_version'],
                          owner_agent_id=actor['sub'], provider_agent_id=provider.agent_id,
                          document=document, digest=contract_digest(document), state='draft'))
    await db.commit()
    return {'state': 'draft', 'digest': contract_digest(document)}


@router.post('/{contract_id}/{version}/validate')
async def validate(contract_id: str, version: str, actor=Depends(require_scope('contracts:write')), db: AsyncSession = Depends(get_db)):
    row = await db.get(ContractVersion, (contract_id, version), with_for_update=True)
    if not row or row.owner_agent_id != actor['sub']:
        raise denied()
    if row.state != 'draft':
        raise denied('CONTRACT_VERSION_UNAVAILABLE', 409)
    try: load_contract(row.document)
    except ContractInvalid as error:
        raise HTTPException(status_code=422, detail={'code': 'CONTRACT_INVALID', 'rule': error.rule}) from None
    row.state = 'validated'
    await db.commit()
    return {'state': 'validated'}


@router.post('/{contract_id}/{version}/activate')
async def activate(contract_id: str, version: str, request: Request, body: Optional[Activation] = None,
                   actor=Depends(require_scope('contracts:write')), db: AsyncSession = Depends(get_db)):
    # Serialize owner publication operations before locking versions.
    await db.get(ContractResource, contract_id, with_for_update=True)
    row = await db.get(ContractVersion, (contract_id, version), with_for_update=True)
    if not row or row.owner_agent_id != actor['sub']:
        raise denied()
    if row.state != 'validated':
        raise denied('CONTRACT_VERSION_UNAVAILABLE', 409)
    try: contract = load_contract(row.document)
    except ContractInvalid as error:
        raise HTTPException(status_code=422, detail={'code': 'CONTRACT_INVALID', 'rule': error.rule}) from None
    await publication_gate(row, request, db, body)
    if any(v['processors'] for v in contract['views']):
        if getattr(request.app.state, 'presidio', None) is None:
            raise denied('PROCESSING_UNAVAILABLE', 503)
        try: await request.app.state.presidio.redact('profile health check')
        except Exception: raise denied('PROCESSING_UNAVAILABLE', 503) from None
    row.state = 'active'
    await db.commit()
    return {'state': 'active', 'is_default': False}


@router.post('/{contract_id}/{version}/retire')
async def retire(contract_id: str, version: str, actor=Depends(require_scope('contracts:write')), db: AsyncSession = Depends(get_db)):
    row = await db.get(ContractVersion, (contract_id, version), with_for_update=True)
    if not row or row.owner_agent_id != actor['sub']:
        raise denied()
    row.state, row.is_default = 'retired', False
    await db.commit()
    return {'state': 'retired'}


@router.get('/discover')
async def discover(request: Request, actor=Depends(require_scope('discover')), db: AsyncSession = Depends(get_db)):
    grants = (await db.execute(select(AccessGrant).where(AccessGrant.agent_id == actor['sub'], AccessGrant.active.is_(True)))).scalars().all()
    result = []
    for grant in grants:
        rows = (await db.execute(select(ContractVersion).where(ContractVersion.contract_id == grant.contract_id,
            ContractVersion.state == 'active'))).scalars().all()
        for row in rows:
            for meeting_id in grant.allowed_meeting_ids:
                try:
                    decision = await request.app.state.opa.decide(row.document, grant.view_id, actor,
                        {k: getattr(grant, k) for k in ('agent_id', 'contract_id', 'view_id', 'allowed_meeting_ids', 'active')}, meeting_id)
                except (PolicyUnavailable, AttributeError):
                    raise denied('PROCESSING_UNAVAILABLE', 503) from None
                if decision['allow']:
                    result.append({'contract_id': row.contract_id, 'contract_version': row.contract_version,
                                   'view_id': grant.view_id, 'provider_agent_id': row.provider_agent_id})
                    break
    return result


@router.post('/{contract_id}/{version}/default')
async def set_default(contract_id: str, version: str, request: Request, body: Optional[Activation] = None, actor=Depends(require_scope('contracts:write')), db: AsyncSession = Depends(get_db)):
    resource = await db.get(ContractResource, contract_id, with_for_update=True)
    if not resource or resource.owner_agent_id != actor['sub']:
        raise denied()
    row = await db.get(ContractVersion, (contract_id, version), with_for_update=True)
    if not row or row.state != 'active':
        raise denied('CONTRACT_VERSION_UNAVAILABLE', 409)
    await publication_gate(row, request, db, body, default=True)
    await db.execute(update(ContractVersion).where(ContractVersion.contract_id == contract_id).values(is_default=False))
    row.is_default = True
    await db.commit()
    return {'contract_version': version, 'is_default': True}
