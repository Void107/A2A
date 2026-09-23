"""Finite comparisons: unknown constraints take precedence over known breaks."""
from .loader import load_contract, leaves, contract_digest


def compare(old, new):
    old, new = load_contract(old), load_contract(new)
    reasons, security = [], []
    def add(code, view_id=None, classification='breaking'):
        reasons.append(dict(code=code, view_id=view_id, classification=classification))
    if old['contract_id'] != new['contract_id']:
        add('CONTRACT_ID_CHANGED', classification='review_required')
    old_views = {v['view_id']: v for v in old['views']}
    new_views = {v['view_id']: v for v in new['views']}
    for view_id, before in old_views.items():
        after = new_views.get(view_id)
        if after is None:
            add('VIEW_REMOVED', view_id); continue
        a, b = leaves(before['output_schema']), leaves(after['output_schema'])
        if set(a) != set(b) or set(before['projection']) != set(after['projection']):
            add('FIELDS_OR_PROJECTION_CHANGED', view_id)
        def walk(x, y, path=''):
            if x['type'] != y['type']:
                add('FIELD_TYPE_CHANGED', view_id); return
            typ = x['type']
            if typ == 'object':
                if set(x.get('required', [])) != set(y.get('required', [])):
                    add('REQUIRED_CHANGED', view_id)
                for k in x['properties'].keys() & y['properties'].keys():
                    walk(x['properties'][k], y['properties'][k], path + '.' + k)
                ignored = {'properties', 'required'}
            elif typ == 'array':
                walk(x['items'], y['items'], path + '[*]'); ignored = {'items'}
            else:
                ignored = set()
            if {k:v for k,v in x.items() if k not in ignored} != {k:v for k,v in y.items() if k not in ignored}:
                add('SCHEMA_CONSTRAINT_CHANGED', view_id, 'review_required')
        walk(before['output_schema'], after['output_schema'])
        if before['processors'] != after['processors']:
            security.append({'view_id': view_id, 'code': 'PROCESSING_CHANGED'})
    if old['source_schema'] != new['source_schema']:
        add('SOURCE_CHANGED', classification='review_required')
    if old['policies'] != new['policies']:
        # Only set additions/removals of unchanged rules have an exact direction.
        import json
        a = {json.dumps(p, sort_keys=True) for p in old['policies']}
        b = {json.dumps(p, sort_keys=True) for p in new['policies']}
        expand = any(json.loads(p)['effect'] == 'allow' for p in b-a) or any(json.loads(p)['effect'] == 'deny' for p in a-b)
        tighten = any(json.loads(p)['effect'] == 'deny' for p in b-a) or any(json.loads(p)['effect'] == 'allow' for p in a-b)
        security.append({'code': 'ACCESS_RULES_CHANGED', 'direction': 'mixed_or_unknown' if expand and tighten else 'expansion' if expand else 'tightening'})
    if old['delivery'] != new['delivery']:
        security.append({'code': 'DELIVERY_CHANGED'})
    kinds = {r['classification'] for r in reasons}
    classification = 'review_required' if 'review_required' in kinds else 'breaking' if kinds else 'compatible'
    return {'classification': classification, 'reasons': reasons, 'security_changes': security,
            'old_digest': contract_digest(old), 'new_digest': contract_digest(new),
            'consumer_validation': 'not_registered', 'all_consumers_verified': False}
