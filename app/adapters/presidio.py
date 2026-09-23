"""A bounded client for the fixed English email-only Presidio service."""
import asyncio
import httpx
from app.adapters.bounded_http import post_json

from app.profile import PROFILE


class PresidioClient:
    profile_revision = PROFILE

    def __init__(self, url, timeout=3):
        self.url, self.timeout = url.rstrip('/'), timeout
        self.client = httpx.AsyncClient(timeout=timeout, trust_env=False)

    async def close(self):
        await self.client.aclose()

    async def redact(self, text):
        if not isinstance(text, str) or len(text) > 3000:
            raise ValueError('PROCESSING_UNAVAILABLE')
        payload = await asyncio.wait_for(post_json(self.client, self.url + '/redact', {'text': text, 'profile_revision': PROFILE}), self.timeout)
        if (set(payload) != {'text', 'profile_revision', 'completed'} or payload['completed'] is not True
                or payload['profile_revision'] != PROFILE or not isinstance(payload['text'], str)):
            raise ValueError('PROCESSING_UNAVAILABLE')
        return payload['text']
