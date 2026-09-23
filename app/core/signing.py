"""Ed25519 over exact bytes/method/target/time/nonce; replay state is persistent."""
import base64
import hashlib
import re
import time
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key


def message(method, target, timestamp, nonce, body):
    return '\n'.join([method.upper(), target, timestamp, nonce, hashlib.sha256(body).hexdigest()]).encode()


class Signer:
    def __init__(self, key, key_id):
        if not isinstance(key, Ed25519PrivateKey) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', key_id):
            raise ValueError('INVALID_SIGNING_KEY')
        self.key, self.key_id = key, key_id

    @classmethod
    def from_file(cls, path, key_id):
        path = Path(path)
        if path.stat().st_mode & 0o077:
            raise ValueError('PRIVATE_KEY_PERMISSIONS')
        return cls(load_pem_private_key(path.read_bytes(), password=None), key_id)

    def sign(self, method, target, body):
        timestamp, nonce = str(int(time.time())), uuid.uuid4().hex
        signature = self.key.sign(message(method, target, timestamp, nonce, body))
        return {'X-Hub-Key-Id': self.key_id, 'X-Hub-Timestamp': timestamp,
                'X-Hub-Nonce': nonce, 'X-Hub-Signature': base64.b64encode(signature).decode()}


async def verify(headers, method, target, body, public_keys, redis):
    """Receiver must enforce this before reading business query fields.

    public_keys is provisioned by the operator, never from the incoming request.
    Redis failure rejects; keys may be removed to revoke them. No replay cache
    lives only in one worker process.
    """
    headers = {k.lower(): v for k, v in headers.items()}
    try:
        kid, timestamp, nonce = [headers[k] for k in ('x-hub-key-id', 'x-hub-timestamp', 'x-hub-nonce')]
        if not re.fullmatch(r'[0-9a-f]{32}', nonce) or not re.fullmatch(r'[0-9]{10,12}', timestamp):
            return False
        if abs(time.time() - int(timestamp)) > 60:
            return False
        signature = base64.b64decode(headers['x-hub-signature'], validate=True)
        public_keys[kid].verify(signature, message(method, target, timestamp, nonce, body))
        return bool(await redis.set('hub:nonce:' + kid + ':' + nonce, '1', nx=True, ex=121))
    except Exception:
        return False


class PostgresNonceStore:
    """Provider-side alternative which leaves Redis optional for delivery."""
    async def set(self, name, value, *, nx, ex):
        from datetime import datetime, timedelta
        from sqlalchemy import delete
        from sqlalchemy.dialects.postgresql import insert
        from app.database import AsyncSessionLocal
        from app.models.schemas import UpstreamNonce
        async with AsyncSessionLocal() as db, db.begin():
            await db.execute(delete(UpstreamNonce).where(UpstreamNonce.expires_at < datetime.utcnow()))
            result = await db.execute(insert(UpstreamNonce).values(nonce=name,
                expires_at=datetime.utcnow() + timedelta(seconds=ex)).on_conflict_do_nothing().returning(UpstreamNonce.nonce))
            return result.scalar_one_or_none() is not None
