from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.response import ok
from app.service import dashboard as dashboard_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/overview")
def dashboard_overview(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("dashboard:read")),
):
    """看板概览（权限：dashboard:read）。"""
    data: Dict[str, Any] = dashboard_service.dashboard_overview_service(db=db)
    return ok(data)


@router.get("/trend")
def dashboard_trend(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("dashboard:read")),
    metric: str = Query(default="crawl", pattern="^(crawl|alert)$"),
    days: int = Query(default=7, ge=1, le=90),
):
    """趋势图数据（权限：dashboard:read）。"""
    data = dashboard_service.dashboard_trend_service(db=db, metric=metric, days=days)
    return ok(data)
