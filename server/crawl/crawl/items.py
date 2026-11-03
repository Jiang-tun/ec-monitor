"""采集数据契约（Spider → Pipeline → Node 回写 API 的唯一字段规范）。

字段语义与落库接口 ``POST /api/internal/snapshots``（server/app/api/internal.py）
以及 ``price_snapshot`` 表保持一致，字段名统一 snake_case。
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

# 缺失任意一项都会被质检判为 missing_field，且无法入库
# 注：stock 允许为空（NULL=未知/平台不展示库存），不列为必填
REQUIRED_FIELDS = ("item_id", "price", "title", "url", "page_status")

# 允许的枚举值
PRICE_BASES = ("list", "landed")
STRATEGIES = ("api", "page", "browser")


@dataclass
class CrawlItem:
    """一条采集结果。

    - 商品级：``sku_id=None``，价格为该商品口径价（多 SKU 时取最低价）
    - SKU 级：``sku_id`` 必填，价格/库存为该 SKU 的值
    """

    # 业务主键：系统内 monitor_item.id（不是平台商品ID）
    item_id: Optional[int] = None
    # 平台侧商品ID，仅用于排查/日志
    platform_item_id: Optional[str] = None
    sku_id: Optional[str] = None

    price: Optional[float] = None
    original_price: Optional[float] = None
    # -1 = 无限库存，None = 未知，0 = 售罄
    stock: Optional[int] = None
    title: Optional[str] = None
    url: Optional[str] = None
    page_status: Optional[int] = None

    price_basis: Optional[str] = None
    strategy_used: Optional[str] = None
    promotion_json: Optional[dict] = None

    proxy_id: Optional[int] = None
    node_id: Optional[str] = None
    task_id: Optional[str] = None
    platform_id: Optional[int] = None
    quality_flag: int = 0
    snapshot_time: Optional[datetime] = None

    extra: dict = field(default_factory=dict)

    def missing_required(self) -> list[str]:
        return [name for name in REQUIRED_FIELDS if getattr(self, name, None) is None]

    def to_payload(self) -> dict[str, Any]:
        """转为可 JSON 序列化的回写结构（datetime → ISO 8601）。"""
        data = asdict(self)
        extra = data.pop("extra", None) or {}
        data.pop("platform_item_id", None)
        if data.get("snapshot_time") is not None:
            data["snapshot_time"] = data["snapshot_time"].isoformat(timespec="seconds")
        else:
            data.pop("snapshot_time", None)
        if extra:
            promotion = dict(data.get("promotion_json") or {})
            promotion.update(extra)
            data["promotion_json"] = promotion
        return {k: v for k, v in data.items() if v is not None}

@dataclass
class SearchBatch:
    """一次关键词搜索的结果批次（由 Spider 产出，SearchResultPipeline 回写）。"""

    task_id: str
    platform_id: Optional[int]
    platform_code: str
    keyword: str
    items: list[dict] = field(default_factory=list)
    error: Optional[str] = None

    def to_payload(self) -> dict[str, Any]:
        payload = {"task_id": self.task_id, "items": self.items}
        if self.error:
            payload["error"] = self.error
        return payload


@dataclass
class SmsResult:
    """接码结果（取号 / 取码），由 SmsResultPipeline 回写后端。"""

    order_id: int
    action: str  # acquire / fetch_code
    status: str = "success"  # success / pending / failed
    phone: Optional[str] = None
    code: Optional[str] = None
    code_url: Optional[str] = None
    provider_order_id: Optional[str] = None
    raw: Optional[dict] = None
    error: Optional[str] = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "action": self.action,
            "status": self.status,
            "phone": self.phone,
            "code": self.code,
            "code_url": self.code_url,
            "provider_order_id": self.provider_order_id,
            "raw": self.raw or {},
            "error": self.error,
        }