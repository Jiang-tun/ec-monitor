from typing import List, Optional

from sqlalchemy.orm import Session

from app.dao import message as message_dao
from app.db.models import AlertLog, SysUser
from app.schemas.message import MessageOut, UnreadCountOut


def _active_user_ids(db: Session) -> List[int]:
    return [row[0] for row in db.query(SysUser.id).filter(SysUser.status == 1).all()]


def _push(db: Session, user_ids: List[int], **kwargs) -> int:
    for user_id in user_ids:
        message_dao.add_message(db, user_id=user_id, **kwargs)
    return len(user_ids)


def push_alert_message(
    db: Session, alert: AlertLog, user_ids: Optional[List[int]] = None
) -> int:
    """把一条告警写入所有启用用户的站内消息（不单独 commit，由调用方提交）。"""
    if user_ids is None:
        user_ids = _active_user_ids(db)
    payload = alert.payload_json or {}
    rule_name = payload.get("rule_name") or alert.rule_type or "告警"
    level = alert.severity or "info"
    title = f"【{level.upper()}】{rule_name}"[:128]
    content = (alert.message or "")[:2000]

    for user_id in user_ids:
        message_dao.add_message(
            db,
            user_id=user_id,
            title=title,
            content=content,
            msg_type="alert",
            level=level,
            link="/alerts",
            ref_type="alert",
            ref_id=str(alert.id),
        )
    return len(user_ids)


def list_messages(
    db: Session,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    is_read: Optional[int] = None,
    msg_type: Optional[str] = None,
) -> tuple[List[MessageOut], int]:
    rows, total = message_dao.list_messages(
        db,
        user_id=user_id,
        page=page,
        page_size=page_size,
        is_read=is_read,
        msg_type=msg_type,
    )
    return [MessageOut.model_validate(r) for r in rows], total


def unread_count(db: Session, user_id: int) -> UnreadCountOut:
    return UnreadCountOut(count=message_dao.unread_count(db, user_id))


def mark_read(db: Session, user_id: int, message_id: int) -> Optional[MessageOut]:
    msg = message_dao.mark_read(db, user_id=user_id, message_id=message_id)
    return MessageOut.model_validate(msg) if msg else None


def mark_all_read(db: Session, user_id: int) -> int:
    return message_dao.mark_all_read(db, user_id=user_id)


def clear_messages(db: Session, user_id: int) -> int:
    return message_dao.clear_messages(db, user_id=user_id)

def push_quality_message(db: Session, issue) -> int:
    """质量异常写入消息中心。"""
    level = "critical" if (issue.severity or "") == "critical" else "warn"
    return _push(
        db,
        _active_user_ids(db),
        title=f"【质量异常】{issue.issue_type}"[:128],
        content=(issue.summary or "")[:2000],
        msg_type="quality",
        level=level,
        link="/quality",
        ref_type="quality_issue",
        ref_id=str(issue.id),
    )


def push_dead_letter_message(db: Session, dead) -> int:
    """死信写入消息中心。"""
    return _push(
        db,
        _active_user_ids(db),
        title="【死信】采集失败待处理",
        content=(
            f"商品ID {dead.item_id} 在 {dead.fail_stage} 阶段失败："
            f"{dead.fail_reason}"
        )[:2000],
        msg_type="dead_letter",
        level="warn",
        link="/dead-letters",
        ref_type="dead_letter",
        ref_id=str(dead.id),
    )

def push_system_message(
    db: Session,
    title: str,
    content: str,
    level: str = "info",
    link: Optional[str] = None,
    msg_type: str = "system",
) -> int:
    """通用系统消息（队列积压、节点离线等）。"""
    return _push(
        db,
        _active_user_ids(db),
        title=title[:128],
        content=(content or "")[:2000],
        msg_type=msg_type,
        level=level,
        link=link,
        ref_type=None,
        ref_id=None,
    )