"""T03 real local HTTP transport, Ed25519 and shared Redis replay tests."""
import asyncio
import sys
import time
from unittest.mock import patch

from verify_real_baseline import ROOT


async def main():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from app.core.signing import Signer, verify
    from app.adapters.upstream import Endpoint, UpstreamClient, UpstreamFailure, strict_json
    from redis.asyncio import Redis
    key = Ed25519PrivateKey.generate()
    signer = Signer(key, 'synthetic-test-key')
    public = {signer.key_id: key.public_key()}
    redis = Redis(host='127.0.0.1', port=56379)
    body = b'{"meeting_id":"meeting-001"}'
    headers = signer.sign('POST', '/normal', body)
    assert not await verify(headers, 'POST', '/normal', body + b' ', public, redis)
    assert not await verify(headers, 'GET', '/normal', body, public, redis)
    assert not await verify(headers, 'POST', '/different', body, public, redis)
    assert not await verify(dict(headers, **{'X-Hub-Key-Id': 'unknown'}), 'POST', '/normal', body, public, redis)
    assert not await verify(dict(headers, **{'X-Hub-Timestamp': str(int(time.time()) - 300)}), 'POST', '/normal', body, public, redis)
    assert await verify(headers, 'POST', '/normal', body, public, redis)
    assert not await verify(headers, 'POST', '/normal', body, public, redis)
    received = []
    async def serve(reader, writer):
        try:
            raw_headers = await reader.readuntil(b'\r\n\r\n')
            lines = raw_headers.decode().split('\r\n')
            method, path, _ = lines[0].split()
            h = dict(line.split(': ', 1) for line in lines[1:] if ': ' in line)
            raw = await reader.readexactly(int(h.get('Content-Length', '0')))
            assert await verify(h, method, path, raw, public, redis)
            received.append(path)
            response = b'{"ok":true}'
            if path == '/large': response = b'"' + b'x' * 100 + b'"'
            if path == '/invalid': response = b'not json'
            if path == '/redirect':
                writer.write(b'HTTP/1.1 302 Found\r\nLocation: /normal\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            else:
                writer.write(b'HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: ' + str(len(response)).encode() + b'\r\n\r\n')
                if path == '/slow':
                    for b in response:
                        writer.write(bytes([b])); await writer.drain(); await asyncio.sleep(.03)
                else: writer.write(response)
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    endpoints = {path: Endpoint('http://127.0.0.1:' + str(port) + '/' + path, ('127.0.0.1',), local_test=True)
                 for path in ['normal', 'large', 'invalid', 'redirect', 'slow']}
    client = UpstreamClient(endpoints, signer, concurrency=1)
    try:
        assert await client.fetch('normal', {'meeting_id': 'meeting-001'}, 1024, 1) == {'ok': True}
        for path, limit, timeout, code in [('large', 101, 1, 'PAYLOAD_TOO_LARGE'),
                                          ('invalid', 1024, 1, 'UPSTREAM_INVALID_JSON'),
                                          ('redirect', 1024, 1, 'UPSTREAM_ERROR'),
                                          ('slow', 1024, .05, 'UPSTREAM_TIMEOUT'),
                                          ('unknown', 1024, 1, 'UPSTREAM_TARGET_DENIED')]:
            try: await client.fetch(path, {}, limit, timeout)
            except UpstreamFailure as e: assert e.code == code, e.code
            else: raise AssertionError(path)
        assert len(await client.fetch('large', {}, 102, 1)) == 100
        before = len(received)
        with patch('app.adapters.upstream.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('169.254.169.254', port))]):
            try: await client.fetch('normal', {}, 1024, 1)
            except UpstreamFailure as e: assert e.code == 'UPSTREAM_TARGET_DENIED'
            else: raise AssertionError('DNS approval not checked')
        assert len(received) == before
        async with client.slots:
            try: await client.fetch('normal', {}, 1024, 1)
            except UpstreamFailure as e: assert e.code == 'CONCURRENCY_LIMIT'
            else: raise AssertionError('unbounded concurrency')
        for endpoint in [Endpoint('http://127.0.0.1/', ('127.0.0.1',)),
                         Endpoint('https://169.254.169.254/', ('169.254.169.254',)),
                         Endpoint('https://example.com/', ())]:
            try: endpoint.validate()
            except UpstreamFailure: pass
            else: raise AssertionError('unsafe endpoint')
        for raw in [b'{"a":1,"a":2}', b'{"a":NaN}', b'[' * 33 + b']' * 33]:
            try: strict_json(raw)
            except UpstreamFailure: pass
            else: raise AssertionError('invalid JSON accepted')
        print('PASS: real signed HTTP; tamper/method/path/expiry/key/replay; address pinning; redirect/size/JSON/depth/deadline/concurrency')
    finally:
        await client.close()
        server.close(); await server.wait_closed()
        await redis.aclose()


if __name__ == '__main__':
    asyncio.run(main())
