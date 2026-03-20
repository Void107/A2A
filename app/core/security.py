"""
安全工具集 —— JWT / API Key / Hub HMAC 签名。

生产级要点：
1. bcrypt 的 cost factor 默认 12 轮，单次比对约 250ms。
   绝不能 O(N) 遍历所有 Agent 做 bcrypt 比对，必须先用 agent_id 做 O(1) 查询。
2. Hub→Agent HMAC 签名带时间戳，防重放窗口 300 秒。
3. JWT payload 里塞 domain 和 scopes，减少后续查库次数。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta

import bcrypt
import jwt

from app.config import settings


# ═══════════════════════════════════════════
#  Agent → Hub 认证（API Key + JWT）
# ═══════════════════════════════════════════

def generate_api_key() -> str:
    """生成 43 字符的 URL-safe 随机 API Key"""
    return secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    """bcrypt 单向哈希，存库用"""
    return bcrypt.hashpw(api_key.encode(), bcrypt.gensalt()).decode()


def verify_api_key(plain: str, hashed: str) -> bool:
    """比对明文 API Key 与库里的 bcrypt 哈希"""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_jwt(agent_id: str, scopes: list, domain: str | None = None) -> str:
    """
    签发短期 JWT。
    payload 里带 domain 和 scopes，后续鉴权不用再查库。
    """
    now = datetime.utcnow()
    payload = {
        "sub": agent_id,
        "iss": "a2a-contract-hub",
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
        "scopes": scopes,
    }
    if domain:
        payload["domain"] = domain
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    """
    解析并验证 JWT。
    过期 / 签名不匹配会抛 jwt.ExpiredSignatureError / jwt.InvalidTokenError。
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
    )


# ═══════════════════════════════════════════
#  Hub → Agent 签名（HMAC-SHA256，规范 §2.2）
# ═══════════════════════════════════════════

def generate_hub_secret() -> str:
    """生成 Hub 与目标 Agent 之间的共享密钥"""
    return secrets.token_urlsafe(32)


def sign_hub_request(body: dict, hub_secret: str) -> dict:
    """
    Hub 转发请求时，用目标 Agent 的共享密钥签名。
    返回需要附加到 HTTP Header 的字段。
    """
    body_bytes = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    sign_payload = f"{timestamp}.{body_bytes.decode()}".encode()
    signature = hmac.new(
        hub_secret.encode(), sign_payload, hashlib.sha256
    ).hexdigest()
    return {
        "X-Hub-Signature": f"sha256={signature}",
        "X-Hub-Timestamp": timestamp,
    }


def verify_hub_signature(
    headers: dict, body_bytes: bytes, hub_secret: str
) -> bool:
    """
    Agent 侧验证 Hub 签名的参考实现。
    Hub 自身不调这个函数，提供给 Agent 开发者参考。
    """
    timestamp = headers.get("X-Hub-Timestamp", "")
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False  # 防重放：超过 5 分钟拒绝
    except (ValueError, TypeError):
        return False

    sign_payload = f"{timestamp}.{body_bytes.decode()}".encode()
    expected = hmac.new(
        hub_secret.encode(), sign_payload, hashlib.sha256
    ).hexdigest()
    actual = headers.get("X-Hub-Signature", "").removeprefix("sha256=")
    return hmac.compare_digest(expected, actual)
