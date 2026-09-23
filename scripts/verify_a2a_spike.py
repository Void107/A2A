"""Run the official A2A client and server as separate processes."""
import asyncio
import subprocess
import sys
from verify_real_baseline import ROOT


async def main():
    import httpx
    log = (ROOT / 'docs/verification/t05-server.log').open('w')
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'examples.a2a_spike.server:app',
        '--host', '127.0.0.1', '--port', '58184', '--no-access-log'], cwd=ROOT, stdout=log, stderr=log)
    try:
        async with httpx.AsyncClient() as http:
            for _ in range(100):
                if process.poll() is not None: raise RuntimeError('A2A server failed')
                try:
                    if (await http.get('http://127.0.0.1:58184/.well-known/agent-card.json')).status_code == 200: break
                except httpx.HTTPError: pass
                await asyncio.sleep(.05)
            else: raise RuntimeError('A2A not ready')
        subprocess.run([sys.executable, '-m', 'examples.a2a_spike.client'], cwd=ROOT, check=True)
    finally:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill(); process.wait()
        log.close()


if __name__ == '__main__': asyncio.run(main())
