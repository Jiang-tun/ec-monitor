from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.dao import quality as quality_dao
from app.schemas.quality import (
    QualityIssueCreate,
    QualityIssueUpdate,
    QualityIssueReview,
)


def list_quality_issues_service(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    item_id: Optional[int] = None,
    sku_id: Optional[str] = None,
    issue_type: Optional[str] = None,
    severity: Optional[str] = None,
    review_status: Optional[str] = None,
    keyword: Optional[str] = None,
):
    rows, total = quality_dao.list_quality_issues(
        db=db,
        page=page,
        page_size=page_size,
        item_id=item_id,
        sku_id=sku_id,
        issue_type=issue_type,
        severity=severity,
        review_status=review_status,
        keyword=keyword,
    )
    return rows, total


def create_quality_issue_service(db: Session, data: QualityIssueCreate):
    return quality_dao.create_quality_issue(db, data.model_dump())


def get_quality_issue_service(db: Session, issue_id: int):
    issue = quality_dao.get_quality_issue(db, issue_id)
    if not issue:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="质量问题不存在")
    return issue


def review_quality_issue_service(
    db: Session,
    issue_id: int,
    data: QualityIssueReview,
    reviewed_by: Optional[str] = None,
):
    issue = quality_dao.update_quality_issue_review(
        db=db,
        issue_id=issue_id,
        review_status=data.review_status,
        review_note=data.review_note,
        reviewed_by=reviewed_by,
    )
    if not issue:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="质量问题不存在")
    return issue


def count_quality_by_status_service(db: Session):
    return quality_dao.count_quality_by_status(db)
