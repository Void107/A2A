"""Controlled faults on the production API, complementary to the real stack."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select,func
from tests.conftest import TestSessionLocal
from app.models.schemas import ContractVersion,AccessGrant,DeliveryReceipt
from app.contracts.loader import contract_digest
from app.main import app
from app.services.view_processing import ProcessedView

FIXTURE=Path(__file__).resolve().parents[2]/'docs/implementation/examples'


async def seed(actor,view):
    contract=json.loads((FIXTURE/'contract.meeting.json').read_text())
    raw=json.loads((FIXTURE/'raw.meeting.json').read_text())
    async with TestSessionLocal() as db,db.begin():
        db.add(ContractVersion(contract_id='meeting-actions',contract_version='1.0.0',owner_agent_id='provider',provider_agent_id='provider',
            document=contract,digest=contract_digest(contract),state='active'))
        db.add(AccessGrant(grant_id='fault-grant',agent_id=actor['agent_id'],contract_id='meeting-actions',view_id=view,
            allowed_meeting_ids=['meeting-001'],active=True,revision=1))
    request={'target_agent':'provider','contract_id':'meeting-actions','contract_version':'1.0.0','view_id':view,'query':{'meeting_id':'meeting-001'}}
    return contract,raw,request


@pytest.mark.parametrize('mutation',['missing','type','extra','incomplete_processor'])
async def test_output_and_obligations_fail_before_receipt(client,registered_agent,monkeypatch,mutation):
    external=mutation=='incomplete_processor'
    view='external-collaboration' if external else 'internal-project'
    contract,raw,request=await seed(registered_agent,view)
    processors=contract['views'][1 if external else 0]['processors']
    monkeypatch.setattr(app.state,'opa',SimpleNamespace(decide=AsyncMock(return_value={'allow':True,'required_processor_ids':[p['processor_id'] for p in processors],'policy_revision':'contract-policy-1'})),raising=False)
    monkeypatch.setattr(app.state,'upstream',SimpleNamespace(fetch=AsyncMock(return_value=raw)),raising=False)
    monkeypatch.setattr(app.state,'presidio',None,raising=False)
    if external:
        expected=json.loads((FIXTURE/'expected.external.json').read_text())
        monkeypatch.setattr('app.services.delivery.process_view',AsyncMock(return_value=ProcessedView(expected,[],'none')))
    else:
        broken=copy.deepcopy(raw)
        if mutation=='missing':broken.pop('title')
        if mutation=='type':broken['title']=123
        if mutation=='extra':broken['undeclared']='synthetic'
        monkeypatch.setattr('app.services.view_processing.project',lambda *args:broken)
    response=await client.post('/api/v2/query',headers=registered_agent['auth_header'],json=request)
    assert response.status_code==502 and response.json()['code']=='OUTPUT_CONTRACT_VIOLATION'
    assert 'data' not in response.json()
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(DeliveryReceipt))==0
