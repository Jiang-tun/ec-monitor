import time
import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.response import ok, err
from app.db.session import SessionLocal
from app.db.models import (
    MonitorItem,
    PriceSnapshot,
    ChangeRecord,
    AlertRule,
    DeadLetter,
    CrawlTaskLog,
)
from app.dao import snapshot as snapshot_dao
from app.dao import dead_letter as dead_letter_dao
from app.schemas.platform_login import PlatformLoginResultIn
from app.schemas.search import SearchResultIn
from app.schemas.sms import SmsResultIn
from app.service import change_detector, message as message_service, platform_login as login_service, quality_checker, rule_engine, search as search_service, sms as sms_service

router = APIRouter(prefix="/internal", tags=["internal"])


def verify_node_key(x_node_api_key: str | None) -> None:
    settings = get_settings()
    if x_node_api_key != settings.node_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "节点 API Key 无效")


# 进程级幂等缓存（生产建议用 Redis SETNX）
_processed_batch_ids: Dict[str, float] = {}


def _batch_id_seen(batch_id: str, ttl_sec: int = 600) -> bool:
    now = time.time()
    expired = [k for k, v in _processed_batch_ids.items() if v < now]
    for k in expired:
        _processed_batch_ids.pop(k, None)
    if batch_id in _processed_batch_ids:
        return True
    _processed_batch_ids[batch_id] = now + ttl_sec
    return False


def _get_db() -> Session:
    return SessionLocal()


def _blocked_reason(rec: dict) -> str:
    """从快照推广信息里提取被拦截原因。"""
    pj = rec.get("promotion_json") or {}
    for v in pj.values():
        if isinstance(v, dict) and v.get("note"):
            return str(v["note"])
    status = rec.get("page_status")
    return f"页面状态 {status}，疑似风控/未登录"


def _maybe_blocked_dead_letter(db: Session, item, sku_id, rec: dict) -> None:
    """被拦截(风控/未登录)连续失败达到阈值时，写入死信队列并推消息。"""
    settings = get_settings()
    try:
        db.refresh(item)
    except Exception:  # noqa: BLE001
        return
    if (item.fail_count or 0) < (settings.dead_threshold or 3):
        return

    reason = _blocked_reason(rec)[:512]
    existing = (
        db.query(DeadLetter)
        .filter(
            DeadLetter.item_id == item.id,
            DeadLetter.status.in_(("pending", "processing", "retrying")),
        )
        .first()
    )
    if existing is not None:
        existing.retry_count = (existing.retry_count or 0) + 1
        existing.last_fail_at = datetime.now()
        existing.fail_reason = reason
        existing.fail_stage = "fetch"
        db.add(existing)
        return

    dl = dead_letter_dao.create_dead_letter(
        db,
        {
            "item_id": item.id,
            "sku_id": sku_id,
            "fail_stage": "fetch",
            "fail_reason": reason,
            "raw_error": f"page_status={rec.get('page_status')}",
            "fail_strategy": rec.get("strategy_used"),
            "retry_count": 0,
            "max_retry": 5,
            "status": "pending",
            "first_fail_at": datetime.now(),
            "last_fail_at": datetime.now(),
            "task_id": rec.get("task_id"),
        },
    )
    try:
        message_service.push_dead_letter_message(db, dl)
    except Exception:  # noqa: BLE001
        pass


# ==================== POST /internal/snapshots ====================

