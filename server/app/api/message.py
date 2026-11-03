from typing import Optional

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, DbSession
from app.core.response import ok
from app.service import message as message_service

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("", response_model=None)
def list_messages(
    db: DbSession,
    user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    is_read: Optional[int] = Query(default=None),
    msg_type: Optional[str] = Query(default=None),
):
    """当前用户的消息列表。"""
    items, total = message_service.list_messages(
        db=db,
        user_id=user.id,
        page=page,
        page_size=page_size,
        is_read=is_read,
        msg_type=msg_type,
    )
    return ok(
        {
            "items": [m.model_dump() for m in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/unread-count", response_model=None)
def unread_count(db: DbSession, user: CurrentUser):
    """当前用户未读消息数。"""
    return ok(message_service.unread_count(db=db, user_id=user.id).model_dump())


@router.put("/read-all", response_model=None)
def read_all(db: DbSession, user: CurrentUser):
    """全部标记已读。"""
    updated = message_service.mark_all_read(db=db, user_id=user.id)
    return ok({"updated": updated})


@router.delete("", response_model=None)
def clear_all(db: DbSession, user: CurrentUser):
    """一键清理：删除当前用户全部消息。"""
    deleted = message_service.clear_messages(db=db, user_id=user.id)
    return ok({"deleted": deleted})


@router.put("/{message_id}/read", response_model=None)
def read_message(message_id: int, db: DbSession, user: CurrentUser):
    """单条消息标记已读。"""
    message = message_service.mark_read(db=db, user_id=user.id, message_id=message_id)
    if not message:
        return ok({"message": "消息不存在"}, code=404)
    return ok(message.model_dump())
