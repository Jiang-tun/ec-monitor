import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from redis import Redis as RedisPy
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import INTERNAL_ERROR, NOT_FOUND, PARAM_INVALID, BizError
from app.dao import search as search_dao
from app.db.models import Platform
from app.schemas.search import (
    SearchCandidateOut,
    SearchConfirmIn,
    SearchConfirmOut,
    SearchResultIn,
    SearchResultOut,
    SearchTaskCreate,
    SearchTaskOut,
)

settings = get_settings()

_SERVER_DIR = Path(__file__).resolve().parents[2]
CRAWL_DIR = _SERVER_DIR / "crawl"
SEARCH_LOG_DIR = _SERVER_DIR / "logs" / "search"

# 平台编码 → 搜索页 URL（{q} 为 URL 编码后的关键词）
SEARCH_URL_BUILDERS = {
    "taobao": lambda q: (
        f"https://uland.taobao.com/sem/tbsearch?keyword={q}"
        f"&localImgKey=&page=1&q={q}&tab=all"
    ),
    "jd": lambda q: f"https://re.jd.com/search?keyword={q}",
    "pdd": lambda q: f"https://mobile.yangkeduo.com/search_result.html?search_key={q}",
    "suning": lambda q: f"https://search.suning.com/{q}/",
    "amazon": lambda q: f"https://www.amazon.com/s?k={q}",
}

# 平台编码 → Spider 名（部署时按需启动）
SEARCH_SPIDERS = {
    "taobao": "taobao_search",
    "jd": "jd_search",
    "pdd": "pdd_search",
    "suning": "suning_search",
    "amazon": "amazon_search",
}


def _redis() -> RedisPy:
    return RedisPy.from_url(settings.redis_url_compat)


def _task_out(task) -> SearchTaskOut:
    return SearchTaskOut.model_validate(task)


