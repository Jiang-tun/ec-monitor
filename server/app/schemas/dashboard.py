from typing import Any, Dict, List

from pydantic import BaseModel


# ==================== 仪表盘概览 Schema =====

class DashboardOverviewOut(BaseModel):
    items: Dict[str, Any]
    crawl_today: Dict[str, Any]
    alerts_today: Dict[str, Any]
    quality: Dict[str, Any]
    proxy: Dict[str, Any]


# ==================== 趋势图 Schema =====

class TrendPointOut(BaseModel):
    time: str
    value: float


class DashboardTrendOut(BaseModel):
    metric: str
    points: List[TrendPointOut]
