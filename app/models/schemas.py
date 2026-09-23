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
        default=list, server_default='[]',
    )
    roles = Column(JSON, nullable=False, default=list, server_default="[]")
    authorization_revision = Column(Integer, nullable=False, default=1, server_default="1")
    credential_revision = Column(Integer, nullable=False, default=1, server_default="1")
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


class AccessGrant(Base):
    __tablename__ = 'access_grants'
    grant_id = Column(String(64), primary_key=True)
    agent_id = Column(String(255), nullable=False, index=True)
    contract_id = Column(String(64), nullable=False)
    view_id = Column(String(64), nullable=False)
    allowed_meeting_ids = Column(JSON, nullable=False, default=list)
    active = Column(Boolean, nullable=False, default=True)
    revision = Column(Integer, nullable=False, default=1)


class PublicResource(Base):
    __tablename__ = 'public_resources'
    contract_id = Column(String(64), primary_key=True)
    contract_version = Column(String(50), primary_key=True)
    owner_agent_id = Column(String(255), nullable=False)
    public = Column(Boolean, nullable=False, default=False)


class DeliveryReceipt(Base):
    __tablename__ = 'delivery_receipts'
    request_id = Column(String(64), primary_key=True)
    source_agent = Column(String(255), nullable=False, index=True)
    target_agent = Column(String(255), nullable=False)
    contract_id = Column(String(64), nullable=False)
    contract_version = Column(String(50), nullable=False)
    contract_digest = Column(String(64), nullable=False)
    view_id = Column(String(64), nullable=False)
    meeting_id = Column(String(64), nullable=False)
    policy_revision = Column(String(64), nullable=False)
    profile_revision = Column(String(64), nullable=False)
    completed_processors = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default='ready_to_send')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class OutboxEvent(Base):
    __tablename__ = 'outbox_events'
    event_id = Column(String(64), primary_key=True)
    receipt_id = Column(String(64), nullable=False, unique=True)
    processed = Column(Boolean, nullable=False, default=False)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt = Column(DateTime, nullable=False, default=datetime.utcnow)


class DeliveryAudit(Base):
    __tablename__ = 'delivery_audit'
    event_id = Column(String(64), primary_key=True)
    receipt_id = Column(String(64), nullable=False, unique=True)
    indexed_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ContractVersion(Base):
    __tablename__ = 'contract_versions'
    contract_id = Column(String(64), primary_key=True)
    contract_version = Column(String(50), primary_key=True)
    owner_agent_id = Column(String(255), nullable=False)
    provider_agent_id = Column(String(255), nullable=False)
    document = Column(JSON, nullable=False)
    digest = Column(String(64), nullable=False)
    state = Column(String(16), nullable=False, default='draft')
    is_default = Column(Boolean, nullable=False, default=False)


class ContractResource(Base):
    __tablename__ = 'contract_resources'
    contract_id = Column(String(64), primary_key=True)
    owner_agent_id = Column(String(255), nullable=False)
    provider_agent_id = Column(String(255), nullable=False)


class FailureRecord(Base):
    __tablename__ = 'failure_records'
    request_id = Column(String(64), primary_key=True)
    source_agent = Column(String(255), nullable=False)
    code = Column(String(64), nullable=False)
    diagnostics = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class UpstreamNonce(Base):
    __tablename__ = 'upstream_nonces'
    nonce = Column(String(256), primary_key=True)
    expires_at = Column(DateTime, nullable=False)


class PublicationCheck(Base):
    __tablename__ = 'publication_checks'
    contract_id = Column(String(64), primary_key=True)
    contract_version = Column(String(50), primary_key=True)
    bundle = Column(JSON, nullable=False)
    report = Column(JSON, nullable=False)
    acknowledged_digest = Column(String(64), nullable=True)
