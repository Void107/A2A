"""Real local TLS with certificate verification and hostname-preserving IP pinning."""
import asyncio
import datetime
import ipaddress
import ssl
import tempfile
from pathlib import Path
from unittest.mock import patch
from verify_real_baseline import ROOT

async def main():
    import httpx
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa, ed25519
    from cryptography.x509.oid import NameOID
    from app.core.signing import Signer
    from app.adapters.upstream import Endpoint, UpstreamClient, UpstreamFailure
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'upstream.test')])
    now=datetime.datetime.now(datetime.timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
        .not_valid_after(now+datetime.timedelta(hours=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('upstream.test')]),False)
        .sign(key,hashes.SHA256()))
    received=[]; sni=[]
    async def serve(reader,writer):
        try:
            lines=(await reader.readuntil(b'\r\n\r\n')).decode().split('\r\n')
            headers=dict(line.split(': ',1) for line in lines if ': ' in line)
            await reader.readexactly(int(headers['Content-Length'])); received.append(headers['Host'])
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{"ok":true}')
            await writer.drain()
        finally: writer.close()
    with tempfile.TemporaryDirectory(prefix='a2a-tls-') as folder:
        folder=Path(folder);(folder/'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (folder/'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        (folder/'key.pem').chmod(0o600)
        server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_context.load_cert_chain(folder/'cert.pem',folder/'key.pem')
        server_context.set_servername_callback(lambda sock,name,ctx:sni.append(name))
        server=await asyncio.start_server(serve,'127.0.0.1',0,ssl=server_context)
        port=server.sockets[0].getsockname()[1]
        client=UpstreamClient({'ok':Endpoint('https://upstream.test:'+str(port)+'/meeting',('127.0.0.1',),local_test=True),
            'wrong':Endpoint('https://wrong.test:'+str(port)+'/meeting',('127.0.0.1',),local_test=True)},Signer(ed25519.Ed25519PrivateKey.generate(),'tls-test'))
        try:
            with patch('app.adapters.upstream.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',port))]):
                try: await client.fetch('ok',{},1024,2)
                except UpstreamFailure as e: assert e.code=='UPSTREAM_UNAVAILABLE'
                else: raise AssertionError('untrusted certificate accepted')
                assert not received
                await client.close()
                context=ssl.create_default_context(cafile=str(folder/'cert.pem'))
                client.client=httpx.AsyncClient(verify=context,trust_env=False,follow_redirects=False)
                assert await client.fetch('ok',{},1024,2)=={'ok':True}
                assert received==['upstream.test:'+str(port)] and 'upstream.test' in sni
                try: await client.fetch('wrong',{},1024,2)
                except UpstreamFailure as e: assert e.code=='UPSTREAM_UNAVAILABLE'
                else: raise AssertionError('wrong hostname accepted')
                assert len(received)==1
        finally:
            await client.close();server.close();await server.wait_closed()
    print('PASS AC-04: actual verified TLS, untrusted certificate and hostname mismatch rejected before HTTP; original Host/SNI retained with IP pinning')

if __name__=='__main__':asyncio.run(main())
