from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.response import ok
from app.schemas.platform_login import PlatformLoginCreate, PlatformLoginSubmitCode
from app.service import platform_login as login_service

router = APIRouter(prefix="/api/platform-logins", tags=["platform-logins"])


@router.get("", response_model=None)
def list_logins(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    platform_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
):
    """平台登录会话列表。"""
    items, total = login_service.list_logins(
        db=db,
        page=page,
        page_size=page_size,
        platform_id=platform_id,
        status=status,
    )
    return ok(
        {
            "items": [i.model_dump() for i in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("", response_model=None)
def create_login(
    data: PlatformLoginCreate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """发起手机号验证码登录（发送验证码任务入队）。"""
    login = login_service.create_login(db=db, data=data, created_by=user.username)
    return ok(login.model_dump())


@router.get("/{login_id}", response_model=None)
def get_login(
    login_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
):
    """登录会话详情（前端轮询状态）。"""
    return ok(login_service.get_login(db=db, login_id=login_id).model_dump())


@router.post("/{login_id}/code", response_model=None)
def submit_code(
    login_id: int,
    data: PlatformLoginSubmitCode,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """提交短信验证码（验证任务入队）。"""
    login = login_service.submit_code(db=db, login_id=login_id, code=data.code)
    return ok(login.model_dump())


@router.post("/{login_id}/cancel", response_model=None)
def cancel_login(
    login_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """取消登录会话。"""
    return ok(login_service.cancel_login(db=db, login_id=login_id).model_dump())
