"""Authorized receipt lookup: ready_to_send never means confirmed received."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.auth import denied, require_scope
from app.database import get_db
from app.models.schemas import DeliveryReceipt, FailureRecord

router = APIRouter(prefix='/api/v2/receipts', tags=['Delivery receipts'])


@router.get('/{request_id}')
async def get_receipt(request_id: str, actor=Depends(require_scope('audit')), db: AsyncSession = Depends(get_db)):
    query = select(DeliveryReceipt).where(DeliveryReceipt.request_id == request_id)
    if 'admin' not in actor['scopes']:
        query = query.where(DeliveryReceipt.source_agent == actor['sub'])
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        failure = await db.get(FailureRecord, request_id)
        if failure and (failure.source_agent == actor['sub'] or 'admin' in actor['scopes']):
            return {'request_id': request_id, 'status': 'failed', 'code': failure.code,
                    'created_at': failure.created_at, 'diagnostics': failure.diagnostics}
        raise denied('RECEIPT_NOT_FOUND', 404)
    return {key: getattr(row, key) for key in ('request_id', 'contract_id', 'contract_version',
                                              'contract_digest', 'view_id', 'policy_revision', 'profile_revision',
                                              'completed_processors', 'status', 'created_at')} | {
        'validation': {'source': 'passed', 'output': 'passed', 'obligations': 'passed'}}
