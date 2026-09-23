import copy
import json
from pathlib import Path
import pytest
from examples.meeting_views.consume import consume
from app.contracts.publication import PublicationInput, validate_consumers

FIXTURE=Path(__file__).resolve().parents[2]/'docs/implementation/examples'


def test_assignment_requires_email_and_preserves_pairing():
    raw=json.loads((FIXTURE/'expected.internal.json').read_text())
    tasks=consume(raw,'internal-project')
    assert [t['assignee'] for t in tasks]==['alice@example.com','bob@example.com']
    assert [t['due_date'] for t in tasks]==['2026-09-20','2026-09-21']
    broken=copy.deepcopy(raw);broken['action_items'][0].pop('owner_email')
    with pytest.raises(KeyError):consume(broken,'internal-project')
    reordered=copy.deepcopy(raw)
    reordered['action_items'][0]['due_date'],reordered['action_items'][1]['due_date']=reordered['action_items'][1]['due_date'],reordered['action_items'][0]['due_date']
    assert consume(reordered,'internal-project')!=tasks


async def test_real_processor_consumer_check_rejects_wrong_effect():
    contract=json.loads((FIXTURE/'contract.meeting.json').read_text())
    raw=json.loads((FIXTURE/'raw.meeting.json').read_text())
    expected=json.loads((FIXTURE/'expected.internal.json').read_text())
    bundle=PublicationInput(consumers=[{'consumer_id':'internal-task-assigner','view_id':'internal-project',
        'source':raw,'expected_output':expected,'required_paths':['action_items[*].owner_email'],
        'expected_tasks':[]}])
    result=await validate_consumers(contract,bundle,None)
    assert result[0]['result']=='CONSUMER_REQUIREMENTS_FAILED'