def create_task(
    db: Session, data: SearchTaskCreate, created_by: Optional[str] = None
) -> SearchTaskOut:
    platform = (
        db.query(Platform)
        .filter(
            Platform.id == data.platform_id,
            Platform.status == 1,
            Platform.is_deleted == 0,
        )
        .first()
    )
    if not platform:
        raise BizError(PARAM_INVALID, "平台不存在或已停用")
    if platform.code not in SEARCH_URL_BUILDERS:
        raise BizError(PARAM_INVALID, f"平台 {platform.code} 暂不支持关键词采集")

    keyword = data.keyword.strip()
    if not keyword:
        raise BizError(PARAM_INVALID, "关键词不能为空")

    adapter = platform.adapter_config or {}
    site_group = adapter.get("site_group") or "cn-main"
    task_id = f"search_{int(time.time() * 1000)}_{platform.code}"

    task = search_dao.create_task(
        db,
        task_id=task_id,
        platform_id=platform.id,
        platform_code=platform.code,
        keyword=keyword,
        limit_count=data.limit_count,
        status="pending",
        created_by=created_by,
    )

    seed = {
        "task_type": "search",
        "task_id": task_id,
        "platform_id": platform.id,
        "platform_code": platform.code,
        "keyword": keyword,
        "limit": data.limit_count,
        "site_group": site_group,
        "url": SEARCH_URL_BUILDERS[platform.code](quote(keyword)),
        "dont_filter": True,
    }
    queue_key = f"ecom:sc:{site_group}:search:{platform.code}"
    try:
        _redis().lpush(queue_key, json.dumps(seed, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        search_dao.update_task(
            db, task, status="failed", error=f"入队失败: {type(exc).__name__}"
        )
        raise BizError(INTERNAL_ERROR, "采集队列不可用，任务未启动") from exc

    return _task_out(task)


def list_tasks(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    platform_id: Optional[int] = None,
    keyword: Optional[str] = None,
    status: Optional[str] = None,
) -> tuple[list[SearchTaskOut], int]:
    rows, total = search_dao.list_tasks(
        db,
        page=page,
        page_size=page_size,
        platform_id=platform_id,
        keyword=keyword,
        status=status,
    )
    return [_task_out(r) for r in rows], total


def get_task(db: Session, task_id: str) -> SearchTaskOut:
    task = search_dao.get_by_task_id(db, task_id)
    if not task:
        raise BizError(NOT_FOUND, "搜索任务不存在")
    return _task_out(task)


def _as_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").strip("¥￥ "))
    except (TypeError, ValueError):
        return None


def handle_results(db: Session, data: SearchResultIn) -> SearchResultOut:
    """节点回写搜索结果：去重后只写候选表，等用户筛选确认再入库。"""
    task = search_dao.get_by_task_id(db, data.task_id)
    if not task:
        raise BizError(NOT_FOUND, "搜索任务不存在")

    if task.status in ("collected", "success"):
        return SearchResultOut(
            task_id=task.task_id,
            total=task.total_count,
            new=task.new_count,
            dup=task.dup_count,
        )

    total = new = dup = 0
    batch_seen: set[str] = set()

    for raw in data.items:
        if total >= task.limit_count:
            break
        pid = raw.get("platform_item_id") or raw.get("item_id")
        if pid is None:
            continue
        pid = str(pid).strip()
        if not pid:
            continue
        total += 1

        if pid in batch_seen:
            dup += 1
            continue
        batch_seen.add(pid)

        if search_dao.get_seen(db, task.platform_id, task.keyword, pid):
            dup += 1
            continue

        existing = search_dao.get_monitor_item(db, task.platform_id, pid)
        if existing:
            search_dao.add_seen(
                db, task.platform_id, task.keyword, pid, existing.id
            )
            dup += 1
            continue

        search_dao.add_candidate(
            db,
            task_id=task.task_id,
            platform_id=task.platform_id,
            keyword=task.keyword,
            platform_item_id=pid,
            title=(raw.get("title") or None),
            url=(raw.get("url") or "")[:1024] or None,
            image=(raw.get("image") or None),
            price=_as_float(raw.get("price")),
            original_price=_as_float(raw.get("original_price")),
            status="pending",
        )
        new += 1

    search_dao.update_task(
        db,
        task,
        status="collected",
        total_count=total,
        new_count=new,
        dup_count=dup,
        added_count=0,
        finished_at=datetime.now(),
        error=None,
    )
    return SearchResultOut(task_id=task.task_id, total=total, new=new, dup=dup)


def list_candidates(
    db: Session, task_id: str, only_pending: bool = False
) -> list[SearchCandidateOut]:
    task = search_dao.get_by_task_id(db, task_id)
    if not task:
        raise BizError(NOT_FOUND, "搜索任务不存在")
    rows = search_dao.list_candidates(db, task_id, only_pending=only_pending)
    return [SearchCandidateOut.model_validate(r) for r in rows]


def confirm_candidates(
    db: Session, task_id: str, data: SearchConfirmIn
) -> SearchConfirmOut:
    """用户筛选确认：把选中的候选商品写入监控列表。"""
    task = search_dao.get_by_task_id(db, task_id)
    if not task:
        raise BizError(NOT_FOUND, "搜索任务不存在")
    if task.status == "success":
        return SearchConfirmOut(
            task_id=task.task_id, added=task.added_count or 0, dup=0, skipped=0
        )

    platform = db.query(Platform).filter(Platform.id == task.platform_id).first()
    price_basis = (platform.adapter_config or {}).get("price_basis") if platform else None
    currency = "USD" if task.platform_code == "amazon" else "CNY"

    pending = search_dao.list_candidates(db, task_id, only_pending=True)
    if data.select_all:
        chosen = pending
    else:
        wanted = set(data.candidate_ids or [])
        chosen = [c for c in pending if c.id in wanted]

    added = dup = 0
    for candidate in chosen:
        existing = search_dao.get_monitor_item(
            db, candidate.platform_id, candidate.platform_item_id
        )
        if existing:
            candidate.status = "added"
            candidate.monitor_item_id = existing.id
            dup += 1
            continue

        monitor = search_dao.create_monitor_item(
            db,
            platform_id=candidate.platform_id,
            item_id=candidate.platform_item_id,
            url=(candidate.url or "")[:1024]
            or f"https://{task.platform_code}/{candidate.platform_item_id}",
            title=candidate.title,
            main_image=candidate.image,
            currency=currency,
            monitor_status=1,
            importance=2,
            crawl_freq="30m",
            strategy="auto",
            price_basis=price_basis,
            next_run_time=datetime.now(),
        )
        candidate.status = "added"
        candidate.monitor_item_id = monitor.id
        added += 1

    # 记录“已决策”：无论入库还是跳过，同一关键词后续采集不再重复展示
    for candidate in pending:
        seen = search_dao.get_seen(
            db, candidate.platform_id, candidate.keyword, candidate.platform_item_id
        )
        if seen is None:
            search_dao.add_seen(
                db,
                candidate.platform_id,
                candidate.keyword,
                candidate.platform_item_id,
                candidate.monitor_item_id,
            )
        elif candidate.monitor_item_id:
            seen.monitor_item_id = candidate.monitor_item_id

    db.flush()
    skipped = search_dao.skip_pending_candidates(db, task_id)
    search_dao.update_task(db, task, status="success", added_count=added)
    return SearchConfirmOut(
        task_id=task.task_id, added=added, dup=dup, skipped=skipped
    )

def mark_failed(db: Session, task_id: str, error: str) -> None:
    task = search_dao.get_by_task_id(db, task_id)
    if not task or task.status == "success":
        return
    search_dao.update_task(
        db,
        task,
        status="failed",
        error=error[:512],
        finished_at=datetime.now(),
    )

# ==================== 通过接口启动 Spider ====================


def _remove_seed(queue_key: str, task_id: str) -> None:
    """启动直连模式前，移除队列里该任务的种子，避免重复消费。"""
    try:
        redis = _redis()
        for raw in redis.lrange(queue_key, 0, -1):
            try:
                seed = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if seed.get("task_id") == task_id:
                redis.lrem(queue_key, 1, raw)
                break
    except Exception:  # noqa: BLE001 队列清理失败不影响直连启动
        pass


def run_task(db: Session, task_id: str) -> dict:
    """为指定任务启动对应平台的搜索 Spider（子进程，一次性执行）。"""
    task = search_dao.get_by_task_id(db, task_id)
    if not task:
        raise BizError(NOT_FOUND, "搜索任务不存在")
    if task.status == "success":
        raise BizError(PARAM_INVALID, "任务已完成，无需重复启动")

    spider = SEARCH_SPIDERS.get(task.platform_code)
    if not spider:
        raise BizError(PARAM_INVALID, f"平台 {task.platform_code} 暂无搜索 Spider")

    platform = db.query(Platform).filter(Platform.id == task.platform_id).first()
    adapter = (platform.adapter_config if platform else None) or {}
    site_group = adapter.get("site_group") or "cn-main"

    _remove_seed(
        f"ecom:sc:{site_group}:search:{task.platform_code}", task.task_id
    )

    search_dao.update_task(db, task, status="running", error=None)

    SEARCH_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = SEARCH_LOG_DIR / f"{task.task_id}.log"

    cmd = [
        sys.executable,
        "-m",
        "scrapy",
        "crawl",
        spider,
        "-a",
        f"site_group={site_group}",
        "-a",
        f"task_id={task.task_id}",
        "-a",
        f"keyword={task.keyword}",
        "-a",
        f"platform_id={task.platform_id}",
        "-a",
        f"limit={task.limit_count}",
        "-s",
        "CLOSESPIDER_ITEMCOUNT=1",
        "-s",
        "CLOSESPIDER_TIMEOUT=180",
    ]

    env = os.environ.copy()
    env["INTERNAL_API_BASE"] = os.environ.get(
        "INTERNAL_API_BASE", "http://127.0.0.1:8000"
    )
    env["NODE_API_KEY"] = settings.node_api_key

    flags = 0x00000200 | 0x08000000 if os.name == "nt" else 0  # 新进程组 + 无窗口

    try:
        with open(log_path, "ab") as log_file:
            proc = subprocess.Popen(
                cmd,
                cwd=str(CRAWL_DIR),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=flags,
            )
    except Exception as exc:  # noqa: BLE001
        search_dao.update_task(
            db, task, status="failed", error=f"启动失败: {type(exc).__name__}"
        )
        raise BizError(INTERNAL_ERROR, "启动 Spider 失败，请检查采集端环境") from exc

    return {
        "task_id": task.task_id,
        "status": "running",
        "spider": spider,
        "pid": proc.pid,
        "log": str(log_path),
    }