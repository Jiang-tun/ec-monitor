from fastapi import APIRouter, Depends

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.response import ok
from app.service.scheduler import scheduler_service

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.post("/tick")
def scheduler_tick(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
    batch_size: int = 500,
):
    """手动触发一轮种子注入（Manager 业务调度）。"""
    result = scheduler_service.schedule_once(db, batch_size=batch_size)
    return ok(result)


@router.get("/status")
def scheduler_status(
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
):
    """查看调度状态（leader、暂停开关、队列积压）。"""
    lag = scheduler_service.queue_lag()
    threshold = scheduler_service.settings.queue_lag_threshold
    return ok(
        {
            "is_leader": scheduler_service.is_leader(),
            "paused": scheduler_service.is_paused(),
            "queue_lag": lag,
            "queue_total": sum(lag.values()),
            "threshold": threshold,
            "over_threshold": [g for g, n in lag.items() if n > threshold],
            "tick_sec": scheduler_service.settings.scheduler_tick_sec,
            "enabled": scheduler_service.settings.scheduler_enabled,
        }
    )


@router.post("/pause", response_model=None)
def scheduler_pause(
    paused: bool,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """暂停/恢复自动调度（不影响手动 tick）。"""
    return ok({"paused": scheduler_service.set_paused(paused)})
