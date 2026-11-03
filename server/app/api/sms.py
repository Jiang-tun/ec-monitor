from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.response import ok
from app.schemas.sms import SmsOrderCreate
from app.service import sms as sms_service

router = APIRouter(tags=["sms"])


@router.get("/api/sms-providers", response_model=None)
def list_providers(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
    enabled_only: bool = Query(default=False),
):
    """接码平台列表。"""
    rows = sms_service.list_providers(db, enabled_only=enabled_only)
    return ok(
        [
            {
                "id": p.id,
                "code": p.code,
                "name": p.name,
                "api_base": p.api_base,
                "enabled": p.enabled,
            }
            for p in rows
        ]
    )


@router.get("/api/sms-orders", response_model=None)
def list_orders(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    provider_id: Optional[int] = Query(default=None),
    platform_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
):
    """接码订单列表。"""
    items, total = sms_service.list_orders(
        db=db,
        page=page,
        page_size=page_size,
        provider_id=provider_id,
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


@router.post("/api/sms-orders", response_model=None)
def acquire_number(
    data: SmsOrderCreate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """获取手机号（无需选择接码平台，默认使用 SMSNam/Telegram）。"""
    order = sms_service.acquire_number(db=db, data=data, created_by=user.username)
    return ok(order.model_dump())


@router.get("/api/sms-orders/{order_id}", response_model=None)
def get_order(
    order_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
):
    """接码订单详情。"""
    return ok(sms_service.get_order(db=db, order_id=order_id).model_dump())


@router.post("/api/sms-orders/{order_id}/code", response_model=None)
def fetch_code(
    order_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """向接码平台获取验证码（未收到时返回原状态，前端可轮询）。"""
    return ok(sms_service.fetch_code(db=db, order_id=order_id).model_dump())


@router.post("/api/sms-orders/{order_id}/login", response_model=None)
def submit_login(
    order_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """用手机号+验证码创建目标平台登录会话（投递给采集节点）。"""
    return ok(sms_service.submit_login(db=db, order_id=order_id, created_by=user.username))


@router.post("/api/sms-orders/{order_id}/cancel", response_model=None)
def cancel_order(
    order_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """取消接码订单。"""
    return ok(sms_service.cancel_order(db=db, order_id=order_id).model_dump())
