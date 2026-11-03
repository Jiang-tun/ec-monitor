import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional

from redis import Redis as RedisPy
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import INTERNAL_ERROR, NOT_FOUND, PARAM_INVALID, BizError
from app.dao import platform_login as login_dao
from app.db.models import Platform
from app.schemas.platform_login import (
    PlatformLoginCreate,
    PlatformLoginOut,
    PlatformLoginResultIn,
)

settings = get_settings()

_CRAWL_DIR = Path(__file__).resolve().parents[2] / "crawl"
COOKIES_DIR = _CRAWL_DIR / "cookies"
STORAGE_DIR = _CRAWL_DIR / "storage"
_LOGIN_LOG_DIR = _CRAWL_DIR.parent / "logs" / "login"

# 登录 Spider 名称（scrapy crawl login -a platform_code=xxx）
LOGIN_SPIDER = "login"


def _redis() -> RedisPy:
    return RedisPy.from_url(settings.redis_url_compat)


def _queue_key(platform_code: str) -> str:
    return f"ecom:sc:login:{platform_code}"


def _worker_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        return str(pid) in out
    except Exception:  # noqa: BLE001
        return False


def _ensure_login_worker(platform_code: str) -> None:
    """确保该平台的登录 Spider 在运行（按平台维度单实例）。

    Playwright 登录是低频、长耗时任务，启动一个常驻 5 分钟的队列消费进程即可。
    """
    if not platform_code:
        return

    redis = _redis()
    lock_key = f"login:worker:{platform_code}"
    current = redis.get(lock_key)
    if current:
        try:
            if _worker_alive(int(current)):
                return
        except (TypeError, ValueError):
            pass
        redis.delete(lock_key)

    _LOGIN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOGIN_LOG_DIR / f"{platform_code}.log"

    cmd = [
        sys.executable,
        "-m",
        "scrapy",
        "crawl",
        LOGIN_SPIDER,
        "-a",
        f"platform_code={platform_code}",
        "-a",
        "site_group=default",
        "-s",
        "CLOSESPIDER_TIMEOUT=600",
    ]
    env = os.environ.copy()
    env["INTERNAL_API_BASE"] = os.environ.get(
        "INTERNAL_API_BASE", "http://127.0.0.1:8000"
    )
    env["NODE_API_KEY"] = settings.node_api_key

    flags = 0x00000200 | 0x08000000 if os.name == "nt" else 0

    try:
        with open(log_path, "ab") as log_file:
            proc = subprocess.Popen(
                cmd,
                cwd=str(_CRAWL_DIR),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=flags,
            )
    except Exception:  # noqa: BLE001 启动失败不阻塞入队
        return

    redis.set(lock_key, str(proc.pid), ex=600)


