"""
审计日志查询接口。

写入由 audit_writer.py 异步完成，这里只做读取。
支持按 agent_id / schema_id / action_type / decision 多条件过滤 + 分页。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_auth
from app.database import get_db
from app.models.schemas import AuditLog

router = APIRouter(prefix="/api/v1/audit", tags=["审计日志"])


@router.get("/logs")
async def get_logs(
    agent: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    agent_id: Optional[str] = Query(None, description="按 Agent ID 过滤（source 或 target）"),
    schema_id: Optional[str] = Query(None, description="按 schema_id 过滤"),
    action_type: Optional[str] = Query(None, description="query / publish / contract_update"),
    decision: Optional[str] = Query(None, description="allowed / blocked / transformed"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    """查询审计日志，支持多种过滤条件 + 分页"""

    query = select(AuditLog).order_by(AuditLog.timestamp.desc())
    count_query = select(func.count(AuditLog.id))

    # 按条件过滤
    if agent_id:
        condition = (AuditLog.source_agent == agent_id) | (
            AuditLog.target_agent == agent_id
        )
        query = query.where(condition)
        count_query = count_query.where(condition)
    if schema_id:
        query = query.where(AuditLog.schema_id == schema_id)
        count_query = count_query.where(AuditLog.schema_id == schema_id)
    if action_type:
        query = query.where(AuditLog.action_type == action_type)
        count_query = count_query.where(AuditLog.action_type == action_type)
    if decision:
        query = query.where(AuditLog.decision == decision)
        count_query = count_query.where(AuditLog.decision == decision)

    # 总数
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # 分页
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    logs = result.scalars().all()

    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "results": [
            {
                "id": str(log.id),
                "timestamp": log.timestamp.isoformat(),
                "source_agent": log.source_agent,
                "target_agent": log.target_agent,
                "schema_id": log.schema_id,
                "action_type": log.action_type,
                "decision": log.decision,
                "policy_matched": log.policy_matched,
                "transforms_applied": log.transforms_applied,
                "request_id": log.request_id,
            }
            for log in logs
        ],
    }
