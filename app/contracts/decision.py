"""Validate one OPA decision, without evaluating or falling back to legacy policy."""
from .loader import ContractInvalid


def validate_decision(response, *, view_id, digest, policy_revision, processor_ids, policy_ids):
    expected = {'allow', 'reason_code', 'matched_policy_ids', 'view_id',
                'contract_digest', 'policy_revision', 'required_processor_ids'}
    result = response.get('result') if isinstance(response, dict) else None
    if not isinstance(result, dict) or set(result) != expected:
        raise ContractInvalid('opa_decision_shape')
    if (type(result['allow']) is not bool or
            result['reason_code'] != ('ALLOW' if result['allow'] else 'ACCESS_DENIED') or
            result['view_id'] != view_id or result['contract_digest'] != digest or
            result['policy_revision'] != policy_revision):
        raise ContractInvalid('opa_decision_binding')
    for key in ('matched_policy_ids', 'required_processor_ids'):
        values = result[key]
        if (not isinstance(values, list) or not all(isinstance(v, str) for v in values)
                or len(values) != len(set(values))):
            raise ContractInvalid('opa_decision_ids')
    if (not set(result['matched_policy_ids']) <= set(policy_ids)
            or result['required_processor_ids'] != processor_ids
            or (result['allow'] and not result['matched_policy_ids'])):
        raise ContractInvalid('opa_decision_obligations')
    return result.copy()
