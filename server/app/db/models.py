from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _pk() -> Mapped[int]:
    return mapped_column(BigInteger, primary_key=True, autoincrement=True)


class Platform(Base):
    """平台字典表"""

    __tablename__ = "platform"

    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(String(64), comment="平台名称")
    code: Mapped[str] = mapped_column(String(32), unique=True, comment="平台编码")
    adapter_config: Mapped[Optional[dict]] = mapped_column(JSON, comment="适配器配置")
    status: Mapped[int] = mapped_column(SmallInteger, default=1, comment="状态：1-启用 0-停用")
    sort: Mapped[int] = mapped_column(Integer, default=0, comment="排序")
    remark: Mapped[Optional[str]] = mapped_column(String(255), comment="描述")
    is_deleted: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class MonitorItem(Base):
    """监控商品表"""

    __tablename__ = "monitor_item"
    __table_args__ = (UniqueConstraint("platform_id", "item_id", name="uk_plat_item"),)

    id: Mapped[int] = _pk()
    platform_id: Mapped[int] = mapped_column(BigInteger, comment="平台ID")
    shop_id: Mapped[Optional[int]] = mapped_column(BigInteger, comment="店铺ID")
    item_id: Mapped[str] = mapped_column(String(64), comment="平台商品ID")
    url: Mapped[str] = mapped_column(String(1024), comment="商品链接")
    title: Mapped[Optional[str]] = mapped_column(String(512), comment="商品标题")
    main_image: Mapped[Optional[str]] = mapped_column(String(512), comment="主图URL")
    category_path: Mapped[Optional[str]] = mapped_column(String(255), comment="类目路径")
    currency: Mapped[str] = mapped_column(String(8), default="CNY", comment="货币单位")
    monitor_status: Mapped[int] = mapped_column(
        SmallInteger, default=1, comment="监控状态：1-监控中 0-暂停 2-疑似下架 3-已下架 4-待激活"
    )
    status_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="状态变更时间"
    )
    importance: Mapped[int] = mapped_column(
        SmallInteger, default=2, comment="重要度：1-核心 2-普通 3-长尾"
    )
    crawl_freq: Mapped[str] = mapped_column(
        String(32), default="30m", comment="采集频率：5m/30m/1h/daily"
    )
    strategy: Mapped[str] = mapped_column(
        String(16), default="auto", comment="采集策略：api/page/browser/auto"
    )
    price_basis: Mapped[Optional[str]] = mapped_column(
        String(16), comment="价格口径：list/landed"
    )
    fail_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="连续失败次数"
    )
    next_run_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="下次采集时间"
    )
    last_crawl_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="最近一次采集时间"
    )
    last_success_status: Mapped[Optional[int]] = mapped_column(
        SmallInteger, comment="最近一次采集结果：1-成功 0-失败"
    )
    remark: Mapped[Optional[str]] = mapped_column(String(255), comment="备注")
    is_deleted: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class MonitorSku(Base):
    """监控SKU表"""

    __tablename__ = "monitor_sku"
    __table_args__ = (UniqueConstraint("item_id", "sku_id", name="uk_item_sku"),)

    id: Mapped[int] = _pk()
    item_id: Mapped[int] = mapped_column(BigInteger, comment="监控商品ID")
    sku_id: Mapped[str] = mapped_column(String(64), comment="平台SKU ID")
    spec_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="规格JSON")
    price: Mapped[Optional[float]] = mapped_column(comment="最近一次采集价格")
    original_price: Mapped[Optional[float]] = mapped_column(comment="划线价/原价")
    stock: Mapped[Optional[int]] = mapped_column(
        Integer, comment="库存：-1表示无尽库存 NULL未知"
    )
    monitor_enabled: Mapped[int] = mapped_column(
        SmallInteger, default=1, comment="监控开关：1-开启 0-停用"
    )
    last_field_hash: Mapped[Optional[str]] = mapped_column(
        String(32), comment="最近快照字段摘要"
    )
    is_deleted: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PriceSnapshot(Base):
    """价格库存快照表"""

    __tablename__ = "price_snapshot"

    id: Mapped[int] = _pk()
    item_id: Mapped[int] = mapped_column(BigInteger, comment="监控商品ID")
    sku_id: Mapped[Optional[str]] = mapped_column(
        String(64), comment="平台SKU ID（NULL=商品级快照）"
    )
    platform_id: Mapped[int] = mapped_column(BigInteger, comment="平台ID")
    price: Mapped[Optional[float]] = mapped_column(comment="口径价")
    price_basis: Mapped[Optional[str]] = mapped_column(
        String(16), comment="快照固化价格口径：list/landed"
    )
    original_price: Mapped[Optional[float]] = mapped_column(comment="划线价/原价")
    stock: Mapped[Optional[int]] = mapped_column(
        Integer, comment="库存：-1无尽库存 NULL未知"
    )
    promotion_json: Mapped[Optional[dict]] = mapped_column(
        JSON, comment="促销结构JSON"
    )
    title: Mapped[Optional[str]] = mapped_column(String(512), comment="标题")
    url: Mapped[Optional[str]] = mapped_column(String(1024), comment="商品链接")
    page_status: Mapped[Optional[int]] = mapped_column(
        SmallInteger, comment="HTTP状态码：404/410用于下架判定"
    )
    strategy_used: Mapped[Optional[str]] = mapped_column(
        String(16), comment="采集策略：api/page/browser"
    )
    proxy_id: Mapped[Optional[int]] = mapped_column(BigInteger, comment="代理ID")
    node_id: Mapped[Optional[str]] = mapped_column(String(64), comment="采集节点ID")
    task_id: Mapped[Optional[str]] = mapped_column(String(64), comment="调度批次号")
    field_hash: Mapped[str] = mapped_column(
        String(32), comment="规范化关键字段MD5"
    )
    field_hash_map: Mapped[Optional[dict]] = mapped_column(
        JSON, comment="字段级哈希映射"
    )
    quality_flag: Mapped[int] = mapped_column(
        SmallInteger, default=0, comment="质量标记：0正常 1异常"
    )
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, comment="采集时刻")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AlertRule(Base):
    """告警规则表"""

    __tablename__ = "alert_rule"

    id: Mapped[int] = _pk()
    rule_name: Mapped[str] = mapped_column(String(128), comment="规则名称")
    target_type: Mapped[str] = mapped_column(
        String(16), comment="目标类型：item/sku/group/global/shop"
    )
    target_id: Mapped[Optional[str]] = mapped_column(String(64), comment="目标ID")
    rule_type: Mapped[str] = mapped_column(
        String(32),
        comment="规则类型：price_below/price_above/pct_change/stock_out/stock_in/status_change/promo_change/title_change/parse_fail_ratio",
    )
    condition_json: Mapped[dict] = mapped_column(JSON, comment="规则条件体JSON")
    price_basis: Mapped[Optional[str]] = mapped_column(
        String(16), comment="价格口径：list/landed"
    )
    threshold: Mapped[Optional[float]] = mapped_column(comment="主阈值")
    min_delta_pct: Mapped[float] = mapped_column(
        default=0, comment="最小变动幅度（%）"
    )
    confirm_times: Mapped[int] = mapped_column(
        Integer, default=1, comment="连续确认次数"
    )
    confirm_window_sec: Mapped[int] = mapped_column(
        Integer, default=600, comment="连续确认窗口秒数"
    )
    silence_period_sec: Mapped[int] = mapped_column(
        Integer, default=1800, comment="静默期秒数"
    )
    aggregation_sec: Mapped[int] = mapped_column(
        Integer, default=60, comment="告警聚合窗口秒数"
    )
    severity: Mapped[str] = mapped_column(
        String(16), default="warn", comment="严重度：info/warn/critical"
    )
    enabled: Mapped[int] = mapped_column(
        SmallInteger, default=1, comment="启用状态：1-启用 0-停用"
    )
    effective_from: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="生效时间"
    )
    effective_to: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="失效时间"
    )
    last_fired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="最后触发时间"
    )
    fire_count: Mapped[int] = mapped_column(Integer, default=0, comment="触发次数")
    is_deleted: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), comment="创建人")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AlertLog(Base):
    """告警记录表"""

    __tablename__ = "alert_log"

    id: Mapped[int] = _pk()
    rule_id: Mapped[int] = mapped_column(BigInteger, comment="规则ID")
    rule_type: Mapped[str] = mapped_column(String(32), comment="规则类型")
    target_type: Mapped[str] = mapped_column(
        String(16), comment="目标类型：item/sku/group/global/shop"
    )
    target_id: Mapped[Optional[str]] = mapped_column(String(64), comment="目标ID")
    item_id: Mapped[Optional[int]] = mapped_column(BigInteger, comment="监控商品ID")
    sku_id: Mapped[Optional[str]] = mapped_column(String(64), comment="SKU ID")
    platform_id: Mapped[Optional[int]] = mapped_column(BigInteger, comment="平台ID")
    alert_type: Mapped[str] = mapped_column(String(32), comment="告警类型")
    severity: Mapped[str] = mapped_column(
        String(16), default="warn", comment="严重度：info/warn/critical"
    )
    field_name: Mapped[Optional[str]] = mapped_column(String(32), comment="变更字段名")
    old_value: Mapped[Optional[str]] = mapped_column(String(1024), comment="旧值")
    new_value: Mapped[Optional[str]] = mapped_column(String(1024), comment="新值")
    delta_pct: Mapped[Optional[float]] = mapped_column(comment="变动百分比")
    price_basis: Mapped[Optional[str]] = mapped_column(String(16), comment="价格口径")
    message: Mapped[str] = mapped_column(String(512), comment="告警摘要")
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="推送报文JSON")
    notify_status: Mapped[str] = mapped_column(
        String(16), default="pending", comment="通知状态：pending/success/failed/partial"
    )
    notify_detail: Mapped[Optional[list]] = mapped_column(
        JSON, comment="推送详情JSON数组"
    )
    notify_retry: Mapped[int] = mapped_column(
        Integer, default=0, comment="通知重试次数"
    )
    confirm_status: Mapped[str] = mapped_column(
        String(16), default="pending", comment="确认状态：pending/confirmed/ignored"
    )
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(64), comment="确认人")
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="确认时间"
    )
    remark: Mapped[Optional[str]] = mapped_column(String(512), comment="备注")
    agg_key: Mapped[Optional[str]] = mapped_column(String(128), comment="聚合键：rule:target:sku")
    alert_time: Mapped[datetime] = mapped_column(DateTime, comment="告警时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DeadLetter(Base):
    """死信队列表"""

    __tablename__ = "dead_letter"

    id: Mapped[int] = _pk()
    item_id: Mapped[int] = mapped_column(BigInteger, comment="监控商品ID")
    sku_id: Mapped[Optional[str]] = mapped_column(String(64), comment="平台SKU标识")
    fail_stage: Mapped[str] = mapped_column(
        String(16), comment="失败阶段：fetch/parse/render/write"
    )
    fail_reason: Mapped[str] = mapped_column(
        String(512), comment="失败原因：错误归类码+摘要"
    )
    raw_error: Mapped[Optional[str]] = mapped_column(Text, comment="截断后的原始异常")
    fail_strategy: Mapped[Optional[str]] = mapped_column(
        String(16), comment="失败策略"
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, comment="重试次数")
    max_retry: Mapped[int] = mapped_column(Integer, default=5, comment="最大重试次数")
    status: Mapped[str] = mapped_column(
        String(16), default="pending", comment="状态：pending/processing/resolved/discarded"
    )
    first_fail_at: Mapped[datetime] = mapped_column(DateTime, comment="首次失败时间")
    last_fail_at: Mapped[datetime] = mapped_column(DateTime, comment="最近失败时间")
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="解决时间"
    )
    resolved_by: Mapped[Optional[str]] = mapped_column(String(64), comment="解决人")
    task_id: Mapped[Optional[str]] = mapped_column(String(64), comment="调度批次号")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ChangeRecord(Base):
    """字段级变更记录"""

    __tablename__ = "change_record"

    id: Mapped[int] = _pk()
    item_id: Mapped[int] = mapped_column(BigInteger, comment="监控商品ID")
    sku_id: Mapped[Optional[str]] = mapped_column(String(64), comment="平台SKU标识")
    field_name: Mapped[str] = mapped_column(String(32), comment="变更字段名")
    old_value: Mapped[Optional[str]] = mapped_column(String(1024), comment="旧值")
    new_value: Mapped[Optional[str]] = mapped_column(String(1024), comment="新值")
    change_type: Mapped[str] = mapped_column(String(32), comment="变更类型")
    delta_value: Mapped[Optional[float]] = mapped_column(comment="变动金额")
    delta_pct: Mapped[Optional[float]] = mapped_column(comment="变动百分比")
    old_hash: Mapped[Optional[str]] = mapped_column(String(32), comment="旧值哈希")
    new_hash: Mapped[Optional[str]] = mapped_column(String(32), comment="新值哈希")
    snapshot_id: Mapped[Optional[int]] = mapped_column(BigInteger, comment="关联新快照ID")
    prev_snapshot_id: Mapped[Optional[int]] = mapped_column(BigInteger, comment="关联旧快照ID")
    price_basis: Mapped[Optional[str]] = mapped_column(String(16), comment="价格口径")
    change_time: Mapped[datetime] = mapped_column(DateTime, comment="变更时刻")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class QualityIssue(Base):
    """数据质量异常"""

    __tablename__ = "quality_issue"

    id: Mapped[int] = _pk()
    item_id: Mapped[int] = mapped_column(BigInteger, comment="监控商品ID")
    sku_id: Mapped[Optional[str]] = mapped_column(String(64), comment="平台SKU标识")
    snapshot_id: Mapped[Optional[int]] = mapped_column(BigInteger, comment="关联快照ID")
    issue_type: Mapped[str] = mapped_column(
        String(32),
        comment="异常类型：price_out_of_range/price_deviation/missing_field/parse_fail_ratio/duplicate_price/stock_anomaly",
    )
    severity: Mapped[str] = mapped_column(
        String(16), default="warn", comment="严重度：info/warn/critical"
    )
    detail: Mapped[Optional[dict]] = mapped_column(JSON, comment="异常详情JSON")
    summary: Mapped[Optional[str]] = mapped_column(String(512), comment="摘要")
    review_status: Mapped[str] = mapped_column(
        String(16), default="pending", comment="复核状态：pending/confirmed/ignored/fixed"
    )
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(64), comment="复核人")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="复核时间")
    review_note: Mapped[Optional[str]] = mapped_column(String(512), comment="复核备注")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, comment="发生时刻")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ItemGroup(Base):
    """商品组（跨平台比价）"""

    __tablename__ = "item_group"

    id: Mapped[int] = _pk()
    group_name: Mapped[str] = mapped_column(String(128), comment="组名称")
    group_code: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, comment="业务编码/SPU编码"
    )
    base_item_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment="基准商品ID（比价锚点）"
    )
    owner: Mapped[Optional[str]] = mapped_column(String(64), comment="负责人")
    status: Mapped[int] = mapped_column(
        SmallInteger, default=1, comment="状态：1启用 0停用"
    )
    is_deleted: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ItemGroupRel(Base):
    """商品组关联"""

    __tablename__ = "item_group_rel"
    __table_args__ = (UniqueConstraint("group_id", "item_id", name="uk_group_item"),)

    id: Mapped[int] = _pk()
    group_id: Mapped[int] = mapped_column(BigInteger, comment="组ID")
    item_id: Mapped[int] = mapped_column(BigInteger, comment="monitor_item.id")
    platform_id: Mapped[int] = mapped_column(BigInteger, comment="平台ID")
    is_base: Mapped[int] = mapped_column(
        SmallInteger, default=0, comment="是否基准商品"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SysUser(Base):
    """用户"""

    __tablename__ = "sys_user"

    id: Mapped[int] = _pk()
    username: Mapped[str] = mapped_column(String(64), unique=True, comment="用户名")
    password_hash: Mapped[str] = mapped_column(
        String(255), comment="argon2id 密码哈希"
    )
    nickname: Mapped[Optional[str]] = mapped_column(String(64), comment="昵称")
    email: Mapped[Optional[str]] = mapped_column(String(128), comment="邮箱")
    status: Mapped[int] = mapped_column(SmallInteger, default=1, comment="状态：1启用 0停用")
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="最后登录时间"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SysRole(Base):
    """角色"""

    __tablename__ = "sys_role"

    id: Mapped[int] = _pk()
    role_code: Mapped[str] = mapped_column(String(32), unique=True, comment="角色编码")
    role_name: Mapped[str] = mapped_column(String(64), comment="角色名称")
    permissions: Mapped[Optional[list]] = mapped_column(JSON, comment="权限点数组")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SysUserRole(Base):
    """用户角色关联"""

    __tablename__ = "sys_user_role"

    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(BigInteger, comment="用户ID")
    role_id: Mapped[int] = mapped_column(BigInteger, comment="角色ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Proxy(Base):
    """代理池"""

    __tablename__ = "proxy"

    id: Mapped[int] = _pk()
    ip: Mapped[str] = mapped_column(String(64), comment="代理IP")
    port: Mapped[int] = mapped_column(Integer, comment="代理端口")
    protocol: Mapped[str] = mapped_column(
        String(8), default="http", comment="协议：http/https/socks5"
    )
    username: Mapped[Optional[str]] = mapped_column(String(64), comment="用户名")
    password_enc: Mapped[Optional[str]] = mapped_column(String(512), comment="加密密码")
    bind_site_group: Mapped[str] = mapped_column(
        String(64), default="default", comment="绑定站点分组"
    )
    source: Mapped[Optional[str]] = mapped_column(String(32), comment="供应商/自建")
    available: Mapped[int] = mapped_column(
        SmallInteger, default=1, comment="是否可用：1可用 0不可用"
    )
    response_time: Mapped[Optional[int]] = mapped_column(Integer, comment="最近检测耗时ms")
    fail_count: Mapped[int] = mapped_column(Integer, default=0, comment="连续失败次数")
    score: Mapped[int] = mapped_column(SmallInteger, default=100, comment="可用性评分")
    last_check_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="最后检测时间"
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="最后使用时间"
    )
    is_active: Mapped[int] = mapped_column(
        SmallInteger, default=0, comment="是否用于采集(Playwright)：1是 0否（全局仅一个）"
    )
    is_deleted: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("ip", "port", name="uk_ip_port"),)


