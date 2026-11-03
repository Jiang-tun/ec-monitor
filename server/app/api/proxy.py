from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.response import ok
from app.schemas.proxy import (
    ProxyBatchIn,
    ProxyCreate,
    ProxyTestRequest,
    ProxyUpdate,
)
from app.service import proxy as proxy_service

router = APIRouter(prefix="/api/proxies", tags=["proxies"])


@router.get("", response_model=None)
def list_proxies(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("proxy:read")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    bind_site_group: Optional[str] = Query(default=None),
    available: Optional[bool] = Query(default=None),
    protocol: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
):
    """代理池列表。"""
    items, total = proxy_service.list_proxies_service(
        db=db,
        page=page,
        page_size=page_size,
        bind_site_group=bind_site_group,
        available=available,
        protocol=protocol,
        keyword=keyword,
    )
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@router.post("", response_model=None)
def create_proxy(
    data: ProxyCreate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("proxy:write")),
):
    """新增单个代理。"""
    proxy = proxy_service.create_proxy_service(db=db, data=data)
    return ok(proxy.model_dump())


@router.post("/batch", response_model=None)
def batch_create_proxies(
    data: ProxyBatchIn,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("proxy:write")),
):
    """批量录入代理。

    每行一条，支持：
      ip:port
      ip:port:username:password
      protocol://ip:port
      protocol://username:password@ip:port
    以 # 或 // 开头的行为注释。
    """
    result = proxy_service.batch_create_service(db=db, data=data)
    return ok(result)


@router.get("/active", response_model=None)
def get_active_proxy(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("proxy:read")),
):
    """当前用于采集(Playwright)的代理（全局唯一）。"""
    return ok(proxy_service.get_active_proxy_service(db=db))


@router.post("/clear-active", response_model=None)
def clear_active_proxy(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("proxy:write")),
):
    """取消当前启用代理（不再使用代理采集）。"""
    return ok(proxy_service.deactivate_proxy_service(db=db))


@router.get("/stats", response_model=None)
def proxy_stats(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("proxy:read")),
):
    """代理池统计。"""
    return ok(proxy_service.get_proxy_stats_service(db=db).model_dump())


@router.get("/{proxy_id}", response_model=None)
def get_proxy(
    proxy_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("proxy:read")),
):
    """代理详情。"""
    return ok(proxy_service.get_proxy_service(db=db, proxy_id=proxy_id).model_dump())


@router.put("/{proxy_id}", response_model=None)
def update_proxy(
    proxy_id: int,
    data: ProxyUpdate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("proxy:write")),
):
    """更新代理。"""
    return ok(
        proxy_service.update_proxy_service(db=db, proxy_id=proxy_id, data=data).model_dump()
    )


@router.delete("/{proxy_id}", response_model=None)
def delete_proxy(
    proxy_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("proxy:write")),
):
    """删除代理（软删除）。"""
    proxy_service.delete_proxy_service(db=db, proxy_id=proxy_id)
    return ok({"deleted": True})


@router.put("/{proxy_id}/toggle", response_model=None)
def toggle_proxy(
    proxy_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("proxy:write")),
    enabled: bool = Query(default=False),
):
    """启用/禁用代理可用性。"""
    proxy = proxy_service.toggle_proxy_service(db=db, proxy_id=proxy_id, enabled=enabled)
    return ok({"id": proxy.id, "available": proxy.available})


@router.put("/{proxy_id}/activate", response_model=None)
def activate_proxy(
    proxy_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("proxy:write")),
):
    """选择使用此代理（全局唯一，自动取消其他代理）。"""
    proxy = proxy_service.activate_proxy_service(db=db, proxy_id=proxy_id)
    return ok(proxy.model_dump())


@router.post("/{proxy_id}/test", response_model=None)
def test_proxy(
    proxy_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("proxy:write")),
    test_url: str = Query(default="http://example.com"),
    timeout: int = Query(default=10, ge=1, le=60),
):
    """测试代理连通性（TCP 连接）。"""
    result = proxy_service.test_proxy_service(
        db, ProxyTestRequest(proxy_id=proxy_id, test_url=test_url, timeout=timeout)
    )
    return ok(result.model_dump())
