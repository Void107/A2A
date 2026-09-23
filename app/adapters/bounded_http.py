"""Buffer bounded JSON only; never read an unbounded dependency response."""
import json


async def post_json(client, url, payload, limit=65536):
    async with client.stream('POST', url, json=payload) as response:
        if response.status_code != 200:
            raise ValueError('DEPENDENCY_UNAVAILABLE')
        chunks, size = [], 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > limit:
                raise ValueError('DEPENDENCY_RESPONSE_TOO_LARGE')
            chunks.append(chunk)
        return json.loads(b''.join(chunks))