class CrawlTaskLog(Base):
    """采集任务批次记录"""

    __tablename__ = "crawl_task_log"

    id: Mapped[int] = _pk()
    task_id: Mapped[str] = mapped_column(String(64), comment="批次号")
    shard: Mapped[Optional[int]] = mapped_column(SmallInteger, comment="批次分组号")
    node_id: Mapped[Optional[str]] = mapped_column(String(64), comment="归集节点")
    trigger_type: Mapped[str] = mapped_column(
        String(16), comment="触发类型：schedule/manual/retry/backfill"
    )
    freq_group: Mapped[Optional[str]] = mapped_column(String(32), comment="频率组")
    total_count: Mapped[int] = mapped_column(Integer, default=0, comment="总数")
    success_count: Mapped[int] = mapped_column(Integer, default=0, comment="成功数")
    fail_count: Mapped[int] = mapped_column(Integer, default=0, comment="失败数")
    dead_count: Mapped[int] = mapped_column(Integer, default=0, comment="死信数")
    strategy_stat: Mapped[Optional[dict]] = mapped_column(JSON, comment="策略分布统计")
    status: Mapped[str] = mapped_column(
        String(16), default="running", comment="状态：running/success/partial/failed"
    )
    start_time: Mapped[datetime] = mapped_column(DateTime, comment="开始时间")
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="结束时间")
    cost_ms: Mapped[Optional[int]] = mapped_column(Integer, comment="耗时ms")
    error_summary: Mapped[Optional[str]] = mapped_column(String(512), comment="错误摘要")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("task_id", name="uk_task"),)


