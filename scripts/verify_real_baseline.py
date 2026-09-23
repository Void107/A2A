"""Real PostgreSQL/Redis migration and lifespan baseline on dedicated test ports."""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OPA_BINARY = os.environ.get('OPA_BINARY', '/private/tmp/a2a-opa-1.0.0')
PRESIDIO_PYTHON = os.environ.get('PRESIDIO_PYTHON', str(ROOT / '.venv-presidio/bin/python'))
os.environ.update(DATABASE_URL='postgresql+asyncpg://a2a_test:local-synthetic-test-only@127.0.0.1:55432/a2a_test',
                  REDIS_URL='redis://127.0.0.1:56379/0',
                  JWT_SECRET='synthetic-baseline-signing-key-at-least-32-bytes')


async def verify():
    from check_test_services import main as probe
    await probe()  # Checks exact database before any migration.
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT, check=True)
    from app.main import app
    from app.database import engine, AsyncSessionLocal
    from sqlalchemy import text
    from httpx import ASGITransport, AsyncClient
    for attempt in range(2):
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
                assert (await client.get('/health')).json()['status'] == 'ok'
                response = await client.get('/ready')
                assert response.status_code == 503 and 'UPSTREAM_NOT_CONFIGURED' in response.json()['errors']
            async with AsyncSessionLocal() as db:
                version = (await db.execute(text('SELECT version_num FROM alembic_version'))).scalar_one()
                assert version
        print('control-plane lifespan; unconfigured delivery correctly not ready; cycle', attempt + 1, 'PASS; migration', version)
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(verify())
