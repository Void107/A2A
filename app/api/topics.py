"""
Broadcast Engine —— 基于 Redis Pub/Sub + SSE 的广播系统。

所有 Redis 操作都通过 get_redis() 获取全局连接池，
不自行创建连接，避免泄露。
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.auth import require_auth
from app.core.redis_pool import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/topics", tags=["广播系统"])


class PublishRequest(BaseModel):
    topic: str
    content: dict
    entity_type: Optional[str] = None


@router.post("/publish")
async def publish(body: PublishRequest, agent: dict = Depends(require_auth)):
    """向某个 Topic 发布广播消息"""

    message = json.dumps(
        {
            "source_agent": agent["sub"],
            "entity_type": body.entity_type,
            "content": body.content,
        },
        ensure_ascii=False,
    )

    redis = get_redis()
    receivers = await redis.publish(f"topic:{body.topic}", message)
    return {"status": "published", "topic": body.topic, "receivers": receivers}


@router.get("/subscribe")
async def subscribe(
    topic: str = Query(..., description="要订阅的 Topic 名称"),
    agent: dict = Depends(require_auth),
):
    """通过 SSE 长连接订阅某个 Topic 的实时消息"""

    async def event_generator():
        redis = get_redis()
        pubsub = redis.pubsub()
        channel = f"topic:{topic}"
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield {"event": "message", "data": message["data"]}
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return EventSourceResponse(event_generator())
