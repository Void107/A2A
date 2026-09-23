"""Synthetic signed upstream. Public key is provisioned separately from Hub."""
import json
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from app.core.signing import verify, PostgresNonceStore

app=FastAPI()


@app.get('/health')
async def health(): return {'status':'ok'}


@app.post('/meeting')
async def meeting(request: Request):
    raw=await request.body()
    public=load_pem_public_key(Path('/public/hub.pub').read_bytes())
    if not await verify(dict(request.headers), 'POST', '/meeting', raw, {'hub-v1':public}, PostgresNonceStore()):
        return JSONResponse(status_code=403,content={'code':'SIGNATURE_REJECTED'})
    if json.loads(raw) != {'meeting_id':'meeting-001'}:
        return JSONResponse(status_code=404,content={'code':'RESOURCE_NOT_FOUND'})
    return json.loads(Path('docs/implementation/examples/raw.meeting.json').read_text())
