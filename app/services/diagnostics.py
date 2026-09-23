"""Bounded metadata only: never accept payloads, exception text or credentials."""
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class FailureDiagnostics(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, validate_assignment=True)
    contract_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    contract_version: str = Field(pattern=r'^[0-9]+\.[0-9]+\.[0-9]+$', max_length=50)
    view_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    stage: Literal['binding', 'authorization', 'upstream', 'source_validation',
                   'projection', 'processing', 'output_validation', 'obligations', 'receipt'] = 'binding'
    contract_digest: Optional[str] = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    policy_revision: Optional[str] = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    profile_revision: Optional[str] = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    policy_decision: Literal['unknown', 'allowed', 'denied'] = 'unknown'
    source_validation: Literal['unknown', 'passed'] = 'unknown'
    output_validation: Literal['unknown', 'passed'] = 'unknown'
    obligations: Literal['unknown', 'passed'] = 'unknown'
    completed_processors: List[str] = Field(default_factory=list, max_length=256)

    def safe_dump(self):
        # Processor identifiers come only from a validated immutable contract.
        import re
        if any(not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', value) for value in self.completed_processors):
            raise ValueError('INVALID_DIAGNOSTIC_METADATA')
        return self.model_dump()
