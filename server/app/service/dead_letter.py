from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.dao import dead_letter as dead_letter_dao
from app.db.models import MonitorItem
from app.service.scheduler import scheduler_service
from app.schemas.dead_letter import DeadLetterCreate, DeadLetterUpdate, DeadLetterRetry


def list_dead_letters_service(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    item_id: Optional[int] = None,
    keyword: Optional[str] = None,
):
    rows, total = dead_letter_dao.list_dead_letters(
        db=db,
        page=page,
        page_size=page_size,
        status=status,
        item_id=item_id,
        keyword=keyword,
    )
    return rows, total


def create_dead_letter_service(db: Session, data: DeadLetterCreate):
    return dead_letter_dao.create_dead_letter(db, data.model_dump())


def get_dead_letter_service(db: Session, dead_id: int):
    dl = dead_letter_dao.get_dead_letter(db, dead_id)
    if not dl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="死信不存在")
    return dl


def update_dead_letter_status_service(
    db: Session,
    dead_id: int,
    data: DeadLetterUpdate,
    resolved_by: Optional[str] = None,
):
    from datetime import datetime

    dl = dead_letter_dao.update_dead_letter_status(
        db=db,
        dead_id=dead_id,
        status=data.status,
        resolved_by=resolved_by or data.resolved_by,
        resolved_at=datetime.now() if data.status in ("resolved", "discarded") else None,
    )
    if not dl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="死信不存在")
    return dl


def retry_dead_letters_service(db: Session, data: DeadLetterRetry):
    """死信重试：更新状态并把对应商品重新投递到采集队列。"""
    from datetime import datetime

    updated = 0
    items: List[MonitorItem] = []
    seen: set[int] = set()
    for dead_id in data.dead_ids:
        dl = dead_letter_dao.get_dead_letter(db, dead_id)
        if not dl:
            continue
        item = (
            db.query(MonitorItem)
            .filter(MonitorItem.id == dl.item_id, MonitorItem.is_deleted == 0)
            .first()
        )
        if not item:
            continue
        dl.status = "retrying"
        dl.retry_count = (dl.retry_count or 0) + 1
        dl.last_fail_at = datetime.now()
        updated += 1
        if item.id not in seen:
            seen.add(item.id)
            items.append(item)
    db.commit()

    queue_result = scheduler_service.enqueue_items(db, items, trigger_type="retry")
    return {"updated": updated, **queue_result}
