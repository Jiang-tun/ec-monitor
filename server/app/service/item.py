from datetime import datetime, timedelta
from io import BytesIO
from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app.dao import item as item_dao
from app.service.scheduler import scheduler_service
from app.db.models import CrawlTaskLog, PriceSnapshot
from app.schemas.item import (
    ChangeRecordOut,
    CrawlLogOut,
    ImportErrorItem,
    ImportResultOut,
    LatestSnapshotOut,
    MonitorItemCreate,
    MonitorItemDetailOut,
    MonitorItemOut,
    MonitorItemUpdate,
    MonitorSkuOut,
    MonitorSwitch,
    PlatformOut,
    PriceHistoryOut,
    SkuToggleIn,
)


# ==================== 平台 ====================
def list_platforms_service(db: Session, only_enabled: bool = True) -> List[PlatformOut]:
    rows = item_dao.list_platforms(db, only_enabled=only_enabled)
    return [PlatformOut.model_validate(r) for r in rows]


# ==================== 商品 ====================
def get_item_service(db: Session, item_id: int) -> MonitorItemOut:
    item = item_dao.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
    return MonitorItemOut.model_validate(item)


def get_item_detail_service(db: Session, item_id: int) -> MonitorItemDetailOut:
    item = item_dao.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
    platform = item_dao.get_platform(db, item.platform_id)
    skus = item_dao.get_skus(db, item_id)
    detail = MonitorItemDetailOut.model_validate(item)
    detail.platform_name = platform.name if platform else None
    detail.skus = [MonitorSkuOut.model_validate(s) for s in skus]

    latest = (
        db.query(PriceSnapshot)
        .filter(PriceSnapshot.item_id == item_id)
        .order_by(PriceSnapshot.snapshot_time.desc(), PriceSnapshot.id.desc())
        .first()
    )
    if latest:
        detail.latest_snapshot = LatestSnapshotOut.model_validate(latest)

    task_ids = [
        row[0]
        for row in db.query(PriceSnapshot.task_id)
        .filter(
            PriceSnapshot.item_id == item_id,
            PriceSnapshot.task_id.isnot(None),
        )
        .order_by(PriceSnapshot.snapshot_time.desc())
        .limit(50)
        .all()
        if row[0]
    ]
    task_ids = list(dict.fromkeys(task_ids))[:10]
    if task_ids:
        logs = (
            db.query(CrawlTaskLog)
            .filter(CrawlTaskLog.task_id.in_(task_ids))
            .order_by(CrawlTaskLog.start_time.desc())
            .limit(10)
            .all()
        )
        detail.crawl_logs = [CrawlLogOut.model_validate(l) for l in logs]

    return detail


def list_items_service(
    db: Session,
    page: int,
    page_size: int,
    platform_id: Optional[int],
    shop_id: Optional[int],
    monitor_status: Optional[int],
    keyword: Optional[str],
) -> Tuple[List[MonitorItemOut], int]:
    items, total = item_dao.get_items(
        db=db,
        page=page,
        page_size=page_size,
        platform_id=platform_id,
        shop_id=shop_id,
        monitor_status=monitor_status,
        keyword=keyword,
    )
    return [MonitorItemOut.model_validate(i) for i in items], total


def create_item_service(db: Session, data: MonitorItemCreate) -> MonitorItemOut:
    platform = item_dao.get_platform(db, data.platform_id)
    if not platform:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="平台不存在")

    exists = item_dao.get_item_by_platform_item(
        db, platform_id=data.platform_id, item_id=data.item_id
    )
    if exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该平台商品已存在，请勿重复添加",
        )
    item = item_dao.create_item(db, **data.model_dump())
    return MonitorItemOut.model_validate(item)


def update_item_service(db: Session, item_id: int, data: MonitorItemUpdate) -> MonitorItemOut:
    item = item_dao.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
    update_data = {
        k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None
    }
    item = item_dao.update_item(db, item, **update_data)
    return MonitorItemOut.model_validate(item)


def delete_item_service(db: Session, item_id: int) -> None:
    item = item_dao.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
    item_dao.delete_item(db, item)