class SysDict(Base):
    """字典类型表"""

    __tablename__ = "sys_dict"

    id: Mapped[int] = _pk()
    dict_name: Mapped[str] = mapped_column(String(64), comment="字典名称")
    dict_code: Mapped[str] = mapped_column(String(64), unique=True, comment="字典编码")
    description: Mapped[Optional[str]] = mapped_column(String(255), comment="描述")
    status: Mapped[int] = mapped_column(SmallInteger, default=1, comment="状态：1启用 0停用")
    sort: Mapped[int] = mapped_column(Integer, default=0, comment="排序")
    is_deleted: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SysDictItem(Base):
    """字典项表"""

    __tablename__ = "sys_dict_item"

    id: Mapped[int] = _pk()
    dict_code: Mapped[str] = mapped_column(String(64), comment="字典编码")
    dict_label: Mapped[str] = mapped_column(String(64), comment="字典标签")
    dict_value: Mapped[str] = mapped_column(String(255), comment="字典值")
    sort: Mapped[int] = mapped_column(Integer, default=0, comment="排序")
    status: Mapped[int] = mapped_column(
        SmallInteger, default=1, comment="字典项状态：1启用 0停用"
    )
    is_deleted: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class OperationLog(Base):
    """操作审计日志"""

    __tablename__ = "operation_log"

    id: Mapped[int] = _pk()
    operator: Mapped[str] = mapped_column(String(64), comment="操作人")
    action: Mapped[str] = mapped_column(
        String(64), comment="动作：item.create/rule.update/template.publish/..."
    )
    target_type: Mapped[Optional[str]] = mapped_column(String(32), comment="目标类型")
    target_id: Mapped[Optional[str]] = mapped_column(String(64), comment="目标ID")
    before_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="变更前")
    after_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="变更后")
    ip: Mapped[Optional[str]] = mapped_column(String(64), comment="来源IP")
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), comment="链路ID")
    result: Mapped[str] = mapped_column(
        String(16), default="success", comment="结果：success/failed"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SearchTask(Base):
    """关键词搜索采集任务"""

    __tablename__ = "search_task"

    id: Mapped[int] = _pk()
    task_id: Mapped[str] = mapped_column(String(64), unique=True, comment="任务批次号")
    platform_id: Mapped[int] = mapped_column(BigInteger, comment="平台ID")
    platform_code: Mapped[str] = mapped_column(String(32), comment="平台编码")
    keyword: Mapped[str] = mapped_column(String(128), comment="搜索关键词")
    limit_count: Mapped[int] = mapped_column(Integer, default=20, comment="取列表前N条")
    status: Mapped[str] = mapped_column(
        String(16),
        default="pending",
        comment="pending/running/collected/success/failed",
    )
    total_count: Mapped[int] = mapped_column(Integer, default=0, comment="列表返回条数")
    new_count: Mapped[int] = mapped_column(Integer, default=0, comment="候选待确认数")
    dup_count: Mapped[int] = mapped_column(Integer, default=0, comment="重复数")
    added_count: Mapped[int] = mapped_column(Integer, default=0, comment="确认入库数")
    error: Mapped[Optional[str]] = mapped_column(String(512), comment="失败原因")
    created_by: Mapped[Optional[str]] = mapped_column(String(64), comment="创建人")
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="完成时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SearchTaskItem(Base):
    """关键词去重记录：同一平台+关键词下出现过的商品"""

    __tablename__ = "search_task_item"
    __table_args__ = (
        UniqueConstraint(
            "platform_id", "keyword", "platform_item_id", name="uk_search_seen"
        ),
    )

    id: Mapped[int] = _pk()
    platform_id: Mapped[int] = mapped_column(BigInteger, comment="平台ID")
    keyword: Mapped[str] = mapped_column(String(128), comment="搜索关键词")
    platform_item_id: Mapped[str] = mapped_column(
        String(128), comment="平台商品ID"
    )
    monitor_item_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment="对应监控商品ID（已存在则为空或原ID）"
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="首次出现时间"
    )