@router.post("/snapshots")
async def post_snapshots(
    request: Request,
    x_node_api_key: str | None = Header(default=None),
):
    verify_node_key(x_node_api_key)
    try:
        body: dict = await request.json()
    except Exception:
        return err(1002, "请求体非法 JSON")

    batch_id = body.get("batch_id")
    items = body.get("items", [])
    if not batch_id:
        return err(1001, "缺少 batch_id")
    if not isinstance(items, list):
        return err(1002, "items 必须是数组")
    if len(items) > 200:
        return err(1002, "单批最多 200 条")

    if _batch_id_seen(batch_id):
        return ok({"accepted": 0, "duplicates": len(items), "changes_detected": 0})

    db = _get_db()
    accepted = 0
    duplicates = 0
    changes_detected = 0
    task_counts: Dict[str, int] = {}
    task_fail: Dict[str, int] = {}
    try:

        for rec in items:
            item_id = rec.get("item_id")
            sku_id = rec.get("sku_id")
            if not item_id:
                duplicates += 1
                continue

            item: Optional[MonitorItem] = (
                db.query(MonitorItem)
                .filter(MonitorItem.id == item_id, MonitorItem.is_deleted == 0)
                .first()
            )
            if not item:
                duplicates += 1
                continue

            snapshot_time = rec.get("snapshot_time")
            if snapshot_time and isinstance(snapshot_time, str):
                try:
                    snapshot_time = datetime.fromisoformat(snapshot_time)
                except Exception:
                    snapshot_time = None
            if not snapshot_time:
                snapshot_time = datetime.now()

            # 辅助去重：相同 item+sku+snapshot_time
            existing = (
                db.query(PriceSnapshot)
                .filter(
                    PriceSnapshot.item_id == item_id,
                    PriceSnapshot.sku_id == sku_id,
                    PriceSnapshot.snapshot_time == snapshot_time,
                )
                .first()
            )
            if existing:
                duplicates += 1
                continue

            # 计算 field_hash / field_hash_map
            parsed = {
                "price": rec.get("price"),
                "original_price": rec.get("original_price"),
                "stock": rec.get("stock"),
                "promotion_json": rec.get("promotion_json"),
                "title": rec.get("title"),
                "page_status": rec.get("page_status"),
            }
            field_hash_value, field_hash_map = change_detector.row_hash(
                parsed, rec.get("price_basis")
            )

            snap_data = {
                "item_id": item_id,
                "sku_id": sku_id,
                "platform_id": rec.get("platform_id", item.platform_id),
                "price": rec.get("price"),
                "price_basis": rec.get("price_basis"),
                "original_price": rec.get("original_price"),
                "stock": rec.get("stock"),
                "promotion_json": rec.get("promotion_json"),
                "title": rec.get("title"),
                "url": rec.get("url"),
                "page_status": rec.get("page_status"),
                "strategy_used": rec.get("strategy_used"),
                "proxy_id": rec.get("proxy_id"),
                "node_id": rec.get("node_id"),
                "task_id": rec.get("task_id"),
                "field_hash": field_hash_value,
                "field_hash_map": field_hash_map,
                "quality_flag": rec.get("quality_flag", 0),
                "snapshot_time": snapshot_time,
            }

            snap = snapshot_dao.create_snapshot(db, snap_data)
            accepted += 1

            # 被拦截/风控（如 403/429/5xx）计为失败；404/410 视为下架检测(成功)
            page_status = rec.get("page_status")
            blocked = (
                page_status is not None
                and page_status >= 400
                and page_status not in (404, 410)
            )
            tid = rec.get("task_id")
            if tid:
                key = str(tid)
                if blocked:
                    task_fail[key] = task_fail.get(key, 0) + 1
                else:
                    task_counts[key] = task_counts.get(key, 0) + 1

            # 质量校验：被拦截(风控/未登录)属抓取失败，不计为数据质量异常、不推质量消息
            if not blocked:
                quality_flag, quality_issues = quality_checker.check_snapshot_quality(
                    db, item, sku_id, parsed
                )
                if quality_issues:
                    quality_checker.write_quality_issues(db, quality_issues)
                # 写回快照质量标记
                if quality_flag != snap.quality_flag:
                    snap.quality_flag = quality_flag
                    db.add(snap)

            # 更新 monitor_sku 冗余字段
            snapshot_dao.update_sku_redundant(
                db,
                item_id,
                sku_id,
                price=rec.get("price"),
                original_price=rec.get("original_price"),
                stock=rec.get("stock"),
            )

            # 更新 monitor_item 最后采集状态（被拦截记为失败）
            snapshot_dao.update_item_last_crawl(db, item_id, success=not blocked)
            if blocked:
                # 连续失败达到阈值 -> 进入死信队列
                _maybe_blocked_dead_letter(db, item, sku_id, rec)

            # 变更检测：被拦截的快照不参与，避免误判降价/缺货
            if not blocked:
                changes = change_detector.process_snapshot_for_changes(
                    db, item, sku_id, snap
                )
                if changes:
                    changes_detected += len(changes)

                    prev = snapshot_dao.get_latest_snapshot(db, item_id, sku_id, exclude_id=snap.id)
                    rule_engine.evaluate_change_event(
                        db, item, sku_id, changes, snap, prev
                    )

        db.commit()

        # 回写采集任务批次的成功/失败计数，达成目标后结束任务
        if task_counts or task_fail:
            for tid in set(task_counts) | set(task_fail):
                log = (
                    db.query(CrawlTaskLog)
                    .filter(CrawlTaskLog.task_id == tid)
                    .first()
                )
                if not log:
                    continue
                succ = task_counts.get(tid, 0)
                fail = task_fail.get(tid, 0)
                log.success_count = (log.success_count or 0) + succ
                log.fail_count = (log.fail_count or 0) + fail
                done = (
                    (log.success_count or 0)
                    + (log.fail_count or 0)
                    + (log.dead_count or 0)
                )
                if done >= (log.total_count or 0) and log.status == "running":
                    has_fail = (log.fail_count or 0) or (log.dead_count or 0)
                    log.status = "partial" if has_fail else "success"
                    log.end_time = datetime.now()
                    try:
                        log.cost_ms = int(
                            (log.end_time - log.start_time).total_seconds() * 1000
                        )
                    except Exception:  # noqa: BLE001
                        pass
                db.add(log)
            db.commit()
    finally:
        db.close()

    return ok({"accepted": accepted, "duplicates": duplicates, "changes_detected": changes_detected})


