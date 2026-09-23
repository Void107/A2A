"""Administrator-approved upstream transport: resolve, pin, sign, fully buffer."""
import asyncio
import ipaddress
import json
import socket
from dataclasses import dataclass

import httpx


class UpstreamFailure(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Endpoint:
    url: str
    approved_addresses: tuple
    allow_private: bool = False
    local_test: bool = False

    def validate(self):
        url = httpx.URL(self.url)
        if (url.username or url.password or url.fragment or url.query or
                not url.host or (url.scheme != 'https' and not (self.local_test and url.scheme == 'http'))):
            raise UpstreamFailure('UPSTREAM_TARGET_DENIED')
        if not self.approved_addresses:
            raise UpstreamFailure('UPSTREAM_TARGET_DENIED')
        for address in self.approved_addresses:
            ip = ipaddress.ip_address(address)
            if ip.is_unspecified or ip.is_multicast or ip.is_link_local:
                raise UpstreamFailure('UPSTREAM_TARGET_DENIED')
            if ip.is_loopback and not self.local_test:
                raise UpstreamFailure('UPSTREAM_TARGET_DENIED')
            if not ip.is_global and not self.allow_private and not (ip.is_loopback and self.local_test):
                raise UpstreamFailure('UPSTREAM_TARGET_DENIED')
        return url


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError()
            value[key] = item
        return value
    def invalid_constant(value):
        raise ValueError()
    # Reject pathological nesting before parsing to avoid recursion overflow.
    level = 0
    in_string = escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                in_string = False
        elif byte == 34:
            in_string = True
        elif byte in (123, 91):
            level += 1
            if level > 32:
                raise UpstreamFailure('UPSTREAM_INVALID_JSON')
        elif byte in (125, 93):
            level -= 1
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise UpstreamFailure('UPSTREAM_INVALID_JSON') from None


class UpstreamClient:
    def __init__(self, endpoints, signer, concurrency=8, max_bytes=5242880, timeout=30):
        self.endpoints, self.signer = dict(endpoints), signer
        self.max_bytes, self.timeout = max_bytes, timeout
        self.slots = asyncio.Semaphore(concurrency)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(5), follow_redirects=False, trust_env=False,
                                        limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency))

    async def close(self):
        await self.client.aclose()

    async def fetch(self, target, query, max_bytes, timeout):
        if self.slots.locked():
            raise UpstreamFailure('CONCURRENCY_LIMIT')
        async with self.slots:
            try:
                return await asyncio.wait_for(self._fetch(target, query, min(max_bytes, self.max_bytes)),
                                              min(timeout, self.timeout))
            except asyncio.TimeoutError:
                raise UpstreamFailure('UPSTREAM_TIMEOUT') from None
            except httpx.TimeoutException:
                raise UpstreamFailure('UPSTREAM_TIMEOUT') from None
            except (httpx.HTTPError, OSError):
                raise UpstreamFailure('UPSTREAM_UNAVAILABLE') from None

    async def _fetch(self, target, query, limit):
        endpoint = self.endpoints.get(target)
        if endpoint is None:
            raise UpstreamFailure('UPSTREAM_TARGET_DENIED')
        url = endpoint.validate()
        resolved = await asyncio.to_thread(socket.getaddrinfo, url.host, url.port or (443 if url.scheme == 'https' else 80),
                                           0, socket.SOCK_STREAM)
        addresses = {entry[4][0] for entry in resolved}
        if not addresses or not addresses <= set(endpoint.approved_addresses):
            raise UpstreamFailure('UPSTREAM_TARGET_DENIED')
        # Pin the connection to a verified IP; retain original Host and TLS SNI.
        pinned = url.copy_with(host=sorted(addresses)[0])
        body = json.dumps(query, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        headers = self.signer.sign('POST', url.raw_path.decode('ascii'), body)
        headers.update({'Host': url.netloc.decode(), 'Content-Type': 'application/json', 'Accept-Encoding': 'identity'})
        async with self.client.stream('POST', pinned, content=body, headers=headers,
                                      extensions={'sni_hostname': url.host}) as response:
            if response.status_code != 200 or response.headers.get('content-encoding', 'identity') != 'identity':
                raise UpstreamFailure('UPSTREAM_ERROR')
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > limit:
                    raise UpstreamFailure('PAYLOAD_TOO_LARGE')
                chunks.append(chunk)
            return strict_json(b''.join(chunks))
