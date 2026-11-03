from datetime import datetime
from typing import List, Optional, Tuple, Dict

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.dao import alert as alert_dao
from app.db.models import AlertRule, AlertLog
from app.schemas.alert import (
    AlertRuleCreate,
    AlertRuleUpdate,
    AlertRuleOut,
    AlertLogOut,
    AlertConfirm,
    AlertBatchConfirm,
)


# ==================== 告警规则 ====================
def list_alert_rules_service(
    db: Session,
    page: int,
    page_size: int,
    target_type: Optional[str],
    target_id: Optional[str],
    rule_type: Optional[str],
    enabled: Optional[bool],
    keyword: Optional[str],
) -> Tuple[List[AlertRuleOut], int]:
    rows, total = alert_dao.list_alert_rules(
        db=db,
        page=page,
        page_size=page_size,
        target_type=target_type,
        target_id=target_id,
        rule_type=rule_type,
        enabled=enabled,
        keyword=keyword,
    )
    return [AlertRuleOut.model_validate(r) for r in rows], total


def get_alert_rule_service(db: Session, rule_id: int) -> AlertRuleOut:
    rule = alert_dao.get_alert_rule(db, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="告警规则不存在")
    return AlertRuleOut.model_validate(rule)


def create_alert_rule_service(db: Session, data: AlertRuleCreate) -> AlertRuleOut:
    # 唯一性校验：同目标+类型不应重复创建
    existing = db.query(AlertRule).filter(
        AlertRule.target_type == data.target_type,
        AlertRule.target_id == data.target_id,
        AlertRule.rule_type == data.rule_type,
        AlertRule.is_deleted == 0,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该目标已存在相同规则类型的告警规则，请勿重复添加",
        )
    rule = alert_dao.create_alert_rule(db, **data.model_dump())
    return AlertRuleOut.model_validate(rule)


def update_alert_rule_service(db: Session, rule_id: int, data: AlertRuleUpdate) -> AlertRuleOut:
    rule = alert_dao.get_alert_rule(db, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="告警规则不存在")
    update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    rule = alert_dao.update_alert_rule(db, rule_id, **update_data)
    return AlertRuleOut.model_validate(rule)


def delete_alert_rule_service(db: Session, rule_id: int) -> None:
    ok = alert_dao.delete_alert_rule(db, rule_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="告警规则不存在")


def toggle_alert_rule_service(db: Session, rule_id: int, enabled: bool) -> AlertRuleOut:
    rule = alert_dao.toggle_alert_rule(db, rule_id, enabled)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="告警规则不存在")
    return AlertRuleOut.model_validate(rule)


# ==================== 告警记录 ====================
def list_alert_logs_service(
    db: Session,
    page: int,
    page_size: int,
    rule_id: Optional[int],
    target_type: Optional[str],
    target_id: Optional[str],
    alert_type: Optional[str],
    severity: Optional[str],
    notify_status: Optional[str],
    confirm_status: Optional[str],
    keyword: Optional[str] = None,
) -> Tuple[List[AlertLogOut], int]:
    rows, total = alert_dao.list_alert_logs(
        db=db,
        page=page,
        page_size=page_size,
        rule_id=rule_id,
        target_type=target_type,
        target_id=target_id,
        alert_type=alert_type,
        severity=severity,
        notify_status=notify_status,
        confirm_status=confirm_status,
        keyword=keyword,
    )
    return [AlertLogOut.model_validate(r) for r in rows], total


def confirm_alert_log_service(
    db: Session,
    alert_id: int,
    data: AlertConfirm,
) -> AlertLogOut:
    alert = alert_dao.confirm_alert_log(
        db=db,
        alert_id=alert_id,
        confirm_status=data.confirm_status,
        confirmed_by=data.confirmed_by,
    )
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="告警记录不存在")
    return AlertLogOut.model_validate(alert)


def batch_confirm_alert_logs_service(
    db: Session,
    data: AlertBatchConfirm,
) -> int:
    count = alert_dao.batch_confirm_alert_logs(
        db=db,
        alert_ids=data.alert_ids,
        confirm_status=data.confirm_status,
        confirmed_by=data.confirmed_by,
    )
    return count
