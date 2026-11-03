from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ===== 平台 =====
class PlatformOut(BaseModel):
    id: int
    name: str
    code: str
    adapter_config: Optional[dict] = None
    status: int
    sort: int

    model_config = {"from_attributes": True}


# ===== 商品基础 Schema =====
class MonitorItemBase(BaseModel):
    platform_id: int = Field(..., gt=0)
    shop_id: Optional[int] = Field(default=None, gt=0)
    item_id: str = Field(..., min_length=1, max_length=64)
    url: str = Field(..., min_length=8, max_length=1024)
    title: Optional[str] = Field(default=None, max_length=512)
    main_image: Optional[str] = Field(default=None, max_length=512)
    category_path: Optional[str] = Field(default=None, max_length=255)
    currency: str = Field(default="CNY", max_length=8)
    importance: int = Field(default=2, ge=1, le=3)
    crawl_freq: str = Field(default="30m", max_length=32)
    strategy: str = Field(default="auto", max_length=16)
    price_basis: Optional[str] = Field(default=None, max_length=16)
    remark: Optional[str] = Field(default=None, max_length=255)


class MonitorItemCreate(MonitorItemBase):
    pass


class MonitorItemUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=512)
    main_image: Optional[str] = Field(default=None, max_length=512)
    category_path: Optional[str] = Field(default=None, max_length=255)
    currency: Optional[str] = Field(default=None, max_length=8)
    importance: Optional[int] = Field(default=None, ge=1, le=3)
    crawl_freq: Optional[str] = Field(default=None, max_length=32)
    strategy: Optional[str] = Field(default=None, max_length=16)
    price_basis: Optional[str] = Field(default=None, max_length=16)
    remark: Optional[str] = Field(default=None, max_length=255)


class MonitorItemOut(MonitorItemBase):
    id: int
    monitor_status: int
    fail_count: int
    next_run_time: Optional[datetime] = None
    last_crawl_time: Optional[datetime] = None
    last_success_status: Optional[int] = None
    is_deleted: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ===== SKU =====
class MonitorSkuBase(BaseModel):
    sku_id: str = Field(..., min_length=1, max_length=64)
    spec_json: Optional[dict] = None
    price: Optional[float] = None
    original_price: Optional[float] = None
    stock: Optional[int] = None
    monitor_enabled: int = Field(default=1)


class MonitorSkuOut(MonitorSkuBase):
    id: int
    item_id: int
    last_field_hash: Optional[str] = None
    is_deleted: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SkuToggleIn(BaseModel):
    sku_ids: List[str] = Field(default_factory=list, description="为空表示全部 SKU")
    monitor_enabled: int = Field(..., ge=0, le=1)


# ===== 监控开关 =====
class MonitorSwitch(BaseModel):
    monitor_status: int = Field(..., ge=0, le=4)


# ===== 批量操作 =====
class BatchIdsIn(BaseModel):
    item_ids: List[int] = Field(..., min_length=1, description="商品主键 id 列表")


class BatchMonitorIn(BaseModel):
    item_ids: List[int] = Field(..., min_length=1, description="商品主键 id 列表")
    monitor_status: int = Field(..., ge=0, le=4)


# ===== 详情（含 SKU）=====
class LatestSnapshotOut(BaseModel):
    id: int
    sku_id: Optional[str] = None
    price: Optional[float] = None
    price_basis: Optional[str] = None
    original_price: Optional[float] = None
    stock: Optional[int] = None
    title: Optional[str] = None
    url: Optional[str] = None
    page_status: Optional[int] = None
    strategy_used: Optional[str] = None
    proxy_id: Optional[int] = None
    node_id: Optional[str] = None
    task_id: Optional[str] = None
    quality_flag: int = 0
    promotion_json: Optional[dict] = None
    snapshot_time: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CrawlLogOut(BaseModel):
    id: int
    task_id: str
    node_id: Optional[str] = None
    trigger_type: str
    total_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    dead_count: int = 0
    status: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    cost_ms: Optional[int] = None
    error_summary: Optional[str] = None

    model_config = {"from_attributes": True}


class MonitorItemDetailOut(MonitorItemOut):
    platform_name: Optional[str] = None
    skus: List[MonitorSkuOut] = Field(default_factory=list)
    latest_snapshot: Optional[LatestSnapshotOut] = None
    crawl_logs: List[CrawlLogOut] = Field(default_factory=list)


# ===== 价格历史 =====
class PricePointOut(BaseModel):
    time: str
    price: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    stock: Optional[int] = None


class PriceHistoryOut(BaseModel):
    item_id: int
    sku_id: Optional[str] = None
    granularity: str = "raw"
    points: List[PricePointOut] = Field(default_factory=list)


# ===== 变更记录 =====
class ChangeRecordOut(BaseModel):
    id: int
    item_id: int
    sku_id: Optional[str] = None
    field_name: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    change_type: str
    delta_value: Optional[float] = None
    delta_pct: Optional[float] = None
    price_basis: Optional[str] = None
    change_time: datetime

    model_config = {"from_attributes": True}


# ===== 批量导入 =====
class ImportErrorItem(BaseModel):
    row: int
    message: str


class ImportResultOut(BaseModel):
    total: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0
    errors: List[ImportErrorItem] = Field(default_factory=list)


# ===== 分页 =====
class ItemPage(BaseModel):
    items: List[MonitorItemOut]
    total: int
    page: int
    page_size: int

    model_config = {"from_attributes": True}
