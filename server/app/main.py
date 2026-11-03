import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import alert, auth, dashboard, dead_letter, health, internal, item, item_group, message, platform_auth, platform_login, proxy, quality, scheduler, search, sms, system
from app.core.audit import AuditMiddleware
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.middleware import TraceMiddleware

settings = get_settings()
logger = logging.getLogger(__name__)


def _scheduler_tick() -> None:
    """一次调度：抢 leader → 注入到期商品 → 冲刷告警聚合。"""
    from app.db.session import SessionLocal
    from app.service import rule_engine
    from app.service.scheduler import scheduler_service

    db = SessionLocal()
    try:
        # 超时任务收尾（不受暂停/leader 影响，避免前端长期显示"进行中"）
        try:
            scheduler_service.finalize_stale_tasks(db)
        except Exception:  # noqa: BLE001
            db.rollback()
        if scheduler_service.is_paused():
            return
        if not scheduler_service.try_acquire_leader():
            return
        scheduler_service.schedule_once(db)
        rule_engine.flush_aggregations(db)
    finally:
        db.close()


async def _scheduler_loop(interval: int) -> None:
    while True:
        try:
            await asyncio.to_thread(_scheduler_tick)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 后台任务不能让进程退出
            logger.exception("scheduler tick failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if settings.scheduler_enabled:
        interval = max(5, settings.scheduler_tick_sec)
        task = asyncio.create_task(_scheduler_loop(interval))
        logger.info("scheduler loop started, interval=%ss", interval)
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AuditMiddleware)
    app.add_middleware(TraceMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(alert.router)
    app.include_router(system.router)
    app.include_router(item.router)
    app.include_router(item.platform_router)
    app.include_router(item_group.router)
    app.include_router(proxy.router)
    app.include_router(internal.router)
    app.include_router(scheduler.router)
    app.include_router(quality.router)
    app.include_router(dead_letter.router)
    app.include_router(dashboard.router)
    app.include_router(message.router)
    app.include_router(platform_login.router)
    app.include_router(platform_auth.router)
    app.include_router(search.router)
    app.include_router(sms.router)
    return app


app = create_app()