# ==================== POST /internal/dead-letters ====================

@router.post("/dead-letters")
async def post_dead_letters(
    request: Request,
    x_node_api_key: str | None = Header(default=None),
):
    verify_node_key(x_node_api_key)
    try:
        body: dict = await request.json()
    except Exception:
        return err(1002, "请求体非法 JSON")

    node_id = body.get("node_id")
    item_id = body.get("item_id")
    sku_id = body.get("sku_id")
    fail_stage = body.get("fail_stage")
    fail_reason = body.get("fail_reason")
    raw_error = body.get("raw_error")
    fail_strategy = body.get("fail_strategy")
    task_id = body.get("task_id")

    if not node_id:
        return err(1001, "缺少 node_id")
    if not item_id:
        return err(1001, "缺少 item_id")
    if not fail_stage:
        return err(1001, "缺少 fail_stage")
    if not fail_reason:
        return err(1001, "缺少 fail_reason")

    db = _get_db()
    dl = None
    dl_id = None
    settings = get_settings()
    try:
        dead_letter_dao.increment_fail_count(db, item_id)

        fail_count_item = (
            db.query(MonitorItem)
            .filter(MonitorItem.id == item_id, MonitorItem.is_deleted == 0)
            .first()
        )
        fc = fail_count_item.fail_count if fail_count_item else 0

        # 同一商品存在未处理死信时：更新重试次数/时间，避免重复堆积
        existing = (
            db.query(DeadLetter)
            .filter(
                DeadLetter.item_id == item_id,
                DeadLetter.status.in_(("pending", "processing", "retrying")),
            )
            .first()
        )
        created_new = False
        if existing is not None:
            existing.retry_count = (existing.retry_count or 0) + 1
            existing.last_fail_at = datetime.now()
            existing.fail_reason = fail_reason
            if fail_stage:
                existing.fail_stage = fail_stage
            db.add(existing)
            dl = existing
            dl_id = existing.id
        elif fc >= settings.dead_threshold:
            # 连续失败超阈值（DEAD_THRESHOLD=3）后才新建死信并推消息
            dl = dead_letter_dao.create_dead_letter(
                db,
                {
                    "item_id": item_id,
                    "sku_id": sku_id,
                    "fail_stage": fail_stage,
                    "fail_reason": fail_reason,
                    "raw_error": raw_error,
                    "fail_strategy": fail_strategy,
                    "retry_count": 0,
                    "max_retry": 5,
                    "status": "pending",
                    "first_fail_at": datetime.now(),
                    "last_fail_at": datetime.now(),
                    "task_id": task_id,
                },
            )
            dl_id = dl.id
            created_new = True
            message_service.push_dead_letter_message(db, dl)

        # 回写任务批次的失败/死信计数
        if task_id:
            log = (
                db.query(CrawlTaskLog)
                .filter(CrawlTaskLog.task_id == str(task_id))
                .first()
            )
            if log:
                log.fail_count = (log.fail_count or 0) + 1
                if created_new:
                    log.dead_count = (log.dead_count or 0) + 1
                done = (
                    (log.success_count or 0)
                    + (log.fail_count or 0)
                    + (log.dead_count or 0)
                )
                if done >= (log.total_count or 0) and log.status == "running":
                    log.status = "partial"
                    log.end_time = datetime.now()
                    try:
                        log.cost_ms = int(
                            (log.end_time - log.start_time).total_seconds() * 1000
                        )
                    except Exception:  # noqa: BLE001
                        pass
                db.add(log)
        db.commit()
    finally:
        db.close()

    return ok({"accepted": 1 if dl_id else 0, "dead_letter_id": dl_id, "status": "pending" if dl_id else "counted"})


