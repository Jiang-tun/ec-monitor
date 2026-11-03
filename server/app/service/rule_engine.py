from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import hashlib
import json

from redis import Redis as RedisPy
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.dao import alert as alert_dao
from app.db.models import AlertRule, AlertLog, MonitorItem, PriceSnapshot
from app.service import message as message_service


settings = get_settings()


# ==================== 告警规则引擎（单次变更事件匹配） ====================


def _eval_condition(
    rule_type: str, condition_json: dict, curr: PriceSnapshot, prev: Optional[PriceSnapshot]
) -> bool:
    """根据 rule_type 与 condition_json 对当前快照做条件求值。"""
    op = condition_json.get("operator")
    value = condition_json.get("value")

    if rule_type == "price_below":
        price = curr.price
        if price is None:
            return False
        threshold = condition_json.get("threshold", value)
        if threshold is None:
            return False
        return Decimal(str(price)) <= Decimal(str(threshold))

    if rule_type == "price_above":
        price = curr.price
        if price is None:
            return False
        threshold = condition_json.get("threshold", value)
        if threshold is None:
            return False
        return Decimal(str(price)) >= Decimal(str(threshold))

    if rule_type == "pct_change":
        if prev is None or prev.price is None or curr.price is None:
            return False
        try:
            old_d = Decimal(str(prev.price))
            new_d = Decimal(str(curr.price))
        except Exception:
            return False
        if old_d == 0:
            return False
        delta_pct = float((new_d - old_d) / old_d * 100)
        direction = condition_json.get("direction")
        if direction == "down":
            return delta_pct <= float(value or 0)
        if direction == "up":
            return delta_pct >= float(value or 0)
        return abs(delta_pct) >= float(value or 0)

    if rule_type == "stock_out":
        return curr.stock == 0

    if rule_type == "stock_in":
        return curr.stock is not None and curr.stock > 0

    if rule_type == "status_change":
        return curr.page_status in (404, 410)

    if rule_type == "promo_change":
        return True

    if rule_type == "title_change":
        return True

    if rule_type == "parse_fail_ratio":
        return False

    return False


def _min_delta_ok(
    rule: AlertRule, curr: PriceSnapshot, prev: Optional[PriceSnapshot]
) -> bool:
    """最小变动幅度校验。"""
    if not rule.min_delta_pct:
        return True
    if rule.rule_type not in ("price_below", "price_above", "pct_change"):
        return True
    if prev is None or prev.price is None or curr.price is None:
        return False
    try:
        old_d = Decimal(str(prev.price))
        new_d = Decimal(str(curr.price))
    except Exception:
        return False
    if old_d == 0:
        return False
    delta_pct = abs(float((new_d - old_d) / old_d * 100))
    return delta_pct >= float(rule.min_delta_pct)


def _check_silence(
    rdb: RedisPy, rule: AlertRule, item_id: int, sku_id: Optional[str]
) -> bool:
    """静默期检查：Redis SETNX 锁，silence_period_sec 内重复命中不告警。"""
    if not rule.silence_period_sec:
        return False
    sku_part = sku_id or "item"
    key = f"alert:silence:{rule.id}:{item_id}:{sku_part}"
    # 已有静默键 -> 在静默期内
    if rdb.exists(key):
        return True
    return False


def _set_silence(rdb: RedisPy, rule: AlertRule, item_id: int, sku_id: Optional[str]) -> None:
    sku_part = sku_id or "item"
    key = f"alert:silence:{rule.id}:{item_id}:{sku_part}"
    rdb.setex(key, rule.silence_period_sec, "1")


def _confirm_incr(
    rdb: RedisPy, rule: AlertRule, item_id: int, sku_id: Optional[str], field: str
) -> bool:
    """连续确认计数：Redis INCR，达到 confirm_times 后返回 True 并清键。"""
    sku_part = sku_id or "item"
    key = f"alert:confirm:{rule.id}:{item_id}:{sku_part}:{field}"
    if rule.confirm_times <= 1:
        return True
    n = rdb.incr(key)
    if n == 1:
        rdb.expire(key, rule.confirm_window_sec)
    return n >= rule.confirm_times


def _agg_add(rdb: RedisPy, rule: AlertRule, item_id: int, sku_id: Optional[str], alert_id: int) -> bool:
    """聚合窗口：ZADD 到告警聚合集合，窗口首条返回 True（由调度任务负责冲刷）。"""
    sku_part = sku_id or "item"
    key = f"alert:agg:{rule.id}:{item_id}:{sku_part}"
    rdb.zadd(key, {str(alert_id): datetime.now().timestamp()})
    # 窗口内首条
    return rdb.zcard(key) == 1


def _agg_flush(rdb: RedisPy, rule: AlertRule, item_id: int, sku_id: Optional[str]) -> List[int]:
    """冲刷聚合窗口：返回本次合并的 alert_id 列表（首条保留，其余合并）。"""
    sku_part = sku_id or "item"
    key = f"alert:agg:{rule.id}:{item_id}:{sku_part}"
    members = rdb.zrange(key, 0, -1)
    if not members:
        return []
    ids = [int(m.decode() if isinstance(m, bytes) else m) for m in members]
    rdb.delete(key)
    return ids


