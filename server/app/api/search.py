from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.response import ok
from app.schemas.search import SearchConfirmIn, SearchTaskCreate
from app.service import search as search_service

router = APIRouter(prefix="/api/search-tasks", tags=["search-tasks"])


@router.post("", response_model=None)
def create_search_task(
    data: SearchTaskCreate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """创建关键词采集任务（异步，权限：item:write）。"""
    task = search_service.create_task(db=db, data=data, created_by=user.username)
    return ok(task.model_dump())


@router.get("", response_model=None)
def list_search_tasks(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    platform_id: Optional[int] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
):
    """关键词采集任务列表（权限：item:read）。"""
    items, total = search_service.list_tasks(
        db=db,
        page=page,
        page_size=page_size,
        platform_id=platform_id,
        keyword=keyword,
        status=status,
    )
    return ok(
        {
            "items": [t.model_dump() for t in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/{task_id}", response_model=None)
def get_search_task(
    task_id: str,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
):
    """关键词采集任务详情（权限：item:read）。"""
    return ok(search_service.get_task(db=db, task_id=task_id).model_dump())


@router.post("/{task_id}/run", response_model=None)
def run_search_task(
    task_id: str,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """启动该任务对应的搜索 Spider（子进程，一次性执行，权限：item:write）。"""
    return ok(search_service.run_task(db=db, task_id=task_id))

@router.get("/{task_id}/candidates", response_model=None)
def list_search_candidates(
    task_id: str,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
    only_pending: bool = Query(default=False),
):
    """关键词采集候选列表（权限：item:read）。"""
    items = search_service.list_candidates(
        db=db, task_id=task_id, only_pending=only_pending
    )
    return ok({"items": [c.model_dump() for c in items], "total": len(items)})


@router.post("/{task_id}/confirm", response_model=None)
def confirm_search_candidates(
    task_id: str,
    data: SearchConfirmIn,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """用户筛选确认后入库（权限：item:write）。"""
    result = search_service.confirm_candidates(db=db, task_id=task_id, data=data)
    return ok(result.model_dump())