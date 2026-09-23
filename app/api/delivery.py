"""HTTP envelope only; all transport paths call services.delivery.deliver."""
import uuid
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.auth import require_scope
from app.database import get_db
from app.services.receipts import record_failure
from app.services.delivery import deliver, DeliveryRequest
from fastapi.responses import JSONResponse

router = APIRouter(prefix='/api/v2', tags=['Data delivery'])
STATUS = {'ACCESS_DENIED': 403, 'CONTRACT_VERSION_UNAVAILABLE': 409, 'CONTRACT_INVALID': 422,
          'UPSTREAM_TIMEOUT': 504, 'DELIVERY_TIMEOUT': 504, 'PAYLOAD_TOO_LARGE': 413,
          'UPSTREAM_INVALID_JSON': 502, 'UPSTREAM_SCHEMA_MISMATCH': 502,
          'UPSTREAM_RESOURCE_MISMATCH': 502, 'OUTPUT_CONTRACT_VIOLATION': 502,
          'CONCURRENCY_LIMIT': 429}


@router.post('/query')
async def query(body: DeliveryRequest, request: Request, actor=Depends(require_scope('query')),
                db: AsyncSession = Depends(get_db)):
    try:
        return await deliver(body, actor, db, request.app.state)
    except Exception as error:
        code = getattr(error, 'code', 'PROCESSING_UNAVAILABLE')
        request_id = getattr(error, 'request_id', None) or uuid.uuid4().hex
        recorded = await record_failure(request_id, actor['sub'], code, getattr(error, 'diagnostics', None))
        return JSONResponse(status_code=STATUS.get(code, 503), content={'code': code, 'request_id': request_id, 'diagnostic_recorded': recorded})
