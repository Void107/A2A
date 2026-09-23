"""One production entry for strict source validation, projection and processors."""
import copy
import time
from dataclasses import dataclass

from app.contracts import load_contract, validate_data


class ProcessingFailure(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def project(data, schema, projection, prefix=''):
    result = {}
    for name, child in schema['properties'].items():
        path = prefix + name
        if name not in data:
            continue
        if path in projection:
            result[name] = copy.deepcopy(data[name])
        elif any(p.startswith(path + '.') or p.startswith(path + '[*].') for p in projection):
            if child['type'] == 'array':
                result[name] = [project(item, child['items'], projection, path + '[*].') for item in data[name]]
            else:
                result[name] = project(data[name], child, projection, path + '.')
    return result


async def transform_path(node, segments, redact):
    name = segments[0]
    array = name.endswith('[*]')
    name = name[:-3] if array else name
    if name not in node:
        return  # Optional source fields may be absent; schema validation handles required ones.
    if array:
        for item in node[name]:
            await transform_path(item, segments[1:], redact)
    elif len(segments) == 1:
        node[name] = await redact(node[name])
    else:
        await transform_path(node[name], segments[1:], redact)


@dataclass
class ProcessedView:
    data: dict
    completed_processors: list
    profile_revision: str
    validation_ms: float = 0
    detection_ms: float = 0


async def process_view(contract, view_id, raw, presidio, requested_meeting_id, diagnostics=None):
    if diagnostics is not None:
        diagnostics.stage = 'source_validation'
    started = time.perf_counter()
    contract = load_contract(contract)
    view = next((v for v in contract['views'] if v['view_id'] == view_id), None)
    if view is None:
        raise ProcessingFailure('CONTRACT_INVALID')
    try:
        validate_data(contract['source_schema'], raw)
    except ValueError:
        raise ProcessingFailure('UPSTREAM_SCHEMA_MISMATCH') from None
    if raw.get('meeting_id') != requested_meeting_id:
        raise ProcessingFailure('UPSTREAM_RESOURCE_MISMATCH')
    if diagnostics is not None:
        diagnostics.source_validation = 'passed'
        diagnostics.stage = 'projection'
    result = project(raw, contract['source_schema'], set(view['projection']))
    validation_ms = (time.perf_counter() - started) * 1000
    detection_started = time.perf_counter()
    completed = []
    revision = 'none'
    if diagnostics is not None:
        diagnostics.stage = 'processing'
    for processor in view['processors']:
        if presidio is None:
            raise ProcessingFailure('PROCESSING_UNAVAILABLE')
        try:
            revision = presidio.profile_revision
            for path in processor['paths']:
                await transform_path(result, path.split('.'), presidio.redact)
            completed.append(processor['processor_id'])
            if diagnostics is not None:
                diagnostics.profile_revision = revision
                diagnostics.completed_processors = list(completed)
        except Exception:
            raise ProcessingFailure('PROCESSING_UNAVAILABLE') from None
    detection_ms = (time.perf_counter() - detection_started) * 1000
    if diagnostics is not None:
        diagnostics.stage = 'output_validation'
    validation_started = time.perf_counter()
    if completed != [p['processor_id'] for p in view['processors']]:
        raise ProcessingFailure('OUTPUT_CONTRACT_VIOLATION')
    try:
        validate_data(view['output_schema'], result)
    except ValueError:
        raise ProcessingFailure('OUTPUT_CONTRACT_VIOLATION') from None
    validation_ms += (time.perf_counter() - validation_started) * 1000
    if diagnostics is not None:
        diagnostics.output_validation = 'passed'
        diagnostics.profile_revision = revision
    return ProcessedView(result, completed, revision, validation_ms, detection_ms)
