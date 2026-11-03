from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.db.models import DeadLetter, MonitorItem


def create_dead_letter(db: Session, data: dict) -> DeadLetter:
    """新增一条死信记录。"""
    obj = DeadLetter(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def list_dead_letters(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    item_id: Optional[int] = None,
    keyword: Optional[str] = None,
) -> tuple[List[DeadLetter], int]:
    """分页查询死信列表。"""
    from sqlalchemy import or_

    q = db.query(DeadLetter)
    if status is not None:
        q = q.filter(DeadLetter.status == status)
    if item_id is not None:
        q = q.filter(DeadLetter.item_id == item_id)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            or_(
                DeadLetter.fail_reason.ilike(like),
                DeadLetter.raw_error.ilike(like),
            )
        )
    total = q.count()
    rows = q.order_by(DeadLetter.last_fail_at.desc(), DeadLetter.id.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return rows, total


def get_dead_letter(db: Session, dead_id: int) -> Optional[DeadLetter]:
    """根据 ID 获取死信。"""
    return db.query(DeadLetter).filter(DeadLetter.id == dead_id).first()


def update_dead_letter_status(
    db: Session,
    dead_id: int,
    status: str,
    resolved_by: Optional[str] = None,
    resolved_at: Optional[datetime] = None,
) -> Optional[DeadLetter]:
    """更新死信处理状态。"""
    dl = get_dead_letter(db, dead_id)
    if not dl:
        return None
    dl.status = status
    if resolved_by is not None:
        dl.resolved_by = resolved_by
    if resolved_at is not None:
        dl.resolved_at = resolved_at
    db.commit()
    db.refresh(dl)
    return dl


def increment_fail_count(db: Session, item_id: int) -> Optional[MonitorItem]:
    """监控商品连续失败计数 +1。"""
    item = (
        db.query(MonitorItem)
        .filter(MonitorItem.id == item_id, MonitorItem.is_deleted == 0)
        .first()
    )
    if not item:
        return None
    item.fail_count = (item.fail_count or 0) + 1
    db.commit()
    db.refresh(item)
    return item
