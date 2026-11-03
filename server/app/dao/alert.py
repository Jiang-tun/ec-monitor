from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.db.models import AlertRule, AlertLog


# ==================== 告警规则 ====================

def get_alert_rule(db: Session, rule_id: int) -> Optional[AlertRule]:
    """根据 ID 获取告警规则（未删除）。"""
    return db.query(AlertRule).filter(
        AlertRule.id == rule_id,
        AlertRule.is_deleted == 0,
    ).first()


def list_alert_rules(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    rule_type: Optional[str] = None,
    enabled: Optional[bool] = None,
    keyword: Optional[str] = None,
) -> Tuple[List[AlertRule], int]:
    """分页查询告警规则，支持目标类型/目标ID/规则类型/启用状态/关键词筛选。"""
    q = db.query(AlertRule).filter(AlertRule.is_deleted == 0)

    if target_type is not None:
        q = q.filter(AlertRule.target_type == target_type)
    if target_id is not None:
        q = q.filter(AlertRule.target_id == target_id)
    if rule_type is not None:
        q = q.filter(AlertRule.rule_type == rule_type)
    if enabled is not None:
        q = q.filter(AlertRule.enabled == (1 if enabled else 0))
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            or_(
                AlertRule.rule_name.ilike(like),
                AlertRule.rule_type.ilike(like),
            )
        )

    total = q.count()
    rows = q.order_by(AlertRule.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def create_alert_rule(db: Session, **kwargs) -> AlertRule:
    """新增告警规则。"""
    obj = AlertRule(**kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_alert_rule(db: Session, rule_id: int, **kwargs) -> Optional[AlertRule]:
    """更新告警规则字段。"""
    rule = get_alert_rule(db, rule_id)
    if not rule:
        return None
    for k, v in kwargs.items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    return rule


def create_alert_log(db: Session, **kwargs) -> AlertLog:
    """新增一条告警记录。"""
    obj = AlertLog(**kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def delete_alert_rule(db: Session, rule_id: int) -> bool:
    """软删除告警规则。"""
    rule = get_alert_rule(db, rule_id)
    if not rule:
        return False
    rule.is_deleted = 1
    db.commit()
    return True


def toggle_alert_rule(db: Session, rule_id: int, enabled: bool) -> Optional[AlertRule]:
    """启用/禁用告警规则。"""
    rule = get_alert_rule(db, rule_id)
    if not rule:
        return None
    rule.enabled = 1 if enabled else 0
    db.commit()
    db.refresh(rule)
    return rule


# ==================== 告警记录 ====================

def get_alert_log(db: Session, alert_id: int) -> Optional[AlertLog]:
    """根据主键获取告警记录。"""
    return db.query(AlertLog).filter(AlertLog.id == alert_id).first()


def list_alert_logs(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    rule_id: Optional[int] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    alert_type: Optional[str] = None,
    severity: Optional[str] = None,
    notify_status: Optional[str] = None,
    confirm_status: Optional[str] = None,
    keyword: Optional[str] = None,
) -> Tuple[List[AlertLog], int]:
    """分页查询告警记录，支持多条件筛选。"""
    q = db.query(AlertLog)

    if rule_id is not None:
        q = q.filter(AlertLog.rule_id == rule_id)
    if target_type is not None:
        q = q.filter(AlertLog.target_type == target_type)
    if target_id is not None:
        q = q.filter(AlertLog.target_id == target_id)
    if alert_type is not None:
        q = q.filter(AlertLog.alert_type == alert_type)
    if severity is not None:
        q = q.filter(AlertLog.severity == severity)
    if notify_status is not None:
        q = q.filter(AlertLog.notify_status == notify_status)
    if confirm_status is not None:
        q = q.filter(AlertLog.confirm_status == confirm_status)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            or_(
                AlertLog.message.ilike(like),
                AlertLog.target_id.ilike(like),
                AlertLog.sku_id.ilike(like),
                AlertLog.field_name.ilike(like),
                AlertLog.old_value.ilike(like),
                AlertLog.new_value.ilike(like),
            )
        )

    total = q.count()
    rows = q.order_by(AlertLog.alert_time.desc(), AlertLog.id.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return rows, total


def confirm_alert_log(
    db: Session,
    alert_id: int,
    confirm_status: str,
    confirmed_by: Optional[str] = None,
) -> Optional[AlertLog]:
    """确认/忽略告警。"""
    alert = get_alert_log(db, alert_id)
    if not alert:
        return None
    alert.confirm_status = confirm_status
    alert.confirmed_by = confirmed_by
    from datetime import datetime
    alert.confirmed_at = datetime.now()
    db.commit()
    db.refresh(alert)
    return alert


def batch_confirm_alert_logs(
    db: Session,
    alert_ids: List[int],
    confirm_status: str,
    confirmed_by: Optional[str] = None,
) -> int:
    """批量确认/忽略告警。"""
    q = db.query(AlertLog).filter(AlertLog.id.in_(alert_ids))
    count = 0
    for alert in q.all():
        alert.confirm_status = confirm_status
        alert.confirmed_by = confirmed_by
        from datetime import datetime
        alert.confirmed_at = datetime.now()
        count += 1
    db.commit()
    return count
