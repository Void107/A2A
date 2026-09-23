"""Legacy query cannot bypass the v2 delivery core while it is being built."""
from fastapi import APIRouter, Depends
from app.api.auth import denied, require_scope

router = APIRouter(prefix='/api/v1/interact', tags=['Legacy query'])


@router.post('/query')
async def query_agent(agent=Depends(require_scope('query'))):
    raise denied('LEGACY_QUERY_DISABLED', 410)
