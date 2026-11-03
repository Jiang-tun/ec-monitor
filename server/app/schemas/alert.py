from datetime import datetime
from typing import Any, Optional, List

from pydantic import BaseModel, Field, field_validator


# ==================== 告警规则 Schema =====
class AlertRuleBase(BaseModel):
    rule_name: str = Field(..., min_length=1, max_length=128)
    target_type: str = Field(..., pattern="^(item|sku|group|global|shop)$")
    target_id: Optional[str] = Field(default=None, max_length=64)
    rule_type: str = Field(..., pattern="^(price_below|price_above|pct_change|stock_out|stock_in|status_change|promo_change|title_change|parse_fail_ratio)$")
    condition_json: dict = Field(..., description="规则条件体 JSON")
    price_basis: Optional[str] = Field(default=None, max_length=16)
    threshold: Optional[float] = Field(default=None)
    min_delta_pct: float = Field(default=0)
    confirm_times: int = Field(default=1, ge=1)
    confirm_window_sec: int = Field(default=600, ge=0)
    silence_period_sec: int = Field(default=1800, ge=0)
    aggregation_sec: int = Field(default=60, ge=0)
    severity: str = Field(default="warn", pattern="^(info|warn|critical)$")
    enabled: int = Field(default=1, ge=0, le=1)
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None


class AlertRuleCreate(AlertRuleBase):
    pass


class AlertRuleUpdate(BaseModel):
    rule_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    target_type: Optional[str] = Field(default=None, pattern="^(item|sku|group|global|shop)$")
    target_id: Optional[str] = Field(default=None, max_length=64)
    rule_type: Optional[str] = Field(default=None, pattern="^(price_below|price_above|pct_change|stock_out|stock_in|status_change|promo_change|title_change|parse_fail_ratio)$")
    condition_json: Optional[dict] = None
    price_basis: Optional[str] = Field(default=None, max_length=16)
    threshold: Optional[float] = None
    min_delta_pct: Optional[float] = None
    confirm_times: Optional[int] = Field(default=None, ge=1)
    confirm_window_sec: Optional[int] = Field(default=None, ge=0)
    silence_period_sec: Optional[int] = Field(default=None, ge=0)
    aggregation_sec: Optional[int] = Field(default=None, ge=0)
    severity: Optional[str] = Field(default=None, pattern="^(info|warn|critical)$")
    enabled: Optional[int] = Field(default=None, ge=0, le=1)
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None


class AlertRuleOut(BaseModel):
    id: int
    rule_name: str
    target_type: str
    target_id: Optional[str]
    rule_type: str
    condition_json: dict
    price_basis: Optional[str]
    threshold: Optional[float]
    min_delta_pct: float
    confirm_times: int
    confirm_window_sec: int
    silence_period_sec: int
    aggregation_sec: int
    severity: str
    enabled: int
    effective_from: Optional[datetime]
    effective_to: Optional[datetime]
    last_fired_at: Optional[datetime]
    fire_count: int
    is_deleted: int
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ==================== 告警记录 Schema =====
class AlertLogOut(BaseModel):
    id: int
    rule_id: int
    rule_type: str
    target_type: str
    target_id: Optional[str]
    item_id: Optional[int]
    sku_id: Optional[str]
    platform_id: Optional[int]
    alert_type: str
    severity: str
    field_name: Optional[str]
    old_value: Optional[str]
    new_value: Optional[str]
    delta_pct: Optional[float]
    price_basis: Optional[str]
    message: str
    payload_json: Optional[dict]
    notify_status: str
    notify_detail: Optional[dict]
    notify_retry: int
    confirm_status: str
    confirmed_by: Optional[str]
    confirmed_at: Optional[datetime]
    remark: Optional[str]
    agg_key: Optional[str]
    alert_time: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


# ==================== 告警确认 Schema =====
class AlertConfirm(BaseModel):
    confirm_status: str = Field(..., pattern="^(confirmed|ignored)$")
    confirmed_by: Optional[str] = None


class AlertBatchConfirm(BaseModel):
    alert_ids: List[int]
    confirm_status: str = Field(..., pattern="^(confirmed|ignored)$")
    confirmed_by: Optional[str] = None
