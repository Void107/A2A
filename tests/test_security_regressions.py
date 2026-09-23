"""Unfixed security expectations: intentionally red, never xfail or skip.

These target the real legacy functions currently reached by API handlers.
The recorded baseline is not a release gate pass.
"""
from unittest.mock import patch

import pytest

from app.core.interceptor import evaluate_contract
from app.services.transform import apply_transforms
from app.services.audit_writer import _flush_batch


def contract(effect='allow', transforms=None, conditions=None):
    policy = {'policy_id': 'p', 'effect': effect, 'schema_ids': ['s'],
              'principal': {'public': True}, 'transform_ids': transforms or []}
    if conditions is not None:
        policy['conditions'] = conditions
    return {'schemas': [{'schema_id': 's'}], 'policies': [policy], 'transforms': []}


def test_no_matching_rule_denies():
    assert evaluate_contract({'schemas': [{'schema_id': 's'}], 'policies': []}, 's', {})['decision'] == 'blocked'


def test_unknown_effect_denies():
    assert evaluate_contract(contract(effect='typo'), 's', {})['decision'] == 'blocked'


def test_missing_transform_denies():
    assert evaluate_contract(contract(transforms=['missing']), 's', {})['decision'] == 'blocked'


def test_unimplemented_conditions_deny():
    assert evaluate_contract(contract(conditions={'unknown': True}), 's', {})['decision'] == 'blocked'


@pytest.mark.parametrize('rule', [
    {'type': 'custom', 'applies_to_fields': ['field']},
    {'type': 'aggregate', 'applies_to_fields': ['field'], 'config': {'aggregation_function': 'avg'}},
    {'type': 'truncate', 'applies_to_fields': ['field'], 'config': {'truncate_length': 'invalid'}},
    {'type': 'redact', 'applies_to_fields': ['*']},
])
def test_unsupported_processing_never_returns_original(rule):
    with pytest.raises(ValueError):
        apply_transforms({'field': [1, 2]}, [rule])


async def test_audit_storage_failure_propagates():
    class UnavailableSession:
        async def __aenter__(self):
            raise RuntimeError('synthetic database outage')

        async def __aexit__(self, *args):
            return False

    with patch('app.services.audit_writer.AsyncSessionLocal', return_value=UnavailableSession()):
        with pytest.raises(RuntimeError):
            await _flush_batch([{'request_id': 'synthetic-request'}])