def switch_monitor_service(db: Session, item_id: int, data: MonitorSwitch) -> MonitorItemOut:
    item = item_dao.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
    item = item_dao.switch_monitor(db, item, data.monitor_status)
    return MonitorItemOut.model_validate(item)


def batch_switch_monitor_service(
    db: Session, item_ids: List[int], monitor_status: int
) -> dict:
    """批量切换监控状态（0暂停 1监控中 2疑似下架 3已下架 4待激活）。"""
    updated = 0
    missing: List[int] = []
    for item_id in item_ids:
        item = item_dao.get_item(db, item_id)
        if not item:
            missing.append(item_id)
            continue
        item.monitor_status = monitor_status
        if monitor_status == 1:
            item.next_run_time = datetime.now()
        updated += 1
    db.commit()
    return {
        "updated": updated,
        "missing": missing,
        "monitor_status": monitor_status,
    }


def batch_trigger_crawl_service(db: Session, item_ids: List[int]) -> dict:
    """批量手动触发采集：按 site_group 投递到 scrapy-redis 队列。"""
    items = []
    missing: List[int] = []
    for item_id in item_ids:
        item = item_dao.get_item(db, item_id)
        if not item:
            missing.append(item_id)
            continue
        items.append(item)
    result = scheduler_service.enqueue_items(db, items, trigger_type="manual")
    result["requested"] = len(item_ids)
    result["missing"] = missing
    return result


# ==================== SKU ====================
def get_item_skus_service(db: Session, item_id: int) -> List[MonitorSkuOut]:
    item = item_dao.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
    skus = item_dao.get_skus(db, item_id)
    return [MonitorSkuOut.model_validate(s) for s in skus]


def toggle_skus_service(db: Session, item_id: int, data: SkuToggleIn) -> dict:
    item = item_dao.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
    if data.sku_ids:
        existing = {s.sku_id for s in item_dao.get_skus(db, item_id)}
        missing = [s for s in data.sku_ids if s not in existing]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"SKU 不存在: {', '.join(missing[:5])}",
            )
    count = item_dao.set_skus_enabled(
        db, item_id, data.sku_ids, data.monitor_enabled
    )
    return {"updated": count, "monitor_enabled": data.monitor_enabled}


# ==================== 价格历史 ====================
def _parse_dt(value: Optional[str], default: datetime) -> datetime:
    if not value:
        return default
    text = value.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail=f"时间格式非法: {value}"
    )


def price_history_service(
    db: Session,
    item_id: int,
    sku_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    granularity: str = "raw",
) -> PriceHistoryOut:
    item = item_dao.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")

    now = datetime.now()
    start_dt = _parse_dt(start, now - timedelta(days=7))
    end_dt = _parse_dt(end, now)
    if start_dt > end_dt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="开始时间不能晚于结束时间")
    if (end_dt - start_dt).days > 180:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="查询跨度不能超过 180 天")

    if granularity in ("hour", "day"):
        fmt = "%Y-%m-%d %H:00" if granularity == "hour" else "%Y-%m-%d"
        points = item_dao.price_series(
            db, item_id, sku_id=sku_id, start=start_dt, end=end_dt, fmt=fmt
        )
    else:
        granularity = "raw"
        rows = item_dao.price_points(
            db, item_id, sku_id=sku_id, start=start_dt, end=end_dt
        )
        points = [
            {
                "time": r.snapshot_time.strftime("%Y-%m-%d %H:%M:%S"),
                "price": float(r.price) if r.price is not None else None,
                "min_price": float(r.price) if r.price is not None else None,
                "max_price": float(r.price) if r.price is not None else None,
                "stock": r.stock,
            }
            for r in rows
        ]

    return PriceHistoryOut(
        item_id=item_id, sku_id=sku_id, granularity=granularity, points=points
    )


# ==================== 变更记录 ====================
def changes_service(
    db: Session,
    item_id: int,
    sku_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[ChangeRecordOut], int]:
    item = item_dao.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
    rows, total = item_dao.changes_page(
        db, item_id, sku_id=sku_id, page=page, page_size=page_size
    )
    return [ChangeRecordOut.model_validate(r) for r in rows], total


