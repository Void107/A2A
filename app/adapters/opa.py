"""The only allow decision source. No cache or legacy authorization fallback."""
import asyncio
import copy

import httpx
from app.adapters.bounded_http import post_json
from app.contracts.decision import validate_decision
from app.contracts.loader import load_contract, contract_digest

POLICY_REVISION = 'contract-policy-1'


class PolicyUnavailable(ValueError):
    code = 'PROCESSING_UNAVAILABLE'


class OPAClient:
    def __init__(self, url, timeout=3):
        self.url, self.timeout = url.rstrip('/') + '/v1/data/hub/contract/decision', timeout
        self.client = httpx.AsyncClient(timeout=timeout, trust_env=False,
                                        limits=httpx.Limits(max_connections=8, max_keepalive_connections=8))

    async def close(self):
        await self.client.aclose()

    async def decide(self, contract, view_id, identity, grant, meeting_id):
        contract = load_contract(contract)
        view = next((v for v in contract['views'] if v['view_id'] == view_id), None)
        if view is None:
            raise PolicyUnavailable('UNKNOWN_VIEW')
        digest = contract_digest(contract)
        context = {'identity': {'agent_ids': [identity['sub']], 'organization_ids': [identity['organization_id']],
                                'roles': identity['roles'], 'is_active': identity['is_active']},
                   'grant': copy.deepcopy(grant), 'view_id': view_id, 'meeting_id': meeting_id,
                   'contract_digest': digest,
                   'contract': {k: contract[k] for k in ('contract_id', 'policies', 'views')}}
        # Do not send schemas, purpose text or response payloads to the decision service.
        context['contract']['views'] = [{'view_id': v['view_id'], 'processors': [
            {'processor_id': p['processor_id'], 'required': p['required']} for p in v['processors']]} for v in contract['views']]
        try:
            response = await asyncio.wait_for(post_json(self.client, self.url, {'input': context}), self.timeout)
            return validate_decision(response, view_id=view_id, digest=digest,
                policy_revision=POLICY_REVISION,
                processor_ids=[p['processor_id'] for p in view['processors'] if p['required']],
                policy_ids=[p['policy_id'] for p in contract['policies']])
        except Exception:
            raise PolicyUnavailable('PROCESSING_UNAVAILABLE') from None
