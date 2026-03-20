"""
异步审计写入管道（规范 §2.7）。

Redis Stream 缓冲 → 后台协程批量写入 PostgreSQL。
即使 Redis 挂了也不影响业务——降级为本地日志。
"""

from __future__ import annotations

import asyncio
import json
import logging

from app.core.redis_pool import get_redis
from app.database import AsyncSessionLocal
from app.models.schemas import AuditLog

logger = logging.getLogger(__name__)

AUDIT_STREAM_KEY = "audit:stream"
BATCH_SIZE = 100
FLUSH_INTERVAL_SECONDS = 5


async def emit_audit_event(event: dict):
    """
    非阻塞地发送审计事件到 Redis Stream。
    调用方调完立即返回，不等写库。
    """
    try:
        redis = get_redis()
        await redis.xadd(
            AUDIT_STREAM_KEY,
            {"data": json.dumps(event, default=str)},
        )
    except Exception:
        # Redis 不可用时降级为本地日志，绝不阻断业务
        logger.warning(
            f"Audit fallback to local log: {json.dumps(event, default=str)}"
        )


async def audit_consumer_loop():
    """
    后台审计消费者 —— 从 Redis Stream 批量读取并写入 PostgreSQL。
    在 lifespan startup 中作为后台任务启动。
    """
    last_id = "0-0"
    batch = []

    while True:
        try:
            redis = get_redis()
            entries = await redis.xread(
                {AUDIT_STREAM_KEY: last_id},
                count=BATCH_SIZE,
                block=FLUSH_INTERVAL_SECONDS * 1000,
            )

            if entries:
                for _stream_name, messages in entries:
                    for msg_id, fields in messages:
                        batch.append(json.loads(fields["data"]))
                        last_id = msg_id

            if batch:
                await _flush_batch(batch)
                # 清理已处理的消息
                if entries:
                    msg_ids = [
                        msg_id
                        for _, messages in entries
                        for msg_id, _ in messages
                    ]
                    if msg_ids:
                        await redis.xdel(AUDIT_STREAM_KEY, *msg_ids)
                batch.clear()

        except Exception as e:
            logger.error(f"Audit consumer error: {e}")
            await asyncio.sleep(2)


async def _flush_batch(batch: list):
    """批量写入审计日志到 PostgreSQL"""
    try:
        async with AsyncSessionLocal() as session:
            for event in batch:
                log = AuditLog(
                    source_agent=event.get("source_agent"),
                    target_agent=event.get("target_agent"),
                    schema_id=event.get("schema_id"),
                    action_type=event.get("action_type"),
                    decision=event.get("decision"),
                    policy_matched=event.get("policy_matched"),
                    transforms_applied=event.get("transforms_applied", []),
                    request_id=event.get("request_id"),
                )
                session.add(log)
            await session.commit()
            logger.info(f"Audit: flushed {len(batch)} events to database")
    except Exception as e:
        logger.error(f"Audit flush failed: {e}")
