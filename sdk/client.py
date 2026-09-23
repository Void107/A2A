"""Minimal async Python caller; server owns authorization and processing."""
import httpx


class ContractError(Exception):
    def __init__(self, code, request_id=None):
        self.code, self.request_id = code, request_id
        super().__init__(code)


class ContractClient:
    def __init__(self, url, token):
        self.http = httpx.AsyncClient(base_url=url, headers={'Authorization': 'Bearer ' + token}, timeout=35, trust_env=False)

    async def close(self):
        await self.http.aclose()

    @staticmethod
    def unpack(response):
        body = response.json()
        if response.is_error:
            detail = body.get('detail', body)
            raise ContractError(detail.get('code', 'REQUEST_FAILED'), body.get('request_id'))
        return body

    async def discover(self):
        return self.unpack(await self.http.get('/api/v2/contracts/discover'))

    async def query(self, provider, contract_id, version, view_id, meeting_id):
        return self.unpack(await self.http.post('/api/v2/query', json={
            'target_agent': provider, 'contract_id': contract_id, 'contract_version': version,
            'view_id': view_id, 'query': {'meeting_id': meeting_id}}))
