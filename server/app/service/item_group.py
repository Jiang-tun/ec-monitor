from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.dao import item_group as item_group_dao
from app.schemas.item_group import (
    ItemGroupCreate,
    ItemGroupUpdate,
    ItemGroupRelCreate,
)


def list_item_groups_service(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
    status: Optional[int] = None,
):
    rows, total = item_group_dao.list_item_groups(
        db=db, page=page, page_size=page_size, keyword=keyword, status=status
    )
    return rows, total


def create_item_group_service(db: Session, data: ItemGroupCreate):
    return item_group_dao.create_item_group(db, data.model_dump())


def get_item_group_service(db: Session, group_id: int):
    group = item_group_dao.get_item_group(db, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品组不存在")
    return group


def update_item_group_service(db: Session, group_id: int, data: ItemGroupUpdate):
    update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    group = item_group_dao.update_item_group(db, group_id, update_data)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品组不存在")
    return group


def delete_item_group_service(db: Session, group_id: int):
    ok = item_group_dao.delete_item_group(db, group_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品组不存在")
    return {"deleted": True}


def list_group_items_service(db: Session, group_id: int):
    group = item_group_dao.get_item_group(db, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品组不存在")
    rels = item_group_dao.list_group_items(db, group_id)
    return rels


def add_item_to_group_service(db: Session, group_id: int, data: ItemGroupRelCreate):
    if data.group_id != group_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="group_id 不一致")
    return item_group_dao.add_item_to_group(db, data.model_dump())


def remove_item_from_group_service(db: Session, group_id: int, item_id: int):
    ok = item_group_dao.remove_item_from_group(db, group_id, item_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="关联不存在")
    return {"removed": True}


def set_base_item_service(db: Session, group_id: int, item_id: int):
    ok = item_group_dao.set_base_item(db, group_id, item_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="关联不存在")
    return {"base_item_id": item_id}


def item_group_compare_service(db: Session, group_id: int):
    """组内商品比价（简化：返回组内各商品最新快照价格）。"""
    from app.db.models import MonitorItem, PriceSnapshot, Platform

    group = item_group_dao.get_item_group(db, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品组不存在")

    rels = item_group_dao.list_group_items(db, group_id)
    items_out = []
    for rel in rels:
        item = (
            db.query(MonitorItem)
            .filter(MonitorItem.id == rel.item_id, MonitorItem.is_deleted == 0)
            .first()
        )
        if not item:
            continue
        latest = (
            db.query(PriceSnapshot)
            .filter(PriceSnapshot.item_id == item.id)
            .order_by(PriceSnapshot.snapshot_time.desc(), PriceSnapshot.id.desc())
            .first()
        )
        platform = (
            db.query(Platform)
            .filter(Platform.id == item.platform_id, Platform.is_deleted == 0)
            .first()
        )
        items_out.append(
            {
                "item_id": item.id,
                "platform_item_id": item.item_id,
                "platform_name": platform.name if platform else None,
                "platform_code": platform.code if platform else None,
                "title": item.title,
                "url": item.url,
                "is_base": rel.is_base == 1,
                "latest_price": float(latest.price) if latest and latest.price is not None else None,
                "latest_stock": latest.stock if latest else None,
                "snapshot_time": latest.snapshot_time.isoformat() if latest else None,
            }
        )

    return {
        "group_id": group.id,
        "group_name": group.group_name,
        "items": items_out,
    }
