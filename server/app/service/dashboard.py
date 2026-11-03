from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.dao import item as item_dao
from app.dao import alert as alert_dao
from app.dao import quality as quality_dao
from app.db.models import MonitorItem, AlertLog, PriceSnapshot


def dashboard_overview_service(db: Session) -> Dict[str, Any]:
    """看板概览数据。"""
    # 商品状态统计
    total = db.query(MonitorItem).filter(MonitorItem.is_deleted == 0).count()
    monitoring = db.query(MonitorItem).filter(
        MonitorItem.is_deleted == 0, MonitorItem.monitor_status == 1
    ).count()
    paused = db.query(MonitorItem).filter(
        MonitorItem.is_deleted == 0, MonitorItem.monitor_status == 0
    ).count()
    suspect = db.query(MonitorItem).filter(
        MonitorItem.is_deleted == 0, MonitorItem.monitor_status == 2
    ).count()
    delisted = db.query(MonitorItem).filter(
        MonitorItem.is_deleted == 0, MonitorItem.monitor_status == 3
    ).count()

    # 今日采集（简化：按 created_at 今日统计快照）
    from datetime import datetime, timedelta
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_total = db.query(PriceSnapshot).filter(
        PriceSnapshot.created_at >= today_start
    ).count()
    today_success = db.query(PriceSnapshot).filter(
        PriceSnapshot.created_at >= today_start,
        PriceSnapshot.page_status == 200,
    ).count()
    today_fail = today_total - today_success
    success_rate = round(today_success / today_total * 100, 2) if today_total else 0.0

    # 今日告警
    alerts_total = db.query(AlertLog).filter(
        AlertLog.created_at >= today_start
    ).count()
    alerts_pending = db.query(AlertLog).filter(
        AlertLog.created_at >= today_start,
        AlertLog.confirm_status == "pending",
    ).count()

    # 质量
    quality_counts = quality_dao.count_quality_by_status(db)
    quality_pending = quality_counts.get("pending", 0)

    # 代理
    from app.db.models import Proxy
    proxy_total = db.query(Proxy).filter(Proxy.is_deleted == 0).count()
    proxy_available = db.query(Proxy).filter(
        Proxy.is_deleted == 0, Proxy.available == 1
    ).count()
    proxy_rate = round(proxy_available / proxy_total * 100, 2) if proxy_total else 0.0

    return {
        "items": {
            "total": total,
            "monitoring": monitoring,
            "paused": paused,
            "suspect_delist": suspect,
            "delisted": delisted,
        },
        "crawl_today": {
            "total": today_total,
            "success": today_success,
            "fail": today_fail,
            "success_rate": success_rate,
        },
        "alerts_today": {
            "total": alerts_total,
            "pending_confirm": alerts_pending,
        },
        "quality": {
            "pending_review": quality_pending,
        },
        "proxy": {
            "total": proxy_total,
            "available": proxy_available,
            "availability_rate": proxy_rate,
        },
    }


def dashboard_trend_service(db: Session, metric: str, days: int = 7) -> Dict[str, Any]:
    """趋势图数据（简化：按天聚合快照/告警）。"""
    from datetime import datetime, timedelta
    from sqlalchemy import func

    end = datetime.now()
    start = end - timedelta(days=days - 1)

    points: List[Dict[str, Any]] = []
    if metric == "crawl":
        rows = (
            db.query(
                func.date_format(PriceSnapshot.created_at, "%Y-%m-%d").label("day"),
                func.count(PriceSnapshot.id).label("cnt"),
            )
            .filter(PriceSnapshot.created_at >= start)
            .group_by("day")
            .order_by("day")
            .all()
        )
        for r in rows:
            points.append({"time": r.day, "value": int(r.cnt)})
    elif metric == "alert":
        rows = (
            db.query(
                func.date_format(AlertLog.created_at, "%Y-%m-%d").label("day"),
                func.count(AlertLog.id).label("cnt"),
            )
            .filter(AlertLog.created_at >= start)
            .group_by("day")
            .order_by("day")
            .all()
        )
        for r in rows:
            points.append({"time": r.day, "value": int(r.cnt)})
    else:
        # 默认返回空序列
        d = start
        while d <= end:
            points.append({"time": d.strftime("%Y-%m-%d"), "value": 0})
            d += timedelta(days=1)

    return {"metric": metric, "points": points}