def _push(seed: dict, queue_key: str) -> None:
    try:
        _redis().lpush(queue_key, json.dumps(seed, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        raise BizError(INTERNAL_ERROR, "登录队列不可用，请检查 Redis") from exc


def _out(row) -> PlatformLoginOut:
    return PlatformLoginOut.model_validate(row)


def create_login(
    db: Session, data: PlatformLoginCreate, created_by: Optional[str] = None
) -> PlatformLoginOut:
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

    login = login_dao.create_login(
        db,
        platform_id=platform.id,
        platform_code=platform.code,
        phone=data.phone,
        status="pending",
        created_by=created_by,
    )

    seed = {
        "action": "send_code",
        "login_id": login.id,
        "platform_id": platform.id,
        "platform_code": platform.code,
        "phone": data.phone,
    }
    try:
        _push(seed, _queue_key(platform.code))
    except BizError as exc:
        login_dao.update_login(
            db, login, status="failed", error="入队失败：登录队列不可用"
        )
        raise exc

    login_dao.update_login(db, login, status="code_sent")
    _ensure_login_worker(platform.code)
    return _out(login)


def submit_code(db: Session, login_id: int, code: str) -> PlatformLoginOut:
    login = login_dao.get_login(db, login_id)
    if not login:
        raise BizError(NOT_FOUND, "登录会话不存在")
    if login.status in ("success", "expired", "cancelled", "failed"):
        raise BizError(PARAM_INVALID, f"当前状态（{login.status}）不能提交验证码")

    seed = {
        "action": "submit_code",
        "login_id": login.id,
        "platform_id": login.platform_id,
        "platform_code": login.platform_code,
        "phone": login.phone,
        "code": code,
    }
    _push(seed, _queue_key(login.platform_code))
    login_dao.update_login(db, login, status="verifying", error=None)
    _ensure_login_worker(login.platform_code)
    return _out(login)


def create_login_with_code(
    db: Session,
    platform_id: int,
    phone: str,
    code: str,
    created_by: Optional[str] = None,
    code_url: Optional[str] = None,
    sms_order_id: Optional[int] = None,
) -> PlatformLoginOut:
    """已有手机号+验证码时直接创建登录会话并投递验证任务（供接码流程使用）。

    若提供 ``code_url`` / ``sms_order_id``，走 ``login_auto``：节点会重新发码并
    轮询接码页面拿到最新验证码，避免使用过期的旧码。
    """
    platform = (
        db.query(Platform)
        .filter(
            Platform.id == platform_id,
            Platform.status == 1,
            Platform.is_deleted == 0,
        )
        .first()
    )
    if not platform:
        raise BizError(PARAM_INVALID, "平台不存在或已停用")

    login = login_dao.create_login(
        db,
        platform_id=platform.id,
        platform_code=platform.code,
        phone=phone,
        status="verifying",
        created_by=created_by,
    )
    auto = bool(code_url or sms_order_id)
    seed = {
        "action": "login_auto" if auto else "submit_code",
        "login_id": login.id,
        "platform_id": platform.id,
        "platform_code": platform.code,
        "phone": phone,
        "code": code,
        "code_url": code_url,
        "sms_order_id": sms_order_id,
    }
    _push(seed, _queue_key(platform.code))
    _ensure_login_worker(platform.code)
    return _out(login)


def list_logins(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    platform_id: Optional[int] = None,
    status: Optional[str] = None,
) -> tuple[List[PlatformLoginOut], int]:
    rows, total = login_dao.list_logins(
        db, page=page, page_size=page_size, platform_id=platform_id, status=status
    )
    return [_out(r) for r in rows], total


def get_login(db: Session, login_id: int) -> PlatformLoginOut:
    login = login_dao.get_login(db, login_id)
    if not login:
        raise BizError(NOT_FOUND, "登录会话不存在")
    return _out(login)


def cancel_login(db: Session, login_id: int) -> PlatformLoginOut:
    login = login_dao.get_login(db, login_id)
    if not login:
        raise BizError(NOT_FOUND, "登录会话不存在")
    if login.status in ("success", "expired"):
        raise BizError(PARAM_INVALID, "登录已完成，不能取消")
    login_dao.update_login(db, login, status="cancelled")
    return _out(login)


def _normalize_cookies(raw: Any, storage_state: Optional[dict]) -> Optional[dict]:
    """把节点回传的 Cookie（dict 或 Playwright cookies 数组）规整成 name->value。"""
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        result = {}
        for item in raw:
            if isinstance(item, dict) and item.get("name"):
                result[str(item["name"])] = str(item.get("value", ""))
        return result or None
    if storage_state and isinstance(storage_state.get("cookies"), list):
        return _normalize_cookies(storage_state["cookies"], None)
    return None


def _merge_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
    if isinstance(existing, dict):
        existing.update(payload)
        payload = existing
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def handle_result(db: Session, data: PlatformLoginResultIn) -> PlatformLoginOut:
    """节点回调：保存登录态 Cookie / storage_state，并更新会话状态。"""
    login = login_dao.get_login(db, data.login_id)
    if not login:
        raise BizError(NOT_FOUND, "登录会话不存在")

    if data.status == "success":
        cookies = _normalize_cookies(data.cookies, data.storage_state)
        if not cookies and not data.storage_state:
            raise BizError(PARAM_INVALID, "登录成功但未回传 Cookie/storage_state")

        if cookies:
            _merge_write(COOKIES_DIR / f"{login.platform_code}.json", cookies)
        if data.storage_state:
            _merge_write(
                STORAGE_DIR / f"{login.platform_code}.json", data.storage_state
            )

        login_dao.update_login(
            db,
            login,
            status="success",
            cookies=cookies,
            storage_state=data.storage_state,
            error=None,
            expires_at=datetime.now() + timedelta(days=7),
        )
    else:
        login_dao.update_login(
            db,
            login,
            status=data.status,
            error=(data.error or "登录失败")[:512],
        )

    # 同步登录会话状态（不再同步接码订单状态）

    return _out(login)