class SearchCandidate(Base):
    """关键词采集候选商品（等待用户筛选确认后入库）"""

    __tablename__ = "search_candidate"
    __table_args__ = (
        UniqueConstraint("task_id", "platform_item_id", name="uk_task_candidate"),
    )

    id: Mapped[int] = _pk()
    task_id: Mapped[str] = mapped_column(String(64), comment="搜索任务批次号")
    platform_id: Mapped[int] = mapped_column(BigInteger, comment="平台ID")
    keyword: Mapped[str] = mapped_column(String(128), comment="搜索关键词")
    platform_item_id: Mapped[str] = mapped_column(String(128), comment="平台商品ID")
    title: Mapped[Optional[str]] = mapped_column(String(512), comment="标题")
    url: Mapped[Optional[str]] = mapped_column(String(1024), comment="商品链接")
    image: Mapped[Optional[str]] = mapped_column(String(512), comment="主图")
    price: Mapped[Optional[float]] = mapped_column(comment="列表价")
    original_price: Mapped[Optional[float]] = mapped_column(comment="原价")
    status: Mapped[str] = mapped_column(
        String(16), default="pending", comment="pending/added/skipped"
    )
    monitor_item_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment="入库后的监控商品ID"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SysMessage(Base):
    """站内消息（右上角消息中心）"""

    __tablename__ = "sys_message"

    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(BigInteger, comment="接收用户ID")
    title: Mapped[str] = mapped_column(String(128), comment="标题")
    content: Mapped[Optional[str]] = mapped_column(Text, comment="内容")
    msg_type: Mapped[str] = mapped_column(
        String(16), default="system", comment="类型：alert/quality/system"
    )
    level: Mapped[str] = mapped_column(
        String(16), default="info", comment="级别：info/warn/critical"
    )
    link: Mapped[Optional[str]] = mapped_column(String(255), comment="点击跳转路由")
    ref_type: Mapped[Optional[str]] = mapped_column(String(32), comment="关联对象类型")
    ref_id: Mapped[Optional[str]] = mapped_column(String(64), comment="关联对象ID")
    is_read: Mapped[int] = mapped_column(
        SmallInteger, default=0, comment="0未读 1已读"
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="阅读时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class PlatformLogin(Base):
    """平台手机号验证码登录会话"""

    __tablename__ = "platform_login"

    id: Mapped[int] = _pk()
    platform_id: Mapped[int] = mapped_column(BigInteger, comment="平台ID")
    platform_code: Mapped[str] = mapped_column(String(32), comment="平台编码")
    phone: Mapped[str] = mapped_column(String(32), comment="手机号")
    status: Mapped[str] = mapped_column(
        String(16),
        default="pending",
        comment="pending/code_sent/verifying/success/failed/expired/cancelled",
    )
    error: Mapped[Optional[str]] = mapped_column(String(512), comment="失败原因")
    cookies: Mapped[Optional[dict]] = mapped_column(JSON, comment="导出的 Cookie")
    storage_state: Mapped[Optional[dict]] = mapped_column(
        JSON, comment="Playwright storage_state"
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="登录态过期时间"
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(64), comment="发起人")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SmsProvider(Base):
    """接码平台配置"""

    __tablename__ = "sms_provider"

    id: Mapped[int] = _pk()
    code: Mapped[str] = mapped_column(String(32), unique=True, comment="平台编码")
    name: Mapped[str] = mapped_column(String(64), comment="平台名称")
    api_base: Mapped[Optional[str]] = mapped_column(String(255), comment="API 地址")
    api_key: Mapped[Optional[str]] = mapped_column(String(255), comment="API Key")
    config_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="其他配置")
    enabled: Mapped[int] = mapped_column(
        SmallInteger, default=1, comment="1启用 0停用"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SmsOrder(Base):
    """接码订单：从接码平台取号/取码，用于目标平台登录"""

    __tablename__ = "sms_order"

    id: Mapped[int] = _pk()
    provider_id: Mapped[int] = mapped_column(BigInteger, comment="接码平台ID")
    provider_code: Mapped[str] = mapped_column(String(32), comment="接码平台编码")
    provider_order_id: Mapped[Optional[str]] = mapped_column(
        String(64), comment="接码平台订单号"
    )
    platform_id: Mapped[int] = mapped_column(BigInteger, comment="目标平台ID")
    platform_code: Mapped[str] = mapped_column(String(32), comment="目标平台编码")
    phone: Mapped[Optional[str]] = mapped_column(String(32), comment="手机号")
    status: Mapped[str] = mapped_column(
        String(16),
        default="pending",
        comment="pending/number_ready/code_ready/logging/success/failed/cancelled",
    )
    sms_code: Mapped[Optional[str]] = mapped_column(String(16), comment="验证码")
    raw_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="接码平台原始响应")
    error: Mapped[Optional[str]] = mapped_column(String(512), comment="失败原因")
    login_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment="关联的 platform_login.id"
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="号码过期时间")
    created_by: Mapped[Optional[str]] = mapped_column(String(64), comment="发起人")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

