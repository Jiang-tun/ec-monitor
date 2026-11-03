from typing import List, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.response import ok
from app.schemas.item import (
    BatchIdsIn,
    BatchMonitorIn,
    MonitorItemCreate,
    MonitorItemUpdate,
    MonitorSwitch,
    SkuToggleIn,
)
from app.service import item as item_service

router = APIRouter(prefix="/api/items", tags=["items"])
platform_router = APIRouter(prefix="/api/platforms", tags=["platforms"])


# ==================== 平台字典 ====================
@platform_router.get("")
def list_platforms(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
):
    """平台字典（下拉用）。"""
    rows = item_service.list_platforms_service(db)
    return ok([r.model_dump() for r in rows])


# ==================== 导入（静态路径需在动态路径前）====================
@router.get("/import/template")
def download_import_template(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
):
    """下载 Excel 导入模板。"""
    content = item_service.build_import_template()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=item_import_template.xlsx"
        },
    )


@router.post("/import")
def import_items(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
    file: UploadFile = File(...),
):
    """Excel 批量导入监控商品。"""
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        from app.core.exceptions import PARAM_INVALID, BizError

        raise BizError(PARAM_INVALID, "仅支持 .xlsx 文件")
    content = file.file.read()
    if len(content) > 10 * 1024 * 1024:
        from app.core.exceptions import PARAM_INVALID, BizError

        raise BizError(PARAM_INVALID, "文件不能超过 10MB")
    result = item_service.import_items_service(db, content)
    return ok(result.model_dump())


# ==================== 列表 / 新增 ====================
@router.get("")
def list_items(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    platform_id: Optional[int] = Query(default=None),
    shop_id: Optional[int] = Query(default=None),
    monitor_status: Optional[int] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
):
    """商品分页列表（权限：item:read）。"""
    items, total = item_service.list_items_service(
        db=db,
        page=page,
        page_size=page_size,
        platform_id=platform_id,
        shop_id=shop_id,
        monitor_status=monitor_status,
        keyword=keyword,
    )
    return ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("")
def create_item(
    data: MonitorItemCreate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """新增监控商品（权限：item:write）。"""
    item = item_service.create_item_service(db=db, data=data)
    return ok(item.model_dump())


# ==================== 批量操作（需在 /{item_id} 之前注册） ====================
@router.post("/batch/crawl")
def batch_crawl(
    data: BatchIdsIn,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """批量手动触发采集（权限：item:write）。"""
    result = item_service.batch_trigger_crawl_service(db=db, item_ids=data.item_ids)
    return ok({"triggered": True, **result})


@router.put("/batch/monitor")
def batch_monitor(
    data: BatchMonitorIn,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """批量切换监控状态，如批量暂停/启用（权限：item:write）。"""
    result = item_service.batch_switch_monitor_service(
        db=db, item_ids=data.item_ids, monitor_status=data.monitor_status
    )
    return ok(result)


# ==================== 详情 / 修改 / 删除 ====================
@router.get("/{item_id}")
def get_item(
    item_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
):
    """商品详情，含平台名称与 SKU 列表（权限：item:read）。"""
    detail = item_service.get_item_detail_service(db=db, item_id=item_id)
    return ok(detail.model_dump())


@router.put("/{item_id}")
def update_item(
    item_id: int,
    data: MonitorItemUpdate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """修改商品（权限：item:write）。"""
    item = item_service.update_item_service(db=db, item_id=item_id, data=data)
    return ok(item.model_dump())


@router.delete("/{item_id}")
def delete_item(
    item_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """删除商品（软删，权限：item:write）。"""
    item_service.delete_item_service(db=db, item_id=item_id)
    return ok({"deleted": True})


# ==================== 监控开关 ====================
@router.put("/{item_id}/monitor")
def switch_monitor(
    item_id: int,
    data: MonitorSwitch,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """更新监控状态（0暂停 1监控中 2疑似下架 3已下架 4待激活）。"""
    item = item_service.switch_monitor_service(db=db, item_id=item_id, data=data)
    return ok(item.model_dump())


# ==================== 手动采集 ====================
@router.post("/{item_id}/crawl")
def trigger_crawl(
    item_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """手动触发一次采集（投递到 scrapy-redis 队列，权限：item:write）。"""
    result = item_service.trigger_crawl_service(db=db, item_id=item_id)
    return ok({"triggered": True, "item_id": item_id, **result})


# ==================== SKU ====================
@router.get("/{item_id}/skus")
def get_item_skus(
    item_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
):
    """商品 SKU 列表（权限：item:read）。"""
    skus = item_service.get_item_skus_service(db=db, item_id=item_id)
    return ok({"skus": [s.model_dump() for s in skus]})


@router.put("/{item_id}/skus")
def toggle_item_skus(
    item_id: int,
    data: SkuToggleIn,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """批量启用/禁用 SKU 监控。sku_ids 为空表示全部。"""
    result = item_service.toggle_skus_service(db=db, item_id=item_id, data=data)
    return ok(result)


# ==================== 价格历史 ====================
@router.get("/{item_id}/price-history")
def get_price_history(
    item_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
    sku_id: Optional[str] = Query(default=None),
    start: Optional[str] = Query(default=None, description="yyyy-MM-dd HH:mm:ss"),
    end: Optional[str] = Query(default=None, description="yyyy-MM-dd HH:mm:ss"),
    granularity: str = Query(default="raw", pattern="^(raw|hour|day)$"),
):
    """价格历史曲线（默认近 7 天）。"""
    data = item_service.price_history_service(
        db=db,
        item_id=item_id,
        sku_id=sku_id,
        start=start,
        end=end,
        granularity=granularity,
    )
    return ok(data.model_dump())


# ==================== 变更记录 ====================
@router.get("/{item_id}/changes")
def get_item_changes(
    item_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
    sku_id: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    """字段级变更记录分页。"""
    rows, total = item_service.changes_service(
        db=db, item_id=item_id, sku_id=sku_id, page=page, page_size=page_size
    )
    return ok(
        {
            "items": [r.model_dump() for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )
