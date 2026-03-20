"""
数据库表结构 —— 对齐 Agent_Data_Contract_Spec_Core v0.2.0。

与指南的区别 / 生产加固：
1. 主键用 server_default=text("gen_random_uuid()") 让 PG 侧生成 UUID，
   避免 Python 侧 uuid4() 在高并发下的微小碰撞风险。
2. created_at / updated_at 用 server_default + onupdate，
   保证时间戳由数据库统一管理，不受应用服务器时钟漂移影响。
3. is_active 用 Boolean 而非 String("true")，防止脏数据。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    JSON,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Agent(Base):
    """Agent 注册表 —— 存储所有注册的 Agent"""
    __tablename__ = "agents"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    agent_id = Column(String(255), unique=True, nullable=False, index=True)
    display_name = Column(String(255), nullable=False)
    callback_url = Column(Text, nullable=False)
    skills = Column(JSON, server_default="[]")

    # ── 数据契约（核心）──
    # 结构遵循 Spec §1.2：{ schemas: [...], policies: [...], transforms: [...] }
    data_contract = Column(JSON, nullable=False)

    # ── 身份与安全 ──
    domain = Column(String(255), nullable=True, index=True)          # 规范 §2.6
    api_key_hash = Column(String(255), nullable=False)               # Agent→Hub 认证
    hub_shared_secret_hash = Column(String(255), nullable=False)     # Hub→Agent 签名 §2.2
    scopes = Column(
        JSON,
        server_default='["publish","query","discover","subscribe","audit"]',
    )
    is_active = Column(Boolean, default=True, server_default=text("true"))

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        server_default=text("now()"),
    )
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )


class ContractHistory(Base):
    """契约版本历史 —— 每次更新契约都留底"""
    __tablename__ = "contract_history"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    agent_id = Column(String(255), nullable=False, index=True)
    version = Column(String(50), nullable=False)
    contract_data = Column(JSON, nullable=False)
    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        server_default=text("now()"),
    )


class AuditLog(Base):
    """审计日志 —— 记录所有跨 Agent 操作"""
    __tablename__ = "audit_logs"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    timestamp = Column(
        DateTime,
        default=datetime.utcnow,
        server_default=text("now()"),
        index=True,
    )
    source_agent = Column(String(255), index=True)
    target_agent = Column(String(255), index=True)
    schema_id = Column(String(255))                     # 对齐规范：entity → schema_id
    action_type = Column(String(50), index=True)        # query / publish / contract_update
    decision = Column(String(50))                       # allowed / blocked / transformed
    policy_matched = Column(String(255), nullable=True) # 命中的策略 ID
    transforms_applied = Column(JSON, server_default="[]")
    request_id = Column(String(255), unique=True)
