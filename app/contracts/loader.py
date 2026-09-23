"""Closed schema language and semantic validation for draft.1.

Only audited literal patterns are accepted. No references, scripts, coercion or
network schema resolution. Errors intentionally omit submitted values.
"""
import copy
import hashlib
import json
import math
import re
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

META = json.loads(Path(__file__).with_name('contract.schema.json').read_text())
CHECKER = FormatChecker(formats=['date', 'email'])
PATTERNS = {'^meeting-[0-9]{3}$', '^item-[0-9]{3}$'}
NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')
COMMON = {'type', 'enum', 'const'}
KEYS = {
    'object': {'properties', 'required', 'additionalProperties'},
    'array': {'items', 'minItems', 'maxItems'},
    'string': {'minLength', 'maxLength', 'pattern', 'format'},
    'integer': {'minimum', 'maximum'}, 'number': {'minimum', 'maximum'},
    'boolean': set(), 'null': set(),
}


class ContractInvalid(ValueError):
    code = 'CONTRACT_INVALID'

    def __init__(self, rule):
        self.rule = rule
        super().__init__(f'{self.code}: {rule}')


def require(condition, rule):
    if not condition:
        raise ContractInvalid(rule)


def _json_limits(value, depth=0):
    require(depth <= 32, 'maximum_depth')
    if isinstance(value, dict):
        require(len(value) <= 256 and all(isinstance(k, str) for k in value), 'object_bounds')
        for v in value.values():
            _json_limits(v, depth + 1)
    elif isinstance(value, list):
        require(len(value) <= 1024, 'array_bounds')
        for v in value:
            _json_limits(v, depth + 1)
    elif isinstance(value, float):
        require(math.isfinite(value), 'finite_number')
    else:
        require(value is None or type(value) in (str, int, bool), 'json_type')


def validate_schema_subset(schema, depth=0):
    require(depth <= 12 and isinstance(schema, dict), 'schema_depth_or_type')
    typ = schema.get('type')
    require(isinstance(typ, str) and typ in KEYS, 'schema_type')
    require(set(schema) <= COMMON | KEYS[typ], 'schema_keyword')
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        raise ContractInvalid('schema_shape') from None
    if typ == 'object':
        props = schema.get('properties')
        require(isinstance(props, dict) and bool(props), 'object_properties')
        require(schema.get('additionalProperties') is False, 'closed_object')
        require(set(schema.get('required', [])) <= set(props), 'required_reference')
        for name, child in props.items():
            require(bool(NAME.fullmatch(name)), 'property_name')
            validate_schema_subset(child, depth + 1)
    elif typ == 'array':
        require(isinstance(schema.get('items'), dict), 'array_items')
        require(schema['items'].get('type') == 'object', 'object_arrays_only')
        validate_schema_subset(schema['items'], depth + 1)
    elif typ == 'string':
        require('pattern' not in schema or schema['pattern'] in PATTERNS, 'audited_pattern')
        require('format' not in schema or schema['format'] in ('email', 'date'), 'supported_format')
    for lower, upper in [('minimum', 'maximum'), ('minLength', 'maxLength'), ('minItems', 'maxItems')]:
        if lower in schema and upper in schema:
            require(schema[lower] <= schema[upper], 'ordered_bounds')
    # enum/const cannot make an otherwise-valid schema impossible by type/format.
    base = {k: v for k, v in schema.items() if k not in ('enum', 'const')}
    values = schema.get('enum', []) + ([schema['const']] if 'const' in schema else [])
    for value in values:
        require(Draft202012Validator(base, format_checker=CHECKER).is_valid(value), 'literal_schema_mismatch')
    if 'const' in schema and 'enum' in schema:
        require(schema['const'] in schema['enum'], 'const_enum_mismatch')


def leaves(schema, prefix=''):
    """Leaf schema map preserves object/array traversal in canonical paths."""
    found = {}
    for name, child in schema['properties'].items():
        path = prefix + name
        if child['type'] == 'object':
            found.update(leaves(child, path + '.'))
        elif child['type'] == 'array':
            found.update(leaves(child['items'], path + '[*].'))
        else:
            found[path] = child
    return found


def _unique(items, key):
    values = [item[key] for item in items]
    require(len(values) == len(set(values)), 'duplicate_' + key)


def _duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def load_contract(value):
    """Return a detached validated JSON contract; callers must snapshot it."""
    if isinstance(value, (str, bytes)):
        require(len(value) <= 262144, 'contract_size')
        try:
            value = json.loads(value, object_pairs_hook=_duplicates)
        except (ValueError, RecursionError):
            raise ContractInvalid('invalid_json') from None
    try:
        _json_limits(value)
        require(len(json.dumps(value, allow_nan=False).encode()) <= 262144, 'contract_size')
        require(Draft202012Validator(META).is_valid(value), 'contract_shape')
        source = value['source_schema']
        validate_schema_subset(source)
        require(source['type'] == 'object', 'root_object')
        source_paths = leaves(source)
        _unique(value['views'], 'view_id')
        _unique(value['policies'], 'policy_id')
        views = {v['view_id'] for v in value['views']}
        for policy in value['policies']:
            require(set(policy['view_ids']) <= views, 'policy_view_reference')
        for view in value['views']:
            validate_schema_subset(view['output_schema'])
            require(view['output_schema']['type'] == 'object', 'root_object')
            output_paths = leaves(view['output_schema'])
            projection = set(view['projection'])
            require(projection <= source_paths.keys(), 'projection_source_reference')
            require(projection == output_paths.keys(), 'projection_output_reference')
            for path in projection:
                require(source_paths[path]['type'] == output_paths[path]['type'], 'projection_type')
            _unique(view['processors'], 'processor_id')
            for processor in view['processors']:
                for path in processor['paths']:
                    require(path in projection, 'processor_path_reference')
                    require(source_paths[path]['type'] == 'string', 'processor_text_type')
            # This release's named external view has a mandatory complete profile.
            if view['view_id'] == 'external-collaboration':
                require(not any(p.endswith(('.owner_name', '.owner_email')) for p in projection), 'external_identity')
                scanned = {p for proc in view['processors'] for p in proc['paths']}
                require({'title', 'summary', 'action_items[*].task'} <= scanned, 'external_text_coverage')
                for path in projection:
                    leaf = source_paths[path]
                    if leaf['type'] == 'string' and 'pattern' not in leaf and leaf.get('format') != 'date':
                        require(path in scanned, 'external_free_text_coverage')
        return copy.deepcopy(value)
    except (TypeError, KeyError, RecursionError, OverflowError):
        raise ContractInvalid('invalid_structure') from None


def contract_digest(contract):
    validated = load_contract(contract)
    return hashlib.sha256(json.dumps(validated, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def validate_data(schema, value):
    """Runtime structural guard. Failure never includes raw payload values."""
    validate_schema_subset(schema)
    _json_limits(value)
    require(Draft202012Validator(schema, format_checker=CHECKER).is_valid(value), 'data_schema_mismatch')
