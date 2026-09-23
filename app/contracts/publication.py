"""Owner-registered synthetic examples run through the actual processing service."""
from typing import Optional
import hashlib
import json
from pydantic import BaseModel, ConfigDict, Field
from app.contracts.loader import leaves, validate_data
from app.services.view_processing import process_view
from examples.meeting_views.consume import consume


class ConsumerCase(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    consumer_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    view_id: str
    source: dict
    expected_output: dict
    required_paths: list[str]
    forbidden_paths: list[str] = Field(default_factory=list)
    expected_tasks: list[dict]


class PublicationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    consumers: list[ConsumerCase] = Field(max_length=32)
    migration_id: Optional[str] = Field(default=None, pattern=r'^[a-z][a-z0-9-]{0,63}$')


def report_digest(report):
    return hashlib.sha256(json.dumps(report, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


async def validate_consumers(contract, bundle, presidio):
    results = []
    ids = [c.consumer_id for c in bundle.consumers]
    if len(set(ids)) != len(ids):
        raise ValueError('DUPLICATE_CONSUMER')
    for case in bundle.consumers:
        try:
            view = next(v for v in contract['views'] if v['view_id'] == case.view_id)
            fields = leaves(view['output_schema'])
            if not set(case.required_paths) <= fields.keys() or set(case.forbidden_paths) & fields.keys():
                raise ValueError('CONSUMER_FIELD_REQUIREMENTS')
            validate_data(view['output_schema'], case.expected_output)
            result = await process_view(contract, case.view_id, case.source, presidio, case.source.get('meeting_id'))
            if result.data != case.expected_output:
                raise ValueError('CONSUMER_OUTPUT_CHANGED')
            if consume(result.data, case.view_id) != case.expected_tasks:
                raise ValueError('CONSUMER_TASK_EFFECT_CHANGED')
            code = 'PASS'
        except Exception as error:
            code = getattr(error, 'code', 'CONSUMER_REQUIREMENTS_FAILED')
        results.append({'consumer_id': case.consumer_id, 'view_id': case.view_id, 'result': code})
    return results


def enforce(reports, results, version, bundle, acknowledgement, expected_digest, default=False, previous_ids=()):
    """No force flag: evidence never overrides unknown semantics or failed checks."""
    if any(r['classification'] == 'review_required' for r in reports):
        raise ValueError('PUBLICATION_REVIEW_REQUIRED')
    if any(r['result'] != 'PASS' for r in results):
        raise ValueError('CONSUMER_VALIDATION_FAILED')
    breaking = [r for r in reports if r['classification'] == 'breaking']
    if breaking:
        if not results or not bundle.migration_id:
            raise ValueError('MIGRATION_EVIDENCE_REQUIRED')
        if not default and any(int(version.split('.')[0]) <= int(r['old_version'].split('.')[0]) for r in breaking):
            raise ValueError('NEW_MAJOR_VERSION_REQUIRED')
        if default and not set(previous_ids) <= {r['consumer_id'] for r in results}:
            raise ValueError('DEFAULT_CONSUMERS_NOT_MIGRATED')
    if breaking or any(r['security_changes'] for r in reports):
        if acknowledgement != expected_digest:
            raise ValueError('EXPLICIT_REPORT_ACKNOWLEDGEMENT_REQUIRED')
