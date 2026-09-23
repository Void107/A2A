"""Offline legacy inspection. Mapping requires explicit new schemas and views."""
import copy
from app.contracts.loader import load_contract, ContractInvalid


def migrate(legacy, template):
    errors = []
    if not isinstance(legacy, dict):
        return {'status': 'blocked', 'errors': ['LEGACY_OBJECT_REQUIRED'], 'draft': None}
    if legacy.get('version') != '0.2.0': errors.append('LEGACY_VERSION_UNSUPPORTED')
    if set(legacy) - {'version', 'schemas', 'policies', 'transforms'}: errors.append('UNKNOWN_LEGACY_FIELDS')
    policies = legacy.get('policies', [])
    transforms = legacy.get('transforms', [])
    if not isinstance(policies, list) or not isinstance(transforms, list):
        return {'status': 'blocked', 'errors': ['LEGACY_SHAPE_INVALID'], 'draft': None}
    ids = {t.get('transform_id') for t in transforms if isinstance(t, dict)}
    if transforms: errors.append('TRANSFORM_SEMANTICS_REQUIRE_MANUAL_MIGRATION')
    if len(policies) != 1: errors.append('AMBIGUOUS_MULTIPLE_POLICIES')
    mapped = []
    for policy in policies:
        if not isinstance(policy, dict):
            errors.append('LEGACY_POLICY_INVALID'); continue
        if set(policy) - {'policy_id', 'effect', 'schema_ids', 'principal', 'transform_ids', 'conditions'}:
            errors.append('UNKNOWN_POLICY_FIELDS')
        if policy.get('conditions'): errors.append('UNSUPPORTED_CONDITIONS')
        if policy.get('effect') not in {'allow', 'deny'}: errors.append('INVALID_EFFECT')
        if not set(policy.get('transform_ids', [])) <= ids: errors.append('MISSING_TRANSFORM')
        if '*' in policy.get('schema_ids', []): errors.append('WILDCARD_SCHEMA')
        principal = policy.get('principal', {})
        if not isinstance(principal, dict) or len(principal) != 1 or not set(principal) <= {'agent_ids', 'organizations', 'roles'}:
            errors.append('AMBIGUOUS_PRINCIPAL'); continue
        # Legacy dimensions used OR. Only a single exact dimension can be mapped.
        principal = {('organization_ids' if k == 'organizations' else k): v for k, v in principal.items()}
        mapped.append(dict(policy_id=policy.get('policy_id'), effect=policy.get('effect'),
                           view_ids=[v['view_id'] for v in template.get('views', [])], principal=principal))
    schemas = legacy.get('schemas', [])
    if not isinstance(schemas, list) or len(schemas) != 1 or not policies or any(p.get('schema_ids') != [schemas[0].get('schema_id')] for p in policies if isinstance(p, dict)):
        errors.append('EXPLICIT_SINGLE_SCHEMA_MAPPING_REQUIRED')
    draft = None
    if not errors:
        draft = copy.deepcopy(template); draft['policies'] = mapped
        try: draft = load_contract(draft)
        except ContractInvalid:
            errors.append('TARGET_TEMPLATE_INVALID'); draft = None
    return {'status': 'blocked' if errors else 'draft_only', 'errors': sorted(set(errors)), 'draft': draft,
            'activation': 'never', 'warning': 'Explicit template defines new structure; this is not proof of legacy output equivalence.'}
