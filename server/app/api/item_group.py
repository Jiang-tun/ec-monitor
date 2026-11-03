from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.response import ok
from app.schemas.item_group import (
    ItemGroupCreate,
    ItemGroupOut,
    ItemGroupUpdate,
    ItemGroupRelCreate,
    ItemGroupRelOut,
    ItemCompareOut,
)
from app.service import item_group as item_group_service

router = APIRouter(prefix="/api/item-groups", tags=["item-groups"])


@router.get("")
def list_item_groups(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    keyword: Optional[str] = Query(default=None),
    status: Optional[int] = Query(default=None),
):
    """商品组列表（权限：item:read）。"""
    rows, total = item_group_service.list_item_groups_service(
        db=db, page=page, page_size=page_size, keyword=keyword, status=status
    )
    return ok(
        {
            "items": [r.__dict__ for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("")
def create_item_group(
    data: ItemGroupCreate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """创建商品组（权限：item:write）。"""
    group = item_group_service.create_item_group_service(db=db, data=data)
    return ok(group.__dict__)


@router.get("/{group_id}")
def get_item_group(
    group_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
):
    """商品组详情（权限：item:read）。"""
    group = item_group_service.get_item_group_service(db=db, group_id=group_id)
    return ok(group.__dict__)


@router.put("/{group_id}")
def update_item_group(
    group_id: int,
    data: ItemGroupUpdate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """更新商品组（权限：item:write）。"""
    group = item_group_service.update_item_group_service(db=db, group_id=group_id, data=data)
    return ok(group.__dict__)


@router.delete("/{group_id}")
def delete_item_group(
    group_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """删除商品组（软删，权限：item:write）。"""
    item_group_service.delete_item_group_service(db=db, group_id=group_id)
    return ok({"deleted": True})


@router.get("/{group_id}/items")
def list_group_items(
    group_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
):
    """组内商品列表（权限：item:read）。"""
    rels = item_group_service.list_group_items_service(db=db, group_id=group_id)
    return ok({"items": [r.__dict__ for r in rels]})


@router.post("/{group_id}/items")
def add_item_to_group(
    group_id: int,
    data: ItemGroupRelCreate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """将商品加入组（权限：item:write）。"""
    rel = item_group_service.add_item_to_group_service(db=db, group_id=group_id, data=data)
    return ok(rel.__dict__)


@router.delete("/{group_id}/items/{item_id}")
def remove_item_from_group(
    group_id: int,
    item_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """将商品移出组（权限：item:write）。"""
    item_group_service.remove_item_from_group_service(db=db, group_id=group_id, item_id=item_id)
    return ok({"removed": True})


@router.put("/{group_id}/items/{item_id}/base")
def set_base_item(
    group_id: int,
    item_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """设置组内基准商品（权限：item:write）。"""
    item_group_service.set_base_item_service(db=db, group_id=group_id, item_id=item_id)
    return ok({"base_item_id": item_id})


@router.get("/{group_id}/compare")
def item_group_compare(
    group_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
):
    """组内跨平台比价（权限：item:read）。"""
    data = item_group_service.item_group_compare_service(db=db, group_id=group_id)
    return ok(data)
