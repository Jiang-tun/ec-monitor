from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.response import ok
from app.schemas.quality import (
    QualityIssueCreate,
    QualityIssueOut,
    QualityIssueReview,
    QualityIssuePage,
)
from app.service import quality as quality_service

router = APIRouter(prefix="/api/quality-issues", tags=["quality-issues"])


@router.get("")
def list_quality_issues(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("quality:read")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    item_id: Optional[int] = Query(default=None),
    sku_id: Optional[str] = Query(default=None),
    issue_type: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    review_status: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
):
    """质量问题列表（权限：quality:read）。"""
    rows, total = quality_service.list_quality_issues_service(
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
    return ok(
        {
            "items": [r.__dict__ for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("")
def create_quality_issue(
    data: QualityIssueCreate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("quality:write")),
):
    """新增质量问题（权限：quality:write）。"""
    issue = quality_service.create_quality_issue_service(db=db, data=data)
    return ok(issue.__dict__)


@router.get("/{issue_id}")
def get_quality_issue(
    issue_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("quality:read")),
):
    """质量问题详情（权限：quality:read）。"""
    issue = quality_service.get_quality_issue_service(db=db, issue_id=issue_id)
    return ok(issue.__dict__)


@router.put("/{issue_id}/review")
def review_quality_issue(
    issue_id: int,
    data: QualityIssueReview,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("quality:review")),
):
    """质量问题复核（权限：quality:review）。"""
    issue = quality_service.review_quality_issue_service(
        db=db, issue_id=issue_id, data=data, reviewed_by=getattr(user, "username", None)
    )
    return ok(issue.__dict__)


@router.get("/stats/by-status")
def quality_stats_by_status(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("quality:read")),
):
    """按复核状态统计质量问题数量（权限：quality:read）。"""
    return ok(quality_service.count_quality_by_status_service(db=db))
