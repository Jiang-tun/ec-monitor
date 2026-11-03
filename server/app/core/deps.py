from typing import Annotated, Callable

import jwt as pyjwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import (
    FORBIDDEN,
    PARAM_INVALID,
    TOKEN_EXPIRED,
    UNAUTHORIZED,
    BizError,
)
from app.core.security import TOKEN_TYPE_ACCESS, decode_token
from app.db.models import SysRole, SysUser, SysUserRole
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)


def load_user_roles_perms(db: Session, user: SysUser) -> tuple[list[str], list[str]]:
    """从数据库查询用户的角色码列表和权限点列表。"""
    rows = (
        db.query(SysRole)
        .join(SysUserRole, SysUserRole.role_id == SysRole.id)
        .filter(SysUserRole.user_id == user.id)
        .all()
    )
    roles: list[str] = [r.role_code for r in rows]
    perms: list[str] = []
    for r in rows:
        for p in r.permissions or []:
            if p not in perms:
                perms.append(p)
    return roles, perms


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> SysUser:
    """从 HTTP Bearer 令牌中获取当前用户。
    - 无凭证 -> 3001 未登录
    - 过期 -> 3004 Token 过期
    - 无效 -> 3001 无效凭证
    - 用户不存在/已停用 -> 3001
    """
    if credentials is None:
        raise BizError(UNAUTHORIZED, "未登录")
    try:
        payload = decode_token(credentials.credentials, TOKEN_TYPE_ACCESS)
    except pyjwt.ExpiredSignatureError:
        raise BizError(TOKEN_EXPIRED, "登录已过期，请重新登录")
    except pyjwt.InvalidTokenError:
        raise BizError(UNAUTHORIZED, "无效凭证")

    username = payload.get("sub")
    user = db.query(SysUser).filter(SysUser.username == username).first()
    if not user or user.status != 1:
        raise BizError(UNAUTHORIZED, "用户不存在或已停用")
    return user


def require_perm(perm: str) -> Callable:
    """权限点依赖工厂。
    用法：`Depends(require_perm("item:write"))`
    权限检查规则：
    - 拥有 `admin` 角色的用户隐含所有权限。
    - 否则检查当前用户的 perms 列表是否包含目标 perm。
    - 不满足则返回 3003 无权限。
    """
    def checker(
        user: Annotated[SysUser, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> SysUser:
        roles, perms = load_user_roles_perms(db, user)
        if "admin" not in roles and perm not in perms:
            raise BizError(FORBIDDEN, f"无权限：需要 {perm}")
        return user

    return checker


CurrentUser = Annotated[SysUser, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]