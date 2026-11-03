from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ==================== 代理池 Schema =====
class ProxyBase(BaseModel):
    ip: str = Field(..., min_length=1, max_length=64)
    port: int = Field(..., ge=1, le=65535)
    protocol: str = Field(default="http", pattern="^(http|https|socks5)$")
    username: Optional[str] = Field(default=None, max_length=64)
    password_enc: Optional[str] = Field(default=None, max_length=512)
    bind_site_group: str = Field(default="default", max_length=64)
    source: Optional[str] = Field(default=None, max_length=32)
    available: int = Field(default=1, ge=0, le=1)
    response_time: Optional[int] = Field(default=None, ge=0)
    fail_count: int = Field(default=0, ge=0)
    score: int = Field(default=100, ge=0)


class ProxyCreate(ProxyBase):
    pass


class ProxyUpdate(BaseModel):
    ip: Optional[str] = Field(default=None, min_length=1, max_length=64)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    protocol: Optional[str] = Field(default=None, pattern="^(http|https|socks5)$")
    username: Optional[str] = Field(default=None, max_length=64)
    password_enc: Optional[str] = Field(default=None, max_length=512)
    bind_site_group: Optional[str] = Field(default=None, max_length=64)
    source: Optional[str] = Field(default=None, max_length=32)
    available: Optional[int] = Field(default=None, ge=0, le=1)
    response_time: Optional[int] = Field(default=None, ge=0)
    fail_count: Optional[int] = Field(default=None, ge=0)
    score: Optional[int] = Field(default=None, ge=0)


class ProxyOut(BaseModel):
    id: int
    ip: str
    port: int
    protocol: str
    username: Optional[str]
    password_enc: Optional[str]
    bind_site_group: str
    source: Optional[str]
    available: int
    response_time: Optional[int]
    fail_count: int
    score: int
    is_active: int = 0
    last_check_at: Optional[datetime]
    last_used_at: Optional[datetime]
    is_deleted: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ==================== 代理测试请求 =====
class ProxyTestRequest(BaseModel):
    proxy_id: int
    test_url: Optional[str] = Field(default="http://example.com", max_length=512)
    timeout: int = Field(default=10, ge=1, le=60)


class ProxyTestResult(BaseModel):
    proxy_id: int
    success: bool
    response_time: Optional[int]
    status_code: Optional[int]
    error: Optional[str]
    tested_at: datetime


# ==================== 代理池统计 =====
class ProxyStatsOut(BaseModel):
    total: int
    enabled: int
    disabled: int
    avg_response_time: Optional[float]


# ==================== 批量录入 ====================
class ProxyBatchIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=20000)
    protocol: str = Field(default="http", pattern="^(http|https|socks5)$")
    bind_site_group: str = Field(default="default", max_length=64)
    source: Optional[str] = Field(default="batch-import", max_length=32)
