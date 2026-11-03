from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.response import ok
from app.schemas.alert import (
    AlertRuleCreate,
    AlertRuleUpdate,
    AlertRuleOut,
    AlertConfirm,
    AlertBatchConfirm,
    AlertLogOut,
)
from app.service import alert as alert_service

router = APIRouter(prefix="/api/alert-rules", tags=["alert-rules"])


# ==================== 告警规则 ====================
@router.get("")
def list_alert_rules(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("alert:rule")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    target_type: Optional[str] = Query(default=None),
    target_id: Optional[str] = Query(default=None),
    rule_type: Optional[str] = Query(default=None),
    enabled: Optional[bool] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
):
    """告警规则列表（权限：alert:rule）。"""
    items, total = alert_service.list_alert_rules_service(
        db=db,
        page=page,
        page_size=page_size,
        target_type=target_type,
        target_id=target_id,
        rule_type=rule_type,
        enabled=enabled,
        keyword=keyword,
    )
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@router.post("")
def create_alert_rule(
    data: AlertRuleCreate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("alert:rule")),
):
    """创建告警规则（权限：alert:rule）。"""
    rule = alert_service.create_alert_rule_service(db=db, data=data)
    return ok(rule.model_dump())


# ==================== 告警记录 ====================
@router.get("/alerts")
def list_alerts(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("alert:read")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    rule_id: Optional[int] = Query(default=None),
    target_type: Optional[str] = Query(default=None),
    target_id: Optional[str] = Query(default=None),
    alert_type: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    notify_status: Optional[str] = Query(default=None),
    confirm_status: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
):
    """告警记录列表（权限：alert:read）。"""
    items, total = alert_service.list_alert_logs_service(
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
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@router.put("/alerts/{alert_id}/confirm")
def confirm_alert(
    alert_id: int,
    data: AlertConfirm,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("alert:confirm")),
):
    """告警确认/忽略（权限：alert:confirm）。"""
    alert = alert_service.confirm_alert_log_service(db=db, alert_id=alert_id, data=data)
    return ok(alert.model_dump())


@router.post("/alerts/batch-confirm")
def batch_confirm_alerts(
    data: AlertBatchConfirm,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("alert:confirm")),
):
    """批量确认/忽略告警（权限：alert:confirm）。"""
    count = alert_service.batch_confirm_alert_logs_service(db=db, data=data)
    return ok({"updated": count, "confirm_status": data.confirm_status})


@router.get("/{rule_id}")
def get_alert_rule(
    rule_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("alert:rule")),
):
    """获取告警规则详情（权限：alert:rule）。"""
    rule = alert_service.get_alert_rule_service(db=db, rule_id=rule_id)
    return ok(rule.model_dump())


@router.put("/{rule_id}")
def update_alert_rule(
    rule_id: int,
    data: AlertRuleUpdate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("alert:rule")),
):
    """更新告警规则（权限：alert:rule）。"""
    rule = alert_service.update_alert_rule_service(db=db, rule_id=rule_id, data=data)
    return ok(rule.model_dump())


@router.delete("/{rule_id}")
def delete_alert_rule(
    rule_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("alert:rule")),
):
    """删除告警规则（软删，权限：alert:rule）。"""
    alert_service.delete_alert_rule_service(db=db, rule_id=rule_id)
    return ok({"deleted": True})


@router.put("/{rule_id}/toggle")
def toggle_alert_rule(
    rule_id: int,
    enabled: bool,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("alert:rule")),
):
    """启用/禁用告警规则（权限：alert:rule）。"""
    rule = alert_service.toggle_alert_rule_service(db=db, rule_id=rule_id, enabled=enabled)
    return ok({"id": rule.id, "enabled": rule.enabled})
