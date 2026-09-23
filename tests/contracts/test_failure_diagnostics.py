"""Metadata proves only completed stages and never serializes upstream content."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select, func
from tests.conftest import TestSessionLocal
from tests.contracts.test_delivery_faults import seed
from app.main import app
from app.models.schemas import FailureRecord, DeliveryReceipt
from app.services.receipts import ReceiptFailure, record_failure
from app.services.diagnostics import FailureDiagnostics


@pytest.mark.parametrize('fault,stage', [
    ('binding', 'binding'), ('deny', 'authorization'), ('opa', 'authorization'),
    ('upstream', 'upstream'), ('source', 'source_validation'),
    ('processor', 'processing'), ('output', 'output_validation'), ('commit', 'receipt')])
async def test_failure_stages(client, registered_agent, second_agent, monkeypatch, fault, stage):
    contract, raw, body = await seed(registered_agent, 'external-collaboration')
    decision = {'allow': fault != 'deny', 'required_processor_ids': ['external-email-redaction'],
                'policy_revision': 'contract-policy-1'}
    opa = AsyncMock(return_value=decision)
    upstream = AsyncMock(return_value=raw)
    redact = AsyncMock(side_effect=lambda value: value.replace('alice@example.com', '[EMAIL]').replace('bob@example.com', '[EMAIL]'))
    monkeypatch.setattr(app.state, 'opa', SimpleNamespace(decide=opa), raising=False)
    monkeypatch.setattr(app.state, 'upstream', SimpleNamespace(fetch=upstream), raising=False)
    monkeypatch.setattr(app.state, 'presidio', SimpleNamespace(redact=redact, profile_revision='test-email-v1'), raising=False)
    secret = 'synthetic-private@example.com Bearer secret-test-only'
    if fault == 'binding': body['query']['meeting_id'] = 'meeting-999'
    if fault == 'opa': opa.side_effect = RuntimeError(secret)
    if fault == 'upstream': upstream.side_effect = RuntimeError(secret)
    if fault == 'source': raw['secret'] = secret
    if fault == 'processor': redact.side_effect = RuntimeError(secret)
    if fault == 'output': redact.side_effect = lambda value: 123
    if fault == 'commit':
        monkeypatch.setattr('app.services.delivery.persist_receipt', AsyncMock(side_effect=ReceiptFailure('AUDIT_PERSISTENCE_UNAVAILABLE')))
    response = await client.post('/api/v2/query', headers=registered_agent['auth_header'], json=body)
    assert response.status_code >= 400 and 'data' not in response.json()
    assert response.json()['diagnostic_recorded'] is True
    request_id = response.json()['request_id']
    lookup = await client.get('/api/v2/receipts/' + request_id, headers=registered_agent['auth_header'])
    assert lookup.status_code == 200
    diag = lookup.json()['diagnostics']
    assert diag['stage'] == stage
    assert diag['contract_id'] == body['contract_id'] and diag['view_id'] == body['view_id']
    assert (diag['contract_digest'] is None) == (fault == 'binding')
    assert (diag['policy_revision'] is None) == (fault in ('binding', 'opa'))
    assert diag['policy_decision'] == ('unknown' if fault in ('binding', 'opa') else 'denied' if fault == 'deny' else 'allowed')
    assert diag['source_validation'] == ('passed' if fault in ('processor', 'output', 'commit') else 'unknown')
    assert diag['output_validation'] == ('passed' if fault == 'commit' else 'unknown')
    assert diag['obligations'] == ('passed' if fault == 'commit' else 'unknown')
    assert diag['completed_processors'] == (['external-email-redaction'] if fault in ('output', 'commit') else [])
    assert diag['profile_revision'] == ('test-email-v1' if fault in ('output', 'commit') else None)
    assert (await client.get('/api/v2/receipts/' + request_id, headers=second_agent['auth_header'])).status_code == 404
    async with TestSessionLocal() as db:
        row = await db.get(FailureRecord, request_id)
        assert row.diagnostics == diag
        assert await db.scalar(select(func.count()).select_from(DeliveryReceipt)) == 0
    serialized = json.dumps(lookup.json()) + response.text
    assert secret not in serialized and '@example.com' not in serialized and 'Bearer' not in serialized


async def test_failure_storage_outage_is_truthful(client, registered_agent, monkeypatch):
    _, _, body = await seed(registered_agent, 'internal-project')
    body['query']['meeting_id'] = 'meeting-999'
    monkeypatch.setattr('app.services.receipts.AsyncSessionLocal', lambda: (_ for _ in ()).throw(RuntimeError('synthetic database failure')))
    response = await client.post('/api/v2/query', headers=registered_agent['auth_header'], json=body)
    assert response.status_code == 403 and response.json()['diagnostic_recorded'] is False
    assert 'data' not in response.json()


async def test_diagnostic_schema_rejects_payload_and_invalid_identifiers():
    from pydantic import ValidationError
    fields = dict(contract_id='meeting-actions', contract_version='1.0.0', view_id='internal-project')
    with pytest.raises(ValidationError): FailureDiagnostics(**fields, raw={'title': 'private'})
    with pytest.raises(ValidationError): FailureDiagnostics(**fields, policy_revision='private@example.com')
    diagnostic = FailureDiagnostics(**fields, completed_processors=['private@example.com'])
    assert await record_failure('a'*32, 'test-agent-alpha', 'PROCESSING_UNAVAILABLE', diagnostic) is False


async def test_historical_failure_and_admin_lookup(client, registered_agent, provision_identity):
    admin = await provision_identity('test-admin', scopes=['admin', 'audit'])
    request_id = 'b' * 32
    async with TestSessionLocal() as db, db.begin():
        db.add(FailureRecord(request_id=request_id, source_agent=registered_agent['agent_id'], code='ACCESS_DENIED'))
    for identity in (registered_agent, admin):
        response = await client.get('/api/v2/receipts/' + request_id, headers=identity['auth_header'])
        assert response.status_code == 200
        assert response.json()['diagnostics'] is None
        assert response.json()['code'] == 'ACCESS_DENIED'
