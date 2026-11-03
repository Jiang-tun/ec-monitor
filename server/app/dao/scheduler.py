from datetime import datetime
from typing import List, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.models import CrawlTaskLog, MonitorItem, Platform


def build_seed_request(item, site_group: str = "cn-main") -> dict:
    """构造种子 Request 结构"""
    return {
        "db_id": item.id,
        "item_id": item.item_id,
        "item_id_str": item.item_id,
        "url": item.url,
        "platform_id": item.platform_id,
        "shop_id": item.shop_id,
        "strategy": item.strategy,
        "price_basis": item.price_basis,
        "freq_group": item.crawl_freq,
        "site_group": site_group,
        "task_id": None,
        "retry_type": None,
        "dont_filter": True,
    }


def build_seed_requests(db: Session, batch_size: int = 500) -> List[dict]:
    """扫描到期待采集商品，构造种子 Request 列表（含平台 site_group）。"""
    items = (
        db.query(MonitorItem)
        .filter(
            MonitorItem.monitor_status == 1,
            MonitorItem.is_deleted == 0,
            (MonitorItem.next_run_time.is_(None))
            | (MonitorItem.next_run_time <= func.now()),
        )
        .order_by(
            MonitorItem.next_run_time.is_(None).desc(),
            MonitorItem.next_run_time.asc(),
        )
        .limit(batch_size)
        .all()
    )
    pmap = {
        p.id: ((p.adapter_config or {}).get("site_group") or "cn-main")
        for p in db.query(Platform).all()
    }
    seeds = []
    for item in items:
        seeds.append(build_seed_request(item, pmap.get(item.platform_id, "cn-main")))
    return seeds


def create_crawl_task_log(
    db: Session,
    task_id: str,
    shard: Optional[int] = None,
    node_id: Optional[str] = None,
    trigger_type: str = "schedule",
    freq_group: Optional[str] = None,
    total_count: int = 0,
) -> CrawlTaskLog:
    """构造采集任务批次记录"""
    obj = CrawlTaskLog(
        task_id=task_id,
        shard=shard,
        node_id=node_id,
        trigger_type=trigger_type,
        freq_group=freq_group,
        total_count=total_count,
        success_count=0,
        fail_count=0,
        dead_count=0,
        strategy_stat=None,
        status="running",
        start_time=datetime.now(),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_task_log(
    db: Session,
    task_id: str,
    success_count: Optional[int] = None,
    fail_count: Optional[int] = None,
    dead_count: Optional[int] = None,
    strategy_stat: Optional[dict] = None,
    cost_ms: Optional[int] = None,
    error_summary: Optional[str] = None,
    status: Optional[str] = None,
) -> None:
    """更新任务执行状态"""
    q = db.query(CrawlTaskLog).filter(CrawlTaskLog.task_id == task_id)
    if not q.first():
        return
    updates = {}
    if success_count is not None:
        updates["success_count"] = success_count
    if fail_count is not None:
        updates["fail_count"] = fail_count
    if dead_count is not None:
        updates["dead_count"] = dead_count
    if strategy_stat is not None:
        updates["strategy_stat"] = strategy_stat
    if cost_ms is not None:
        updates["cost_ms"] = cost_ms
    if error_summary is not None:
        updates["error_summary"] = error_summary
    if status is not None:
        updates["status"] = status
    if status in ("success", "failed", "partial"):
        updates["end_time"] = datetime.now()
    q.update(updates)
    db.commit()


def get_pending_snapshots(
    db: Session,
    item_id: int,
    limit: int = 500,
) -> List:
    """获取待消费的快照（用于变更检测）"""
    return (
        db.query(PriceSnapshot)
        .filter(
            PriceSnapshot.item_id == item_id,
            PriceSnapshot.field_hash.isnot(None),
        )
        .order_by(PriceSnapshot.snapshot_time.desc())
        .limit(limit)
        .all()
    )