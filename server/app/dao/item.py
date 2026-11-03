from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Query, Session

from app.db.models import (
    ChangeRecord,
    MonitorItem,
    MonitorSku,
    Platform,
    PriceSnapshot,
)


# ==================== 平台 ====================
def list_platforms(db: Session, only_enabled: bool = True) -> List[Platform]:
    q = db.query(Platform).filter(Platform.is_deleted == 0)
    if only_enabled:
        q = q.filter(Platform.status == 1)
    return q.order_by(Platform.sort.asc(), Platform.id.asc()).all()


def get_platform(db: Session, platform_id: int) -> Optional[Platform]:
    return (
        db.query(Platform)
        .filter(Platform.id == platform_id, Platform.is_deleted == 0)
        .first()
    )


def get_platform_by_code(db: Session, code: str) -> Optional[Platform]:
    return (
        db.query(Platform)
        .filter(Platform.code == code, Platform.is_deleted == 0)
        .first()
    )


# ==================== 商品 ====================
def get_item(db: Session, item_id: int) -> Optional[MonitorItem]:
    """根据主键获取监控商品（未删除）。"""
    return (
        db.query(MonitorItem)
        .filter(MonitorItem.id == item_id, MonitorItem.is_deleted == 0)
        .first()
    )


def get_item_by_platform_item(
    db: Session, platform_id: int, item_id: str
) -> Optional[MonitorItem]:
    """根据平台+商品ID获取监控商品（未删除）。"""
    return (
        db.query(MonitorItem)
        .filter(
            MonitorItem.platform_id == platform_id,
            MonitorItem.item_id == item_id,
            MonitorItem.is_deleted == 0,
        )
        .first()
    )


def get_items(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    platform_id: Optional[int] = None,
    shop_id: Optional[int] = None,
    monitor_status: Optional[int] = None,
    keyword: Optional[str] = None,
) -> Tuple[List[MonitorItem], int]:
    """分页查询监控商品，返回 (列表, 总数)。"""
    q: Query = db.query(MonitorItem).filter(MonitorItem.is_deleted == 0)
    if platform_id is not None:
        q = q.filter(MonitorItem.platform_id == platform_id)
    if shop_id is not None:
        q = q.filter(MonitorItem.shop_id == shop_id)
    if monitor_status is not None:
        q = q.filter(MonitorItem.monitor_status == monitor_status)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            or_(
                MonitorItem.item_id.ilike(like),
                MonitorItem.title.ilike(like),
                MonitorItem.url.ilike(like),
            )
        )
    total = q.count()
    items = (
        q.order_by(MonitorItem.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def create_item(db: Session, **kwargs) -> MonitorItem:
    obj = MonitorItem(**kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def create_items_bulk(db: Session, rows: List[dict]) -> List[MonitorItem]:
    objs = [MonitorItem(**r) for r in rows]
    db.add_all(objs)
    db.commit()
    for o in objs:
        db.refresh(o)
    return objs


def update_item(db: Session, item: MonitorItem, **kwargs) -> MonitorItem:
    for k, v in kwargs.items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, item: MonitorItem) -> None:
    item.is_deleted = 1
    db.commit()


def switch_monitor(db: Session, item: MonitorItem, status: int) -> MonitorItem:
    item.monitor_status = status
    if status == 1:
        # 启动监控后尽快按频率进入调度
        item.next_run_time = datetime.now()
    db.commit()
    db.refresh(item)
    return item


# ==================== SKU ====================
def get_skus(db: Session, item_id: int, only_enabled: bool = False) -> List[MonitorSku]:
    q = db.query(MonitorSku).filter(
        MonitorSku.item_id == item_id, MonitorSku.is_deleted == 0
    )
    if only_enabled:
        q = q.filter(MonitorSku.monitor_enabled == 1)
    return q.order_by(MonitorSku.id.asc()).all()


def get_sku(db: Session, item_id: int, sku_id: str) -> Optional[MonitorSku]:
    return (
        db.query(MonitorSku)
        .filter(
            MonitorSku.item_id == item_id,
            MonitorSku.sku_id == sku_id,
            MonitorSku.is_deleted == 0,
        )
        .first()
    )


def set_skus_enabled(
    db: Session, item_id: int, sku_ids: List[str], enabled: int
) -> int:
    q = db.query(MonitorSku).filter(
        MonitorSku.item_id == item_id, MonitorSku.is_deleted == 0
    )
    if sku_ids:
        q = q.filter(MonitorSku.sku_id.in_(sku_ids))
    count = q.update({MonitorSku.monitor_enabled: enabled}, synchronize_session=False)
    db.commit()
    return count


# ==================== 价格历史 ====================
def price_points(
    db: Session,
    item_id: int,
    sku_id: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: int = 2000,
) -> List[PriceSnapshot]:
    q = db.query(PriceSnapshot).filter(PriceSnapshot.item_id == item_id)
    if sku_id:
        q = q.filter(PriceSnapshot.sku_id == sku_id)
    if start:
        q = q.filter(PriceSnapshot.snapshot_time >= start)
    if end:
        q = q.filter(PriceSnapshot.snapshot_time <= end)
    return q.order_by(PriceSnapshot.snapshot_time.asc()).limit(limit).all()


def price_series(
    db: Session,
    item_id: int,
    sku_id: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    fmt: str = "%Y-%m-%d",
) -> List[dict]:
    bucket = func.date_format(PriceSnapshot.snapshot_time, fmt)
    q = db.query(
        bucket.label("bucket"),
        func.avg(PriceSnapshot.price).label("avg_price"),
        func.min(PriceSnapshot.price).label("min_price"),
        func.max(PriceSnapshot.price).label("max_price"),
        func.max(PriceSnapshot.stock).label("stock"),
    ).filter(PriceSnapshot.item_id == item_id)
    if sku_id:
        q = q.filter(PriceSnapshot.sku_id == sku_id)
    if start:
        q = q.filter(PriceSnapshot.snapshot_time >= start)
    if end:
        q = q.filter(PriceSnapshot.snapshot_time <= end)
    rows = q.group_by(bucket).order_by(bucket.asc()).all()
    return [
        {
            "time": r.bucket,
            "price": float(r.avg_price) if r.avg_price is not None else None,
            "min_price": float(r.min_price) if r.min_price is not None else None,
            "max_price": float(r.max_price) if r.max_price is not None else None,
            "stock": int(r.stock) if r.stock is not None else None,
        }
        for r in rows
    ]


# ==================== 变更记录 ====================
def changes_page(
    db: Session,
    item_id: int,
    sku_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[ChangeRecord], int]:
    q = db.query(ChangeRecord).filter(ChangeRecord.item_id == item_id)
    if sku_id:
        q = q.filter(ChangeRecord.sku_id == sku_id)
    total = q.count()
    rows = (
        q.order_by(ChangeRecord.change_time.desc(), ChangeRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total
