from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.deps import CurrentUser, DbSession, load_user_roles_perms
from app.core.exceptions import (
    FORBIDDEN,
    PARAM_INVALID,
    UNAUTHORIZED,
    BizError,
)
from app.core.response import ok
from app.core.security import (
    TOKEN_TYPE_REFRESH,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.models import SysUser
from app.schemas.common import ChangePasswordReq, LoginReq, RefreshReq

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _load_user_perms(db, user: SysUser) -> tuple[list[str], list[str]]:
    """封装一次查角色/权限，避免在每个路由里重复写。"""
    return load_user_roles_perms(db, user)


@router.post("/login", response_model=None)
def login(body: LoginReq, db: DbSession):
    """用户登录。返回 access_token (2h), refresh_token (7d), 用户信息。"""
    user = db.query(SysUser).filter(SysUser.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise BizError(UNAUTHORIZED, "用户名或密码错误")
    if user.status != 1:
        raise BizError(FORBIDDEN, "用户已停用")

    roles, perms = _load_user_perms(db, user)
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    settings = get_settings()
    return ok(
        {
            "access_token": create_access_token(
                subject=user.username, uid=user.id, roles=roles, perms=perms
            ),
            "refresh_token": create_refresh_token(subject=user.username, uid=user.id),
            "token_type": "bearer",
            "expires_in": settings.access_token_expire_min * 60,
            "user": {
                "id": user.id,
                "username": user.username,
                "nickname": user.nickname,
                "email": user.email,
                "roles": roles,
                "permissions": perms,
            },
        }
    )


@router.post("/refresh", response_model=None)
def refresh(body: RefreshReq, db: DbSession):
    """使用 refresh token 换取新的 access token。"""
    try:
        payload = decode_token(body.refresh_token, TOKEN_TYPE_REFRESH)
    except Exception:
        raise BizError(UNAUTHORIZED, "刷新令牌无效")
    user = db.query(SysUser).filter(SysUser.username == payload.get("sub")).first()
    if not user or user.status != 1:
        raise BizError(UNAUTHORIZED, "用户不存在或已停用")
    roles, perms = _load_user_perms(db, user)
    settings = get_settings()
    return ok(
        {
            "access_token": create_access_token(
                subject=user.username, uid=user.id, roles=roles, perms=perms
            ),
            "token_type": "bearer",
            "expires_in": settings.access_token_expire_min * 60,
        }
    )


@router.get("/me", response_model=None)
def me(user: CurrentUser, db: DbSession):
    """获取当前登录用户的详细信息（含角色与权限）。"""
    roles, perms = _load_user_perms(db, user)
    return ok(
        {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "email": user.email,
            "roles": roles,
            "permissions": perms,
            "last_login_at": (
                user.last_login_at.strftime("%Y-%m-%d %H:%M:%S")
                if user.last_login_at
                else None
            ),
        }
    )


@router.post("/change-password", response_model=None)
def change_password(body: ChangePasswordReq, user: CurrentUser, db: DbSession):
    """修改密码。需要验证旧密码。"""
    if not verify_password(body.old_password, user.password_hash):
        raise BizError(PARAM_INVALID, "原密码错误")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return ok({"changed": True})