# ==================== POST /internal/search-results ====================

@router.post("/search-results")
async def post_search_results(
    request: Request,
    x_node_api_key: str | None = Header(default=None),
):
    """节点回写关键词搜索结果（按 平台+关键词+商品ID 去重后建监控）。"""
    verify_node_key(x_node_api_key)
    try:
        body: dict = await request.json()
    except Exception:
        return err(1002, "请求体非法 JSON")

    task_id = body.get("task_id")
    if not task_id:
        return err(1001, "缺少 task_id")
    items = body.get("items")
    if not isinstance(items, list):
        return err(1002, "items 必须是数组")
    if len(items) > 100:
        return err(1002, "单批最多 100 条")

    error = body.get("error")
    if error:
        db = _get_db()
        try:
            search_service.mark_failed(db, str(task_id), str(error))
        finally:
            db.close()
        return ok({"failed": True, "message": str(error)})

    db = _get_db()
    try:
        result = search_service.handle_results(
            db, SearchResultIn(task_id=str(task_id), items=items)
        )
        return ok(result.model_dump())
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return err(5001, f"回写失败: {type(exc).__name__}: {str(exc)[:200]}")
    finally:
        db.close()
# ==================== POST /internal/login-results ====================

@router.post("/login-results")
async def post_login_result(
    request: Request,
    x_node_api_key: str | None = Header(default=None),
):
    """节点回调：回传手机号验证码登录结果（Cookie/storage_state）。

    请求体：
      {"login_id": 1, "status": "success|failed|expired",
       "cookies": {"name": "value"} 或 Playwright cookies 数组,
       "storage_state": {...}, "error": "..."}
    """
    verify_node_key(x_node_api_key)
    try:
        body: dict = await request.json()
    except Exception:
        return err(1002, "请求体非法 JSON")

    if not body.get("login_id"):
        return err(1001, "缺少 login_id")
    if not body.get("status"):
        return err(1001, "缺少 status")

    db = _get_db()
    try:
        result = login_service.handle_result(
            db, PlatformLoginResultIn(**body)
        )
        return ok(result.model_dump())
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return err(5001, f"回写登录结果失败: {type(exc).__name__}: {str(exc)[:200]}")
    finally:
        db.close()
# ==================== POST /internal/sms-results ====================

