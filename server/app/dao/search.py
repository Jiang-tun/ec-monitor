from typing import List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import MonitorItem, SearchCandidate, SearchTask, SearchTaskItem


def create_task(db: Session, **kwargs) -> SearchTask:
    obj = SearchTask(**kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_by_task_id(db: Session, task_id: str) -> Optional[SearchTask]:
    return db.query(SearchTask).filter(SearchTask.task_id == task_id).first()


def get_task(db: Session, task_pk: int) -> Optional[SearchTask]:
    return db.query(SearchTask).filter(SearchTask.id == task_pk).first()


def list_tasks(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    platform_id: Optional[int] = None,
    keyword: Optional[str] = None,
    status: Optional[str] = None,
) -> Tuple[List[SearchTask], int]:
    q = db.query(SearchTask)
    if platform_id is not None:
        q = q.filter(SearchTask.platform_id == platform_id)
    if keyword:
        q = q.filter(SearchTask.keyword.ilike(f"%{keyword}%"))
    if status:
        q = q.filter(SearchTask.status == status)
    total = q.count()
    rows = (
        q.order_by(SearchTask.created_at.desc(), SearchTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total


def update_task(db: Session, task: SearchTask, **fields) -> SearchTask:
    for key, value in fields.items():
        setattr(task, key, value)
    db.commit()
    db.refresh(task)
    return task


def get_seen(
    db: Session, platform_id: int, keyword: str, platform_item_id: str
) -> Optional[SearchTaskItem]:
    return (
        db.query(SearchTaskItem)
        .filter(
            SearchTaskItem.platform_id == platform_id,
            SearchTaskItem.keyword == keyword,
            SearchTaskItem.platform_item_id == platform_item_id,
        )
        .first()
    )


def add_seen(
    db: Session,
    platform_id: int,
    keyword: str,
    platform_item_id: str,
    monitor_item_id: Optional[int] = None,
) -> SearchTaskItem:
    obj = SearchTaskItem(
        platform_id=platform_id,
        keyword=keyword,
        platform_item_id=platform_item_id,
        monitor_item_id=monitor_item_id,
    )
    db.add(obj)
    return obj


def get_monitor_item(
    db: Session, platform_id: int, platform_item_id: str
) -> Optional[MonitorItem]:
    return (
        db.query(MonitorItem)
        .filter(
            MonitorItem.platform_id == platform_id,
            MonitorItem.item_id == platform_item_id,
            MonitorItem.is_deleted == 0,
        )
        .first()
    )


def create_monitor_item(db: Session, **kwargs) -> MonitorItem:
    obj = MonitorItem(**kwargs)
    db.add(obj)
    db.flush()
    return obj

# ==================== 候选商品 ====================


def add_candidate(db: Session, **kwargs) -> SearchCandidate:
    obj = SearchCandidate(**kwargs)
    db.add(obj)
    db.flush()
    return obj


def list_candidates(
    db: Session, task_id: str, only_pending: bool = False
) -> List[SearchCandidate]:
    q = db.query(SearchCandidate).filter(SearchCandidate.task_id == task_id)
    if only_pending:
        q = q.filter(SearchCandidate.status == "pending")
    return q.order_by(SearchCandidate.id.asc()).all()


def get_candidate(db: Session, candidate_id: int) -> Optional[SearchCandidate]:
    return db.query(SearchCandidate).filter(SearchCandidate.id == candidate_id).first()


def skip_pending_candidates(db: Session, task_id: str) -> int:
    return (
        db.query(SearchCandidate)
        .filter(
            SearchCandidate.task_id == task_id,
            SearchCandidate.status == "pending",
        )
        .update({"status": "skipped"}, synchronize_session=False)
    )