def evaluate_change_event(
    db: Session,
    item: MonitorItem,
    sku_id: Optional[str],
    changes: List[dict],
    curr: PriceSnapshot,
    prev: Optional[PriceSnapshot],
) -> List[dict]:
    """对单次变更事件评估所有适用规则。

    流程（报告 5.4.2）：
      类型匹配 -> 口径检查 -> 条件求值 -> 最小幅度 -> 静默期 -> 连续确认 -> 聚合窗口 ->
      写 alert_log + 置静默键 -> 返回触发告警
    """
    triggered: List[dict] = []
    rdb = _get_redis()

    rules, _ = alert_dao.list_alert_rules(db, page=1, page_size=1000, enabled=True)

    # 作用域过滤：sku > item（简化：group/global 后续接入）
    applicable = []
    for rule in rules:
        if rule.target_type == "sku" and rule.target_id == sku_id:
            applicable.append(rule)
        elif rule.target_type == "item" and str(rule.target_id) == str(item.id):
            applicable.append(rule)

    for rule in applicable:
        # 口径检查
        if rule.price_basis and curr.price_basis and rule.price_basis != curr.price_basis:
            continue
        # 类型匹配
        matched = False
        for ch in changes:
            ct = ch.get("change_type")
            rt = rule.rule_type
            if ct == "price_down" and rt in ("price_below", "pct_change", "price_above"):
                matched = True
            elif ct == "price_up" and rt in ("price_above", "pct_change", "price_below"):
                matched = True
            elif ct == "stock_out" and rt == "stock_out":
                matched = True
            elif ct == "stock_in" and rt == "stock_in":
                matched = True
            elif ct == "delist" and rt == "status_change":
                matched = True
            elif ct == "promo_change" and rt == "promo_change":
                matched = True
            elif ct == "title_change" and rt == "title_change":
                matched = True
        if not matched:
            continue
        # 条件求值
        if not _eval_condition(rule.rule_type, rule.condition_json or {}, curr, prev):
            continue
        # 最小幅度
        if not _min_delta_ok(rule, curr, prev):
            continue
        # 静默期
        if _check_silence(rdb, rule, item.id, sku_id):
            continue
        # 连续确认
        ch = changes[0] if changes else {}
        field = ch.get("field_name", rule.rule_type)
        if not _confirm_incr(rdb, rule, item.id, sku_id, field):
            continue
        # 聚合窗口
        agg_first = _agg_add(rdb, rule, item.id, sku_id, 0)  # alert_id 写入后再补齐

        # 写告警记录
        alert_data = {
            "rule_id": rule.id,
            "rule_type": rule.rule_type,
            "target_type": rule.target_type,
            "target_id": rule.target_id,
            "item_id": item.id,
            "sku_id": sku_id,
            "platform_id": item.platform_id,
            "alert_type": ch.get("change_type", rule.rule_type),
            "severity": rule.severity,
            "field_name": ch.get("field_name"),
            "old_value": ch.get("old_value"),
            "new_value": ch.get("new_value"),
            "delta_pct": ch.get("delta_pct"),
            "price_basis": curr.price_basis,
            "message": (
                f"【{rule.severity.upper()}】{rule.rule_name}: "
                f"{ch.get('field_name','')} {ch.get('old_value','')} -> {ch.get('new_value','')}"
            ),
            "payload_json": {
                "rule_name": rule.rule_name,
                "item_id": item.id,
                "sku_id": sku_id,
                "changes": changes,
            },
            "notify_status": "pending",
            "confirm_status": "pending",
            "agg_key": f"{rule.id}:{item.id}:{sku_id or 'item'}",
            "alert_time": curr.snapshot_time,
        }
        alert = alert_dao.create_alert_log(db, **alert_data)

        # 写入站内消息中心（所有启用用户），并标记为已投递
        message_service.push_alert_message(db, alert)
        alert.notify_status = "success"
        alert.notify_detail = [{"channel": "message_center", "status": "success"}]
        db.add(alert)

        # 更新聚合窗口的 alert_id（将占位 0 替换为真实 id）
        if agg_first:
            sku_part = sku_id or "item"
            key = f"alert:agg:{rule.id}:{item.id}:{sku_part}"
            rdb.zrem(key, "0")
            rdb.zadd(key, {str(alert.id): datetime.now().timestamp()})

        # 置静默键
        _set_silence(rdb, rule, item.id, sku_id)

        # 更新规则触发计时
        rule.last_fired_at = datetime.now()
        rule.fire_count = (rule.fire_count or 0) + 1
        db.add(rule)

        triggered.append(
            {
                "id": alert.id,
                "rule_name": rule.rule_name,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "message": alert.message,
                "alert_time": alert.alert_time,
                "agg_key": alert.agg_key,
            }
        )

    db.commit()
    return triggered


def flush_aggregations(db: Session) -> int:
    """冲刷所有到期的聚合窗口：合并同一 agg_key 在窗口内的多条告警为一条推送。"""
    rdb = _get_redis()
    keys = rdb.keys("alert:agg:*")
    flushed = 0
    for key in keys:
        members = rdb.zrange(key, 0, -1)
        if not members:
            continue
        ids = [int(m.decode() if isinstance(m, bytes) else m) for m in members]
        if len(ids) <= 1:
            rdb.delete(key)
            continue
        # 取首条作为主告警，其余标记为已合并（suppressed）
        main_id = ids[0]
        for dup_id in ids[1:]:
            alert = (
                db.query(AlertLog).filter(AlertLog.id == dup_id).first()
            )
            if alert:
                alert.confirm_status = "ignored"
                alert.remark = f"aggregated into alert #{main_id}"
                db.add(alert)
        db.commit()
        rdb.delete(key)
        flushed += len(ids) - 1
    return flushed


def _get_redis() -> RedisPy:
    return RedisPy.from_url(settings.redis_url_compat)
