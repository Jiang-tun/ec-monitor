from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.response import ok
from app.db.models import DeadLetter
from app.schemas.dead_letter import (
    DeadLetterCreate,
    DeadLetterOut,
    DeadLetterUpdate,
    DeadLetterRetry,
    DeadLetterPage,
)
from app.service import dead_letter as dead_letter_service

router = APIRouter(prefix="/api/dead-letters", tags=["dead-letters"])


@router.get("/stats")
def dead_letter_stats(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
):
    """死信状态统计（需在 /{dead_id} 之前注册）。"""
    rows = (
        db.query(DeadLetter.status, func.count(DeadLetter.id))
        .group_by(DeadLetter.status)
        .all()
    )
    data = {status: count for status, count in rows}
    for key in ("pending", "retrying", "resolved", "discarded"):
        data.setdefault(key, 0)
    data["total"] = sum(value for value in data.values())
    return ok(data)


@router.get("")
def list_dead_letters(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status: Optional[str] = Query(default=None),
    item_id: Optional[int] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
):
    """死信列表（权限：item:read）。"""
    rows, total = dead_letter_service.list_dead_letters_service(
        db=db,
        page=page,
        page_size=page_size,
        status=status,
        item_id=item_id,
        keyword=keyword,
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
def create_dead_letter(
    data: DeadLetterCreate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """新增死信（权限：item:write）。"""
    dl = dead_letter_service.create_dead_letter_service(db=db, data=data)
    return ok(dl.__dict__)


@router.get("/{dead_id}")
def get_dead_letter(
    dead_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
):
    """死信详情（权限：item:read）。"""
    dl = dead_letter_service.get_dead_letter_service(db=db, dead_id=dead_id)
    return ok(dl.__dict__)


@router.put("/{dead_id}")
def update_dead_letter(
    dead_id: int,
    data: DeadLetterUpdate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("retry:manual")),
):
    """更新死信处理状态（权限：retry:manual）。"""
    dl = dead_letter_service.update_dead_letter_status_service(
        db=db, dead_id=dead_id, data=data, resolved_by=getattr(user, "username", None)
    )
    return ok(dl.__dict__)


@router.post("/batch-retry")
def batch_retry_dead_letters(
    data: DeadLetterRetry,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("retry:manual")),
):
    """批量重试死信（权限：retry:manual）。"""
    result = dead_letter_service.retry_dead_letters_service(db=db, data=data)
    return ok(result)
