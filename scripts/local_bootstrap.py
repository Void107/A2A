"""Dedicated synthetic compose initialization; never uses host .env."""
import asyncio
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def secret(path, factory):
    path=Path(path)
    if not path.exists():
        with path.open('xb') as f:
            os.chmod(path, 0o600); f.write(factory())
    return path.read_bytes()


async def main():
    if os.environ.get('LOCAL_SYNTHETIC_STACK') != '1': raise RuntimeError('LOCAL_STACK_REQUIRED')
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption, load_pem_private_key
    key=secret('/state/hub.pem',lambda: Ed25519PrivateKey.generate().private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption()))
    Path('/public/hub.pub').write_bytes(load_pem_private_key(key,None).public_key().public_bytes(Encoding.PEM,PublicFormat.SubjectPublicKeyInfo))
    os.environ['JWT_SECRET']=secret('/state/jwt',lambda:secrets.token_hex(32).encode()).decode()
    api_key=secret('/state/admin-key',lambda:secrets.token_urlsafe(32).encode()).decode()
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],check=True)
    from app.database import AsyncSessionLocal,engine
    from app.models.schemas import Agent
    from sqlalchemy import select
    from app.core.security import hash_api_key
    async with AsyncSessionLocal() as db, db.begin():
        if not await db.scalar(select(Agent).where(Agent.agent_id == 'meeting-provider')):
            db.add(Agent(agent_id='meeting-provider',display_name='Synthetic Provider',callback_url='',domain='org-acme',
                roles=['admin'],scopes=['admin','contracts:write','audit'],data_contract={},api_key_hash=hash_api_key(api_key),hub_shared_secret_hash=''))
    await engine.dispose()
    print('Synthetic database migrated; local credentials initialized without printing secrets.')


if __name__=='__main__': asyncio.run(main())
