from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import hashlib
import json
import re

from sqlalchemy.orm import Session

from app.dao import snapshot as snapshot_dao
from app.db.models import MonitorItem, PriceSnapshot


# ==================== 字段哈希算法（规范化 + MD5） ====================


def _canonical(field: str, value: Any, price_basis: Optional[str]) -> str:
    """对单个字段做规范化处理，消除字符串表示差异。"""
    if field in ("price", "original_price"):
        if value is None:
            return ""
        return f"{Decimal(str(value)):.2f}"
    if field == "stock":
        if value is None:
            return ""
        v = int(value)
        return "unlimited" if v == -1 else str(v)
    if field == "promotion_json":
        if value is None:
            return ""
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if field == "title":
        if value is None:
            return ""
        return re.sub(r"\s+", "", str(value))
    if field == "page_status":
        if value is None:
            return ""
        return str(value)
    return str(value) if value is not None else ""


def field_hash(field: str, value: Any, price_basis: Optional[str] = None) -> str:
    """计算单个字段的 MD5 摘要。"""
    return hashlib.md5(_canonical(field, value, price_basis).encode("utf-8")).hexdigest()


def row_hash(parsed: Dict[str, Any], price_basis: Optional[str] = None) -> tuple[str, Dict[str, str]]:
    """计算整行关键字段的哈希，同时产出字段级 map。

    参与字段固定顺序：price, original_price, stock, promotion_json, title, page_status
    """
    fields = (
        "price",
        "original_price",
        "stock",
        "promotion_json",
        "title",
        "page_status",
    )
    fmap: Dict[str, str] = {}
    parts = []
    for f in fields:
        v = parsed.get(f)
        fmap[f] = field_hash(f, v, price_basis)
        parts.append(fmap[f])
    payload = "|".join(parts)
    return hashlib.md5(payload.encode("utf-8")).hexdigest(), fmap


# ==================== 变更检测 ====================


def classify_change(
    field: str, old: Any, new: Any, page_status: Optional[int]
) -> Optional[str]:
    """根据字段变化判定 change_type，无变化返回 None。"""
    if field == "price":
        try:
            old_d = Decimal(str(old)) if old is not None else None
            new_d = Decimal(str(new)) if new is not None else None
        except Exception:
            old_d = new_d = None
        if old_d is not None and new_d is not None:
            if new_d < old_d:
                return "price_down"
            if new_d > old_d:
                return "price_up"
        return None
    if field == "stock":
        old_v = int(old) if old is not None else None
        new_v = int(new) if new is not None else None
        if old_v is not None and new_v is not None:
            if old_v > 0 and new_v == 0:
                return "stock_out"
            if old_v == 0 and new_v > 0:
                return "stock_in"
            if new_v == -1 or old_v == -1:
                return "stock_change"
        return None
    if field == "promotion_json":
        return "promo_change"
    if field == "title":
        return "title_change"
    if field == "page_status":
        if page_status in (404, 410):
            return "delist"
        return None
    return None


def delta_of(field: str, old: Any, new: Any) -> Optional[tuple[Optional[float], Optional[float]]]:
    """计算价格类字段的 delta_value 与 delta_pct。"""
    if field not in ("price", "original_price"):
        return None, None
    try:
        old_d = Decimal(str(old)) if old is not None else None
        new_d = Decimal(str(new)) if new is not None else None
    except Exception:
        return None, None
    if old_d is None or new_d is None or old_d == 0:
        return float(new_d) if new_d is not None else None, None
    delta_value = float(new_d - old_d)
    delta_pct = round(float((new_d - old_d) / old_d * 100), 2)
    return delta_value, delta_pct


def detect_changes(
    db: Session,
    item: MonitorItem,
    sku_id: Optional[str],
    curr: PriceSnapshot,
    prev: Optional[PriceSnapshot],
) -> List[dict]:
    """对比当前快照与上一条快照，返回变更记录列表（未入库）。"""
    if prev is None:
        return []

    curr_map = curr.field_hash_map or {}
    prev_map = prev.field_hash_map or {}

    changes: List[dict] = []
    fields = ("price", "original_price", "stock", "promotion_json", "title", "page_status")
    for f in fields:
        if curr_map.get(f) == prev_map.get(f):
            continue
        ctype = classify_change(f, getattr(prev, f), getattr(curr, f), curr.page_status)
        if not ctype:
            continue
        delta_value, delta_pct = delta_of(f, getattr(prev, f), getattr(curr, f))
        changes.append(
            {
                "item_id": item.id,
                "sku_id": sku_id,
                "field_name": f,
                "old_value": str(getattr(prev, f)) if getattr(prev, f) is not None else None,
                "new_value": str(getattr(curr, f)) if getattr(curr, f) is not None else None,
                "change_type": ctype,
                "delta_value": delta_value,
                "delta_pct": delta_pct,
                "old_hash": prev_map.get(f),
                "new_hash": curr_map.get(f),
                "snapshot_id": curr.id,
                "prev_snapshot_id": prev.id,
                "price_basis": curr.price_basis,
                "change_time": curr.snapshot_time,
            }
        )
    return changes


def process_snapshot_for_changes(
    db: Session,
    item: MonitorItem,
    sku_id: Optional[str],
    curr: PriceSnapshot,
) -> List[dict]:
    """对单条快照执行变更检测并入库 change_record，返回写入的记录。"""
    prev = snapshot_dao.get_latest_snapshot(
        db, item.id, sku_id, exclude_id=curr.id
    )
    changes = detect_changes(db, item, sku_id, curr, prev)
    created = []
    for ch in changes:
        created.append(snapshot_dao.create_change_record(db, ch))
    return [c.__dict__ for c in created]
