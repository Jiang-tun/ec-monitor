from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import SysMessage


def add_message(db: Session, **kwargs) -> SysMessage:
    obj = SysMessage(**kwargs)
    db.add(obj)
    return obj


def list_messages(
    db: Session,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    is_read: Optional[int] = None,
    msg_type: Optional[str] = None,
) -> Tuple[List[SysMessage], int]:
    q = db.query(SysMessage).filter(SysMessage.user_id == user_id)
    if is_read is not None:
        q = q.filter(SysMessage.is_read == is_read)
    if msg_type:
        q = q.filter(SysMessage.msg_type == msg_type)
    total = q.count()
    rows = (
        q.order_by(SysMessage.created_at.desc(), SysMessage.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total


def unread_count(db: Session, user_id: int) -> int:
    return (
        db.query(SysMessage)
        .filter(SysMessage.user_id == user_id, SysMessage.is_read == 0)
        .count()
    )


def get_message(db: Session, user_id: int, message_id: int) -> Optional[SysMessage]:
    return (
        db.query(SysMessage)
        .filter(SysMessage.id == message_id, SysMessage.user_id == user_id)
        .first()
    )


def mark_read(db: Session, user_id: int, message_id: int) -> Optional[SysMessage]:
    msg = get_message(db, user_id, message_id)
    if not msg:
        return None
    if msg.is_read != 1:
        msg.is_read = 1
        msg.read_at = datetime.now()
        db.commit()
        db.refresh(msg)
    return msg


def mark_all_read(db: Session, user_id: int) -> int:
    count = (
        db.query(SysMessage)
        .filter(SysMessage.user_id == user_id, SysMessage.is_read == 0)
        .update(
            {"is_read": 1, "read_at": datetime.now()},
            synchronize_session=False,
        )
    )
    db.commit()
    return count


def clear_messages(db: Session, user_id: int) -> int:
    """删除当前用户的全部消息，返回删除条数。"""
    count = (
        db.query(SysMessage)
        .filter(SysMessage.user_id == user_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return count