# ==================== 批量导入 ====================
IMPORT_HEADERS = ["平台编码", "商品ID", "商品链接", "标题", "重要度", "采集频率", "采集策略"]

_IMPORTANCE_MAP = {"核心": 1, "普通": 2, "长尾": 3}
_FREQ_MAP = {
    "5分钟": "5m", "5m": "5m",
    "30分钟": "30m", "30m": "30m",
    "1小时": "1h", "1h": "1h",
    "每天": "daily", "daily": "daily",
}
_STRATEGY_SET = {"auto", "api", "page", "browser"}


def build_import_template() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "商品导入"

    header_fill = PatternFill("solid", fgColor="EAF1FF")
    for idx, title in enumerate(IMPORT_HEADERS, start=1):
        cell = ws.cell(row=1, column=idx, value=title)
        cell.font = Font(bold=True, color="1F2937")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(idx)].width = 22 if idx < 4 else 14

    sample = ["taobao", "123456789", "https://item.taobao.com/item.htm?id=123456789", "示例商品", 2, "30m", "auto"]
    for idx, value in enumerate(sample, start=1):
        ws.cell(row=2, column=idx, value=value)

    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 22

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def import_items_service(db: Session, content: bytes) -> ImportResultOut:
    try:
        wb = load_workbook(BytesIO(content), data_only=True)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="文件解析失败，请使用导入模板"
        )

    ws = wb.active
    result = ImportResultOut()
    errors: List[ImportErrorItem] = []

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or all(v is None or str(v).strip() == "" for v in row):
            continue
        result.total += 1

        platform_code = str(row[0]).strip() if row[0] else ""
        item_no = str(row[1]).strip() if row[1] else ""
        url = str(row[2]).strip() if row[2] else ""
        title = str(row[3]).strip() if len(row) > 3 and row[3] else None
        importance_raw = row[4] if len(row) > 4 else None
        freq_raw = str(row[5]).strip() if len(row) > 5 and row[5] else "30m"
        strategy_raw = str(row[6]).strip() if len(row) > 6 and row[6] else "auto"

        if not platform_code:
            result.failed += 1
            errors.append(ImportErrorItem(row=row_idx, message="平台编码为空"))
            continue
        platform = item_dao.get_platform_by_code(db, platform_code)
        if not platform:
            result.failed += 1
            errors.append(ImportErrorItem(row=row_idx, message=f"平台编码不存在: {platform_code}"))
            continue
        if not item_no:
            result.failed += 1
            errors.append(ImportErrorItem(row=row_idx, message="商品ID为空"))
            continue
        if not url:
            result.failed += 1
            errors.append(ImportErrorItem(row=row_idx, message="商品链接为空"))
            continue
        if item_dao.get_item_by_platform_item(db, platform.id, item_no):
            result.skipped += 1
            continue

        if isinstance(importance_raw, str):
            importance = _IMPORTANCE_MAP.get(importance_raw.strip(), 2)
        elif isinstance(importance_raw, (int, float)):
            importance = int(importance_raw)
        else:
            importance = 2
        importance = min(max(importance, 1), 3)

        crawl_freq = _FREQ_MAP.get(freq_raw, "30m")
        strategy = strategy_raw if strategy_raw in _STRATEGY_SET else "auto"

        try:
            item_dao.create_item(
                db,
                platform_id=platform.id,
                item_id=item_no,
                url=url,
                title=title,
                importance=importance,
                crawl_freq=crawl_freq,
                strategy=strategy,
            )
            result.success += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            result.failed += 1
            errors.append(
                ImportErrorItem(row=row_idx, message=f"写入失败: {type(exc).__name__}")
            )

    result.errors = errors[:100]
    return result

def trigger_crawl_service(db: Session, item_id: int) -> dict:
    """手动触发一次采集：投递到对应 site_group 的 scrapy-redis 队列。"""
    item = item_dao.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
    return scheduler_service.enqueue_items(db, [item], trigger_type="manual")