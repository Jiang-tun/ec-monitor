from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
ALGORITHM = "HS256"
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


def hash_password(plain: str) -> str:
    """用 argon2 将明文密码哈希化。"""
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文与哈希是否匹配。"""
    try:
        return _hasher.verify(hashed, plain)
    except VerifyMismatchError:
        return False


def create_token(
    subject: str,
    token_type: str = TOKEN_TYPE_ACCESS,
    uid: Optional[int] = None,
    roles: Optional[list[str]] = None,
    perms: Optional[list[str]] = None,
    expires_min: Optional[int] = None,
) -> str:
    """核心函数：根据类型创建 access 或 refresh token。
    - token_type: "access" -> 2h 过期；"refresh" -> 7d 过期
    - uid: 用户 ID (整数)
    - roles: 角色码列表，如 ["admin"] 或 ["operator"]
    - perms: 权限点列表，如 ["item:write", "alert:read"]
    - expires_min: 仅对 access token 有效，未传则用设计里的 720 分钟
    """
    settings = get_settings()
    if token_type == TOKEN_TYPE_REFRESH:
        expire = datetime.now(timezone.utc) + timedelta(days=7)
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=expires_min or settings.access_token_expire_min
        )
    payload: dict[str, Any] = {
        "sub": subject,
        "typ": token_type,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    if uid is not None:
        payload["uid"] = uid
    if roles is not None:
        payload["roles"] = roles
    if perms is not None:
        payload["perms"] = perms
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(
    subject: str,
    uid: Optional[int] = None,
    roles: Optional[list[str]] = None,
    perms: Optional[list[str]] = None,
    expires_min: Optional[int] = None,
) -> str:
    return create_token(subject, TOKEN_TYPE_ACCESS, uid, roles, perms, expires_min)


def create_refresh_token(subject: str, uid: Optional[int] = None) -> str:
    return create_token(subject, TOKEN_TYPE_REFRESH, uid=uid)


def decode_token(token: str, expected_type: str = TOKEN_TYPE_ACCESS) -> dict[str, Any]:
    """解码令牌并校验其类型；若类型不匹配/过期/非法，抛出异常（由上层映射为 3004/3001）。"""
    settings = get_settings()
    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    if payload.get("typ", TOKEN_TYPE_ACCESS) != expected_type:
        raise jwt.InvalidTokenError(f"token type mismatch: {payload.get('typ')}")
    return payload


# 兼容旧调用接口
def decode_access_token(token: str) -> dict[str, Any]:
    return decode_token(token, TOKEN_TYPE_ACCESS)