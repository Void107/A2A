"""A new uniquely owned test database must never look ready before migration."""
import asyncio
import os
import subprocess
import sys
import uuid
from verify_real_baseline import ROOT

async def main():
    import asyncpg
    from check_test_services import main as probe
    await probe()
    connection=await asyncpg.connect(host='127.0.0.1',port=55432,user='a2a_test',password='local-synthetic-test-only',database='a2a_test')
    name='a2a_readiness_'+uuid.uuid4().hex
    await connection.execute('CREATE DATABASE "'+name+'"')
    try:
        env=dict(os.environ,DATABASE_URL='postgresql+asyncpg://a2a_test:local-synthetic-test-only@127.0.0.1:55432/'+name,
            HUB_SIGNING_KEY_FILE='',PRESIDIO_URL='',A2A_ENABLED='false')
        code='''import asyncio
from app.main import app
from app.database import engine
from httpx import AsyncClient,ASGITransport
async def run():
 async with app.router.lifespan_context(app):
  async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as http:
   assert (await http.get('/health')).status_code==200
   result=await http.get('/ready')
   assert result.status_code==503
   assert 'DATABASE_UNAVAILABLE_OR_UNMIGRATED' in result.json()['errors']
   assert 'PROFILE_NOT_READY' in result.json()['errors']
   print('PASS AC-21: fresh unmigrated database and missing profile reject readiness with safe error codes')
 await engine.dispose()
asyncio.run(run())'''
        subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,check=True)
    finally:
        # Only the exact database created by this invocation is removed.
        await connection.execute('DROP DATABASE "'+name+'"')
        await connection.close()

if __name__=='__main__':asyncio.run(main())
