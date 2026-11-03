import json
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.dao import quality as quality_dao
from app.db.models import MonitorItem, PriceSnapshot, SysDictItem


settings = get_settings()


# ==================== 数据质量校验（报告 5.6章 六条规则） ====================


def _get_price_range(db: Session, category_path: Optional[str]) -> Tuple[float, float]:
    """从 sys_dict 字典项获取价格区间，无配置则用全局 [1, 999999]。"""
    # 优先按类目命中：dict_code=price_range，dict_value 如 "电子/手机:100,10000"
    rows = db.query(SysDictItem).filter(
        SysDictItem.dict_code == "price_range",
        SysDictItem.status == 1,
        SysDictItem.is_deleted == 0,
    ).all()
    for row in rows:
        val = row.dict_value or ""
        if ":" in val:
            cat, rng = val.split(":", 1)
            if category_path and cat in category_path:
                parts = rng.split(",")
                if len(parts) == 2:
                    return float(parts[0]), float(parts[1])
    # 兜底：全局区间
    for row in rows:
        if row.dict_label and row.dict_label == "default":
            parts = (row.dict_value or "1,999999").split(",")
            if len(parts) == 2:
                return float(parts[0]), float(parts[1])
    return 1.0, 999999.0


def _price_history(
    db: Session, item_id: int, sku_id: Optional[str], days: int = 7
) -> List[float]:
    """查询近 N 天同 SKU 的价格序列（用于 median/MAD 偏离检测）。"""
    start = datetime.now() - timedelta(days=days)
    q = db.query(PriceSnapshot.price).filter(
        PriceSnapshot.item_id == item_id,
        PriceSnapshot.price.isnot(None),
        PriceSnapshot.snapshot_time >= start,
    )
    if sku_id is not None:
        q = q.filter(PriceSnapshot.sku_id == sku_id)
    return [float(r[0]) for r in q.all()]


def _mad(values: List[float]) -> float:
    if not values:
        return 0.0
    med = median(values)
    abs_devs = [abs(v - med) for v in values]
    return median(abs_devs) if abs_devs else 0.0


def check_snapshot_quality(
    db: Session,
    item: MonitorItem,
    sku_id: Optional[str],
    snapshot: dict,
) -> Tuple[int, List[dict]]:
    """对一条快照做质量校验。

    返回 (quality_flag, issues)：
      quality_flag: 0 正常 / 1 异常
      issues: 写入 quality_issue 所需的字段列表
    """
    issues: List[dict] = []
    price = snapshot.get("price")
    title = snapshot.get("title")
    stock = snapshot.get("stock")
    category_path = item.category_path
    now = datetime.now()

    # 1. 必填字段非空：price/title/stock
    if price is None or title is None:
        issues.append(
            {
                "item_id": item.id,
                "sku_id": sku_id,
                "issue_type": "missing_field",
                "severity": "critical",
                "detail": {
                    "price": price,
                    "title": title,
                    "stock": stock,
                },
                "summary": "必填字段缺失",
                "occurred_at": now,
            }
        )

    # 4. 价格为0/负
    if price is not None and price <= 0:
        issues.append(
            {
                "item_id": item.id,
                "sku_id": sku_id,
                "issue_type": "price_out_of_range",
                "severity": "critical",
                "detail": {"price": price, "reason": "price <= 0"},
                "summary": f"价格异常：{price}",
                "occurred_at": now,
            }
        )

    # 2. 价格区间合理性
    if price is not None and price > 0:
        lo, hi = _get_price_range(db, category_path)
        if price < lo or price > hi:
            issues.append(
                {
                    "item_id": item.id,
                    "sku_id": sku_id,
                    "issue_type": "price_out_of_range",
                    "severity": "warn",
                    "detail": {
                        "price": price,
                        "range": [lo, hi],
                        "category_path": category_path,
                    },
                    "summary": f"价格 {price} 超出区间 [{lo}, {hi}]",
                    "occurred_at": now,
                }
            )

    # 3. 偏离历史阈值：近 7 天 median 与 MAD
    if price is not None and price > 0:
        history = _price_history(db, item.id, sku_id, days=7)
        if history:
            med = median(history)
            mad = _mad(history)
            if mad > 0 and abs(price - med) > 5 * mad and abs(price - med) / med > 0.30:
                issues.append(
                    {
                        "item_id": item.id,
                        "sku_id": sku_id,
                        "issue_type": "price_deviation",
                        "severity": "warn",
                        "detail": {
                            "price": price,
                            "median": med,
                            "mad": mad,
                        },
                        "summary": f"价格 {price} 偏离历史中位数 {med} 过大",
                        "occurred_at": now,
                    }
                )

    # 5. 重复价跳变（单轮 ±50% 且下轮恢复）：简化为与上一快照对比
    if price is not None and price > 0:
        prev = (
            db.query(PriceSnapshot)
            .filter(
                PriceSnapshot.item_id == item.id,
                PriceSnapshot.sku_id == sku_id,
                PriceSnapshot.price.isnot(None),
            )
            .order_by(PriceSnapshot.snapshot_time.desc(), PriceSnapshot.id.desc())
            .offset(1)
            .first()
        )
        if prev and prev.price:
            prev_p = float(prev.price)
            if prev_p > 0 and abs(price - prev_p) / prev_p > 0.50:
                issues.append(
                    {
                        "item_id": item.id,
                        "sku_id": sku_id,
                        "issue_type": "duplicate_price",
                        "severity": "warn",
                        "detail": {
                            "price": price,
                            "prev_price": prev_p,
                        },
                        "summary": f"价格单轮跳变 {prev_p} -> {price}",
                        "occurred_at": now,
                    }
                )

    quality_flag = 1 if issues else 0
    return quality_flag, issues


def write_quality_issues(db: Session, issues: List[dict]) -> List[int]:
    """批量写入 quality_issue，并同步到站内消息中心。

    去重：同 item + sku + issue_type 已存在“待复核”记录时，不再重复创建/推送，
    避免同一异常在反复采集时刷屏。
    """
    from app.service import message as message_service
    from app.db.models import QualityIssue

    ids: List[int] = []
    for issue in issues:
        exists = (
            db.query(QualityIssue)
            .filter(
                QualityIssue.item_id == issue["item_id"],
                QualityIssue.sku_id == issue.get("sku_id"),
                QualityIssue.issue_type == issue["issue_type"],
                QualityIssue.review_status == "pending",
            )
            .first()
        )
        if exists:
            continue
        obj = quality_dao.create_quality_issue(db, issue)
        ids.append(obj.id)
        message_service.push_quality_message(db, obj)
        db.commit()
    return ids
