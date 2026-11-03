from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.db.models import ChangeRecord, MonitorItem, MonitorSku, PriceSnapshot


def create_snapshot(db: Session, data: dict) -> PriceSnapshot:
    """插入单条快照（追加写）。"""
    obj = PriceSnapshot(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def create_snapshots_batch(db: Session, rows: List[dict]) -> List[PriceSnapshot]:
    """批量插入快照（追加写）。"""
    objs = [PriceSnapshot(**r) for r in rows]
    db.add_all(objs)
    db.commit()
    for o in objs:
        db.refresh(o)
    return objs


def get_latest_snapshot(
    db: Session,
    item_id: int,
    sku_id: Optional[str] = None,
    exclude_id: Optional[int] = None,
) -> Optional[PriceSnapshot]:
    """获取最新一条快照（用于变更检测 diff）。"""
    q = db.query(PriceSnapshot).filter(PriceSnapshot.item_id == item_id)
    if sku_id is not None:
        q = q.filter(PriceSnapshot.sku_id == sku_id)
    if exclude_id is not None:
        q = q.filter(PriceSnapshot.id != exclude_id)
    return q.order_by(PriceSnapshot.snapshot_time.desc(), PriceSnapshot.id.desc()).first()


def update_sku_redundant(
    db: Session,
    item_id: int,
    sku_id: Optional[str],
    price: Optional[float] = None,
    original_price: Optional[float] = None,
    stock: Optional[int] = None,
) -> None:
    """更新 monitor_sku 冗余字段（最新值）。"""
    if sku_id is None:
        return
    sku = (
        db.query(MonitorSku)
        .filter(
            MonitorSku.item_id == item_id,
            MonitorSku.sku_id == sku_id,
            MonitorSku.is_deleted == 0,
        )
        .first()
    )
    if not sku:
        return
    if price is not None:
        sku.price = price
    if original_price is not None:
        sku.original_price = original_price
    if stock is not None:
        sku.stock = stock
    db.commit()


def update_item_last_crawl(db: Session, item_id: int, success: bool) -> None:
    """更新 monitor_item 最近采集信息。"""
    item = (
        db.query(MonitorItem)
        .filter(MonitorItem.id == item_id, MonitorItem.is_deleted == 0)
        .first()
    )
    if not item:
        return
    item.last_crawl_time = datetime.now()
    item.last_success_status = 1 if success else 0
    if success:
        item.fail_count = 0
    else:
        item.fail_count = (item.fail_count or 0) + 1
    db.commit()


def create_change_record(db: Session, data: dict) -> ChangeRecord:
    """写入一条字段级变更记录。"""
    obj = ChangeRecord(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_pending_change_snapshots(db: Session, limit: int = 500) -> List[PriceSnapshot]:
    """获取尚未产生变更记录的快照（缺口巡检）。"""
    from app.db.models import ChangeRecord

    subq = db.query(ChangeRecord.snapshot_id).filter(
        ChangeRecord.snapshot_id.isnot(None)
    )
    q = (
        db.query(PriceSnapshot)
        .outerjoin(ChangeRecord, ChangeRecord.snapshot_id == PriceSnapshot.id)
        .filter(ChangeRecord.id.is_(None))
        .order_by(PriceSnapshot.snapshot_time.asc())
        .limit(limit)
    )
    return q.all()
