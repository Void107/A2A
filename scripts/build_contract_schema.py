"""Generate the closed contract meta-schema (no runtime remote resolution)."""
import json
from pathlib import Path


def obj(properties, required=None):
    return {'type': 'object', 'properties': properties,
            'required': list(properties) if required is None else required,
            'additionalProperties': False}


def seq(items, minimum=1):
    return {'type': 'array', 'items': items, 'minItems': minimum, 'maxItems': 256, 'uniqueItems': True}


identifier = {'type': 'string', 'pattern': '^[a-z][a-z0-9-]{0,63}$'}
text = {'type': 'string', 'minLength': 1, 'maxLength': 3000}
path = {'type': 'string', 'minLength': 1, 'maxLength': 256}
processor = obj({
    'processor_id': identifier, 'type': {'const': 'presidio_redact'},
    'paths': seq(path), 'language': {'const': 'en'},
    'entities': {'const': ['EMAIL_ADDRESS']}, 'replacement': {'const': '[EMAIL]'},
    'required': {'const': True},
})
# Recursive closed meta-schema; the loader additionally validates keyword/type
# consistency, references, projection and the supported content profile.
node = {'$ref': '#/$defs/schemaNode'}
view = obj({'view_id': identifier, 'display_name': text, 'purpose': text,
            'projection': seq(path), 'output_schema': node, 'processors': seq(processor, 0)})
principal = obj({k: seq(identifier) for k in ['agent_ids', 'organization_ids', 'roles']}, [])
principal['minProperties'] = 1
policy = obj({'policy_id': identifier, 'effect': {'enum': ['allow', 'deny']},
              'view_ids': seq(identifier), 'principal': principal})
schema = obj({
    'spec_version': {'const': '0.3.0-draft.1'}, 'contract_id': identifier,
    'contract_version': {'type': 'string', 'pattern': '^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$'},
    'source_schema': node, 'views': seq(view), 'policies': seq(policy, 0),
    'delivery': obj({'failure_mode': {'const': 'closed'}, 'audit_required': {'const': True},
                     'max_response_bytes': {'type': 'integer', 'minimum': 1, 'maximum': 5242880},
                     'total_timeout_seconds': {'type': 'number', 'exclusiveMinimum': 0, 'maximum': 30}}),
})
schema['$defs'] = {'schemaNode': obj({
    'type': {'enum': ['object', 'array', 'string', 'integer', 'number', 'boolean', 'null']},
    'properties': {'type': 'object', 'additionalProperties': node},
    'required': seq({'type': 'string'}, 0), 'additionalProperties': {'const': False},
    'items': node, 'enum': {'type': 'array', 'minItems': 1, 'uniqueItems': True}, 'const': {},
    'pattern': {'enum': ['^meeting-[0-9]{3}$', '^item-[0-9]{3}$']},
    'format': {'enum': ['email', 'date']},
    **{k: {'type': 'integer', 'minimum': 0} for k in ['minLength', 'maxLength', 'minItems', 'maxItems']},
    **{k: {'type': 'number'} for k in ['minimum', 'maximum']},
}, ['type'])}
schema['$schema'] = 'https://json-schema.org/draft/2020-12/schema'
Path('app/contracts/contract.schema.json').write_text(json.dumps(schema, indent=2) + '\n')
