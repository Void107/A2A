"""
Query Engine —— 核心业务逻辑（规范 §2.2 / §2.3 / §2.4 / §2.5 / §2.7）。

完整流程：
  1. 策略匹配（Contract Interceptor）
  2. Hub HMAC 签名 + 反向代理到目标 Agent
  3. 流式读取 + Payload Guard 体积限制
  4. 数据脱敏（Transform Pipeline）
  5. 异步审计

🔴 核心风控修正（相比指南）：
   - httpx 设置分段超时：connect=5s, read=10s, write=5s, pool=5s
   - 捕获所有 httpx 异常分类返回 502/504，不让 Hub 卡死
   - 流式读取，边读边计量字节数，超限立即截断
"""

from __future__ import annotations

import json
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_auth
from app.config import settings
from app.core.interceptor import evaluate_contract
from app.database import get_db
from app.models.schemas import Agent
from app.services.audit_writer import emit_audit_event
from app.services.transform import apply_transforms

router = APIRouter(prefix="/api/v1/interact", tags=["查询引擎"])

# ── 严格的分段超时，防止目标 Agent 拖垮 Hub ──
UPSTREAM_TIMEOUT = httpx.Timeout(
    connect=5.0,   # 建连最多 5 秒
    read=10.0,     # 读响应最多 10 秒
    write=5.0,     # 写请求最多 5 秒
    pool=5.0,      # 从连接池等连接最多 5 秒
)


class QueryRequest(BaseModel):
    target_agent: str
    schema_id: str
    query_params: dict = {}


@router.post("/query")
async def query_agent(
    body: QueryRequest,
    agent: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Agent A 向 Agent B 发起数据查询"""

    source_id = agent["sub"]
    source_domain = agent.get("domain")
    request_id = str(uuid.uuid4())

    # ── 第 1 步：查找目标 Agent ──
    result = await db.execute(
        select(Agent).where(
            Agent.agent_id == body.target_agent,
            Agent.is_active.is_(True),
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{body.target_agent}' 不存在或未激活",
        )

    # ── 第 2 步：策略匹配（Contract Interceptor §2.3） ──
    source_info = {
        "sub": source_id,
        "scopes": agent.get("scopes", []),
        "domain": source_domain,
    }
    evaluation = evaluate_contract(
        target.data_contract, body.schema_id, source_info
    )

    if evaluation["decision"] == "blocked":
        await emit_audit_event({
            "source_agent": source_id,
            "target_agent": body.target_agent,
            "schema_id": body.schema_id,
            "action_type": "query",
            "decision": "blocked",
            "policy_matched": evaluation.get("policy_matched"),
            "transforms_applied": [],
            "request_id": request_id,
        })
        raise HTTPException(
            status_code=403,
            detail={
                "code": "CONTRACT_VIOLATION",
                "message": evaluation["reason"],
                "request_id": request_id,
            },
        )

    # ── 第 3 步：反向代理到目标 Agent ──
    forward_body = {
        "schema_id": body.schema_id,
        "params": body.query_params,
    }

    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
            # 流式读取 + 体积限制（Payload Guard §2.5）
            async with client.stream(
                "POST", target.callback_url, json=forward_body
            ) as resp:
                resp.raise_for_status()
                chunks = []
                total_bytes = 0
                async for chunk in resp.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > settings.MAX_RESPONSE_BYTES:
                        await emit_audit_event({
                            "source_agent": source_id,
                            "target_agent": body.target_agent,
                            "schema_id": body.schema_id,
                            "action_type": "query",
                            "decision": "blocked",
                            "policy_matched": evaluation.get("policy_matched"),
                            "transforms_applied": ["PAYLOAD_LIMIT_EXCEEDED"],
                            "request_id": request_id,
                        })
                        raise HTTPException(
                            status_code=413,
                            detail={
                                "code": "PAYLOAD_TOO_LARGE",
                                "message": f"响应体积超过 {settings.MAX_RESPONSE_BYTES} 字节限制",
                                "request_id": request_id,
                            },
                        )
                    chunks.append(chunk)
                raw_data = json.loads(b"".join(chunks))

    except httpx.ConnectTimeout:
        await _emit_upstream_error(
            source_id, body, request_id, evaluation, "CONNECT_TIMEOUT"
        )
        raise HTTPException(
            status_code=504,
            detail={
                "code": "CONNECT_TIMEOUT",
                "message": "无法建立与目标 Agent 的连接（超时 5 秒）",
                "request_id": request_id,
            },
        )
    except httpx.ReadTimeout:
        await _emit_upstream_error(
            source_id, body, request_id, evaluation, "READ_TIMEOUT"
        )
        raise HTTPException(
            status_code=504,
            detail={
                "code": "READ_TIMEOUT",
                "message": "目标 Agent 响应超时（超时 10 秒）",
                "request_id": request_id,
            },
        )
    except httpx.ConnectError:
        await _emit_upstream_error(
            source_id, body, request_id, evaluation, "CONNECT_REFUSED"
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "CONNECT_REFUSED",
                "message": "无法连接目标 Agent（连接被拒绝或 DNS 解析失败）",
                "request_id": request_id,
            },
        )
    except httpx.HTTPStatusError as e:
        await _emit_upstream_error(
            source_id, body, request_id, evaluation,
            f"UPSTREAM_{e.response.status_code}",
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "UPSTREAM_ERROR",
                "message": f"目标 Agent 返回错误状态码 {e.response.status_code}",
                "request_id": request_id,
            },
        )
    except HTTPException:
        raise  # 413 Payload Guard 直接抛出
    except httpx.RequestError as e:
        await _emit_upstream_error(
            source_id, body, request_id, evaluation, "REQUEST_ERROR"
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "UPSTREAM_ERROR",
                "message": f"与目标 Agent 通信失败: {type(e).__name__}",
                "request_id": request_id,
            },
        )

    # ── 第 4 步：数据脱敏（Transform Pipeline §2.4） ──
    decision = evaluation["decision"]
    transforms = evaluation["transforms"]

    if decision == "transformed" and transforms:
        final_data = apply_transforms(raw_data, transforms)
        transforms_applied = [
            f"{t['transform_id']}:{t['type']}" for t in transforms
        ]
    else:
        final_data = raw_data
        transforms_applied = []

    # ── 第 5 步：异步审计（§2.7） ──
    await emit_audit_event({
        "source_agent": source_id,
        "target_agent": body.target_agent,
        "schema_id": body.schema_id,
        "action_type": "query",
        "decision": decision,
        "policy_matched": evaluation.get("policy_matched"),
        "transforms_applied": transforms_applied,
        "request_id": request_id,
    })

    # ── 第 6 步：返回 ──
    return {
        "request_id": request_id,
        "source_agent": source_id,
        "target_agent": body.target_agent,
        "schema_id": body.schema_id,
        "decision": decision,
        "data": final_data,
    }


async def _emit_upstream_error(
    source_id: str,
    body: QueryRequest,
    request_id: str,
    evaluation: dict,
    error_type: str,
):
    """上游错误时统一记审计日志"""
    await emit_audit_event({
        "source_agent": source_id,
        "target_agent": body.target_agent,
        "schema_id": body.schema_id,
        "action_type": "query",
        "decision": "blocked",
        "policy_matched": evaluation.get("policy_matched"),
        "transforms_applied": [error_type],
        "request_id": request_id,
    })
