"""Tests exercise the actual contract loader, not a duplicate interpreter."""
import copy
import json
from pathlib import Path

import pytest

from app.contracts import ContractInvalid, load_contract, validate_data
from app.contracts.loader import contract_digest

EXAMPLES = Path(__file__).resolve().parents[2] / 'docs/implementation/examples'


def example(name='contract.meeting.json'):
    return json.loads((EXAMPLES / name).read_text())


def test_golden_schemas_and_detached_snapshot():
    original = example()
    contract = load_contract(original)
    validate_data(contract['source_schema'], example('raw.meeting.json'))
    for view, filename in zip(contract['views'], ['expected.internal.json', 'expected.external.json']):
        validate_data(view['output_schema'], example(filename))
    assert contract_digest(original) == contract_digest(json.dumps(original))
    contract['views'][0]['projection'].clear()
    assert original['views'][0]['projection']


@pytest.mark.parametrize('mutation', [
    lambda c: c.update(spec_version='future'),
    lambda c: c.update(contract_version='01.0.0'),
    lambda c: c.update(validated=True),
    lambda c: c['policies'][0].update(effect='other'),
    lambda c: c['policies'][0].update(conditions={'purpose': 'anything'}),
    lambda c: c['policies'][0].update(principal={}),
    lambda c: c['policies'][0].update(principal={'roles': []}),
    lambda c: c['policies'][0].update(view_ids=['missing']),
    lambda c: c['views'].append(copy.deepcopy(c['views'][0])),
    lambda c: c['policies'].append(copy.deepcopy(c['policies'][0])),
    lambda c: c['views'][0]['projection'].append('*'),
    lambda c: c['views'][0]['projection'].append('action_items'),
    lambda c: c['views'][0]['projection'].append('action_items[0].task'),
    lambda c: c['views'][0]['projection'].pop(),
    lambda c: c['source_schema'].update(additionalProperties=True),
    lambda c: c['source_schema'].update(required=['absent']),
    lambda c: c['source_schema'].update({'$ref': 'https://example.com/schema'}),
    lambda c: c['source_schema'].update(anyOf=[]),
    lambda c: c['source_schema']['properties']['meeting_id'].update(pattern='(a+)+$'),
    lambda c: c['source_schema']['properties']['meeting_id'].update(format='unknown'),
    lambda c: c['views'][1].update(processors=[]),
    lambda c: c['views'][1]['processors'][0].update(type='custom'),
    lambda c: c['views'][1]['processors'][0].update(language='zh'),
    lambda c: c['views'][1]['processors'][0].update(entities=['PERSON']),
    lambda c: c['views'][1]['processors'][0].update(required=False),
    lambda c: c['views'][1]['processors'][0].update(paths=['title', 'summary']),
    lambda c: c['delivery'].update(audit_required=False),
    lambda c: c['delivery'].update(failure_mode='open'),
    lambda c: c['delivery'].update(max_response_bytes=True),
    lambda c: c['delivery'].update(total_timeout_seconds=float('nan')),
])
def test_invalid_contract(mutation):
    contract = example()
    mutation(contract)
    with pytest.raises(ContractInvalid):
        load_contract(contract)


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(secret='synthetic'),
    lambda d: d['action_items'][0].update(secret='synthetic'),
    lambda d: d['action_items'][0].pop('owner_email'),
    lambda d: d['action_items'][0].update(due_date='2026-02-30'),
    lambda d: d.update(meeting_id='alice@example.com'),
    lambda d: d.update(action_items={}),
])
def test_source_drift(mutation):
    data = example('raw.meeting.json')
    mutation(data)
    with pytest.raises(ContractInvalid) as error:
        validate_data(load_contract(example())['source_schema'], data)
    assert 'synthetic' not in str(error.value)
    assert 'alice@example.com' not in str(error.value)


def test_duplicate_keys_and_non_json():
    for value in ['{"a":1,"a":2}', '{', {'x': object()}]:
        with pytest.raises(ContractInvalid):
            load_contract(value)


@pytest.mark.parametrize('response', [{}, {'result': None}, {'result': {}}, {'result': True}])
def test_missing_opa_decisions_fail_closed(response):
    from app.contracts.decision import validate_decision
    with pytest.raises(ContractInvalid):
        validate_decision(response, view_id='v', digest='d', policy_revision='r', processor_ids=[], policy_ids=[])


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(allow='true'),
    lambda r: r.update(contract_digest='wrong'),
    lambda r: r.update(view_id='other'),
    lambda r: r.update(policy_revision='old'),
    lambda r: r.update(required_processor_ids=[]),
    lambda r: r.update(matched_policy_ids=['unknown']),
])
def test_opa_bindings_and_obligations(mutation):
    from app.contracts.decision import validate_decision
    result = {'allow': True, 'reason_code': 'ALLOW', 'matched_policy_ids': ['p'],
              'view_id': 'v', 'contract_digest': 'd', 'policy_revision': 'r',
              'required_processor_ids': ['redact']}
    args = dict(view_id='v', digest='d', policy_revision='r', processor_ids=['redact'], policy_ids=['p'])
    assert validate_decision({'result': result}, **args)['allow'] is True
    mutation(result)
    with pytest.raises(ContractInvalid):
        validate_decision({'result': result}, **args)
