from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.db.models import QualityIssue


def create_quality_issue(db: Session, data: dict) -> QualityIssue:
    """新增一条质量问题记录。"""
    obj = QualityIssue(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def list_quality_issues(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    item_id: Optional[int] = None,
    sku_id: Optional[str] = None,
    issue_type: Optional[str] = None,
    severity: Optional[str] = None,
    review_status: Optional[str] = None,
    keyword: Optional[str] = None,
) -> Tuple[List[QualityIssue], int]:
    """分页查询质量问题列表。"""
    q = db.query(QualityIssue)

    if item_id is not None:
        q = q.filter(QualityIssue.item_id == item_id)
    if sku_id is not None:
        q = q.filter(QualityIssue.sku_id == sku_id)
    if issue_type is not None:
        q = q.filter(QualityIssue.issue_type == issue_type)
    if severity is not None:
        q = q.filter(QualityIssue.severity == severity)
    if review_status is not None:
        q = q.filter(QualityIssue.review_status == review_status)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            or_(
                QualityIssue.summary.ilike(like),
                QualityIssue.issue_type.ilike(like),
            )
        )

    total = q.count()
    rows = q.order_by(QualityIssue.occurred_at.desc(), QualityIssue.id.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return rows, total


def get_quality_issue(db: Session, issue_id: int) -> Optional[QualityIssue]:
    """根据 ID 获取质量问题。"""
    return db.query(QualityIssue).filter(QualityIssue.id == issue_id).first()


def update_quality_issue_review(
    db: Session,
    issue_id: int,
    review_status: str,
    review_note: Optional[str] = None,
    reviewed_by: Optional[str] = None,
) -> Optional[QualityIssue]:
    """复核质量问题（确认/忽略/修复）。"""
    issue = get_quality_issue(db, issue_id)
    if not issue:
        return None
    issue.review_status = review_status
    if review_note is not None:
        issue.review_note = review_note
    issue.reviewed_by = reviewed_by
    issue.reviewed_at = datetime.now()
    db.commit()
    db.refresh(issue)
    return issue


def count_quality_by_status(
    db: Session,
) -> dict:
    """按 review_status 统计质量问题数量。"""
    rows = (
        db.query(QualityIssue.review_status, func.count(QualityIssue.id))
        .group_by(QualityIssue.review_status)
        .all()
    )
    return {r[0] or "pending": r[1] for r in rows}