@router.post("/sms-results")
async def post_sms_result(
    request: Request,
    x_node_api_key: str | None = Header(default=None),
):
    """节点回写接码结果（取号 / 取码）。

    请求体：
      {"order_id": 1, "action": "acquire|fetch_code", "status": "success|pending|failed",
       "phone": "...", "code": "...", "code_url": "...", "provider_order_id": "...",
       "raw": {...}, "error": "..."}
    """
    verify_node_key(x_node_api_key)
    try:
        body: dict = await request.json()
    except Exception:
        return err(1002, "请求体非法 JSON")

    if not body.get("order_id"):
        return err(1001, "缺少 order_id")
    if body.get("action") not in ("acquire", "fetch_code"):
        return err(1002, "action 必须是 acquire 或 fetch_code")

    db = _get_db()
    try:
        result = sms_service.handle_result(db, SmsResultIn(**body))
        return ok(result.model_dump())
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return err(5001, f"回写接码结果失败: {type(exc).__name__}: {str(exc)[:200]}")
    finally:
        db.close()


# ==================== POST /internal/sms-orders (acquire) ====================

@router.post("/sms-orders")
async def create_sms_order_internal(
    request: Request,
    x_node_api_key: str | None = Header(default=None),
):
    """供登录节点取号：按 platform_code 创建接码订单并入队 SMSNam。

    请求体：{"platform_code": "jd"}（可选 provider_code，默认 smsnam）
    返回：订单（含 id / platform_id / status）
    """
    verify_node_key(x_node_api_key)
    try:
        body = await request.json()
    except Exception:
        return err(1002, "请求体非法 JSON")

    platform_code = (body.get("platform_code") or "").strip()
    if not platform_code:
        return err(1001, "缺少 platform_code")

    from app.db.models import Platform
    from app.schemas.sms import SmsOrderCreate

    db = _get_db()
    try:
        platform = (
            db.query(Platform)
            .filter(
                Platform.code == platform_code,
                Platform.status == 1,
                Platform.is_deleted == 0,
            )
            .first()
        )
        if not platform:
            return err(1004, f"平台 {platform_code} 不存在或已停用")

        provider_id = body.get("provider_id")
        data = SmsOrderCreate(
            provider_id=provider_id,
            platform_id=platform.id,
        )
        order = sms_service.acquire_number(
            db=db, data=data, created_by="internal-node"
        )
        return ok(order.model_dump())
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return err(5001, f"创建接码订单失败: {type(exc).__name__}: {str(exc)[:200]}")
    finally:
        db.close()


# ==================== GET /internal/sms-orders/{order_id} ====================

@router.get("/sms-orders/{order_id}")
def get_sms_order_internal(
    order_id: int,
    x_node_api_key: str | None = Header(default=None),
):
    """供登录节点轮询接码订单：状态 / 验证码 / 接码页面地址。"""
    verify_node_key(x_node_api_key)
    from app.dao import sms as sms_dao

    db = _get_db()
    try:
        order = sms_dao.get_order(db, order_id)
        if not order:
            return err(1004, "接码订单不存在")
        raw = order.raw_json or {}
        return ok(
            {
                "id": order.id,
                "provider_code": order.provider_code,
                "platform_code": order.platform_code,
                "phone": order.phone,
                "status": order.status,
                "sms_code": order.sms_code,
                "code_url": raw.get("code_url"),
                "login_id": order.login_id,
                "error": order.error,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return err(5001, f"查询接码订单失败: {type(exc).__name__}: {str(exc)[:200]}")
    finally:
        db.close()


# ==================== POST /internal/sms-orders/{order_id}/fetch-code ====================

@router.post("/sms-orders/{order_id}/fetch-code")
def trigger_fetch_code(
    order_id: int,
    x_node_api_key: str | None = Header(default=None),
):
    """供登录节点触发取码（走接码平台的 Cloudflare 绕过管线），结果回写订单。"""
    verify_node_key(x_node_api_key)
    db = _get_db()
    try:
        out = sms_service.fetch_code(db, order_id)
        return ok(out.model_dump())
    except Exception as exc:  # noqa: BLE001
        return err(5001, f"触发取码失败: {type(exc).__name__}: {str(exc)[:200]}")
    finally:
        db.close()