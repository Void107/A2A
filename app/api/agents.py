"""Legacy registration is closed; v2 administrators provision trusted identities."""
from fastapi import APIRouter, Depends
from app.api.auth import denied, require_scope

router = APIRouter(prefix='/api/v1/agents', tags=['Agent registry'])


@router.post('/register')
async def register_agent():
    raise denied('SELF_REGISTRATION_DISABLED', 403)


@router.get('/discover')
async def discover_agents(agent=Depends(require_scope('discover'))):
    # v2 view discovery requires an active contract and OPA (T09). Returning
    # everyone from the legacy registry would leak policy and owner information.
    raise denied('LEGACY_DISCOVERY_DISABLED', 410)
