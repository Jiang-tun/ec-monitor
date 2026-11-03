import json
import os
import random
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from pathlib import Path

from redis import Redis as RedisPy

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NOT_FOUND, PARAM_INVALID, INTERNAL_ERROR, BizError
from app.dao import sms as sms_dao
from app.db.models import Platform, SmsOrder
from app.schemas.sms import SmsOrderCreate, SmsOrderOut, SmsResultIn
from app.service import platform_login as login_service


# ==================== 接码平台适配器 ====================
# 新增接码平台时，实现下列方法并注册到 ADAPTERS 即可；
# 前端无需改动。示例：
#   class FiveSimAdapter:
#       def acquire(self, order, provider): ...  # 返回 {"phone", "provider_order_id", "raw"}
#       def fetch_code(self, order, provider): ...  # 返回验证码字符串或 None
#   ADAPTERS["5sim"] = FiveSimAdapter()
# ====================


class MockAdapter:
    """开发用模拟接码：固定返回测试号码与验证码。"""

    def acquire(self, order, provider) -> dict:
        phone = "138" + "".join(str(random.randint(0, 9)) for _ in range(8))
        return {
            "phone": phone,
            "provider_order_id": "mock-" + uuid.uuid4().hex[:12],
            "raw": {"provider": "mock"},
        }

    def fetch_code(self, order, provider) -> Optional[str]:
        return "123456"

    def release(self, order, provider) -> None:
        return None


ADAPTERS = {"mock": MockAdapter()}

settings = get_settings()
QUEUE_PREFIX = "ecom:sc:sms:"

_CRAWL_DIR = Path(__file__).resolve().parents[2] / "crawl"
_SMS_LOG_DIR = Path(__file__).resolve().parents[2] / "logs" / "sms"

# queue 模式下，provider_code -> scrapy spider 名称
SMS_SPIDERS = {"smsnam": "smsnam"}


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


def _ensure_worker(provider_code: str) -> None:
    """确保接码 Spider 在运行（按 provider 维度单实例）。"""
    spider = SMS_SPIDERS.get(provider_code)
    if not spider:
        return

    redis = RedisPy.from_url(settings.redis_url_compat)
    lock_key = f"sms:worker:{provider_code}"
    current = redis.get(lock_key)
    if current:
        try:
            if _worker_alive(int(current)):
                return
        except (TypeError, ValueError):
            pass
        redis.delete(lock_key)

    _SMS_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _SMS_LOG_DIR / f"{provider_code}.log"

    cmd = [
        sys.executable,
        "-m",
        "scrapy",
        "crawl",
        spider,
        "-a",
        "site_group=default",
        "-s",
        "CLOSESPIDER_TIMEOUT=300",
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
    except Exception:  # noqa: BLE001 启动失败不阻塞入队，前端会保持 pending
        return

    redis.set(lock_key, str(proc.pid), ex=300)


def _is_queue_mode(provider) -> bool:
    return (provider.config_json or {}).get("mode") == "queue"


def _push(seed: dict, provider_code: str) -> None:
    try:
        RedisPy.from_url(settings.redis_url_compat).lpush(
            f"{QUEUE_PREFIX}{provider_code}",
            json.dumps(seed, ensure_ascii=False),
        )
    except Exception as exc:  # noqa: BLE001
        raise BizError(INTERNAL_ERROR, "接码任务队列不可用，请检查 Redis") from exc


def _adapter(code: str):
    adapter = ADAPTERS.get(code)
    if not adapter:
        raise BizError(
            INTERNAL_ERROR,
            f"接码平台 {code} 适配器未实现（请在 app/service/sms.py 的 ADAPTERS 中注册）",
        )
    return adapter


def _out(order: SmsOrder) -> SmsOrderOut:
    return SmsOrderOut.model_validate(order)


def list_providers(db: Session, enabled_only: bool = True):
    return sms_dao.list_providers(db, enabled_only=enabled_only)


def list_orders(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    provider_id: Optional[int] = None,
    platform_id: Optional[int] = None,
    status: Optional[str] = None,
) -> tuple[List[SmsOrderOut], int]:
    rows, total = sms_dao.list_orders(
        db,
        page=page,
        page_size=page_size,
        provider_id=provider_id,
        platform_id=platform_id,
        status=status,
    )
    return [_out(r) for r in rows], total


def get_order(db: Session, order_id: int) -> SmsOrderOut:
    order = sms_dao.get_order(db, order_id)
    if not order:
        raise BizError(NOT_FOUND, "接码订单不存在")
    return _out(order)


def acquire_number(
    db: Session, data: SmsOrderCreate, created_by: Optional[str] = None
) -> SmsOrderOut:
    if data.provider_id:
        provider = sms_dao.get_provider(db, data.provider_id)
    else:
        provider = sms_dao.get_provider_by_code(db, "smsnam")
    if not provider or provider.enabled != 1:
        raise BizError(PARAM_INVALID, "接码平台不存在或已停用")
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
        raise BizError(PARAM_INVALID, "目标平台不存在或已停用")

    order = sms_dao.create_order(
        db,
        provider_id=provider.id,
        provider_code=provider.code,
        platform_id=platform.id,
        platform_code=platform.code,
        status="pending",
        created_by=created_by,
    )

    if _is_queue_mode(provider):
        _push(
            {
                "action": "acquire",
                "order_id": order.id,
                "provider_id": provider.id,
                "provider_code": provider.code,
                "platform_id": platform.id,
            },
            provider.code,
        )
        _ensure_worker(provider.code)
        return _out(order)

    try:
        result = _adapter(provider.code).acquire(order, provider)
    except BizError as exc:
        sms_dao.update_order(
            db, order, status="failed", error=str(exc.message)[:512]
        )
        raise
    except Exception as exc:  # noqa: BLE001
        sms_dao.update_order(
            db, order, status="failed", error=f"取号失败: {type(exc).__name__}"
        )
        raise BizError(INTERNAL_ERROR, "接码平台取号失败") from exc

    phone = str(result.get("phone") or "").strip()
    if not phone:
        sms_dao.update_order(db, order, status="failed", error="接码平台未返回手机号")
        raise BizError(INTERNAL_ERROR, "接码平台未返回手机号")

    sms_dao.update_order(
        db,
        order,
        status="number_ready",
        phone=phone,
        provider_order_id=str(result.get("provider_order_id") or "") or None,
        raw_json=result,
        expires_at=datetime.now() + timedelta(minutes=10),
        error=None,
    )
    return _out(order)


def fetch_code(db: Session, order_id: int) -> SmsOrderOut:
    order = sms_dao.get_order(db, order_id)
    if not order:
        raise BizError(NOT_FOUND, "接码订单不存在")
    if order.status not in ("number_ready", "code_ready"):
        raise BizError(PARAM_INVALID, f"当前状态（{order.status}）不能获取验证码")

    provider = sms_dao.get_provider(db, order.provider_id)
    if not provider:
        raise BizError(PARAM_INVALID, "接码平台不存在")

    if _is_queue_mode(provider):
        code_url = (order.raw_json or {}).get("code_url")
        if not code_url:
            raise BizError(PARAM_INVALID, "未获取到接码页面地址，请重新获取手机号")
        _push(
            {
                "action": "fetch_code",
                "order_id": order.id,
                "provider_id": provider.id,
                "provider_code": provider.code,
                "platform_code": order.platform_code,
                "code_url": code_url,
            },
            provider.code,
        )
        _ensure_worker(provider.code)
        return _out(order)

    code = _adapter(provider.code).fetch_code(order, provider)
    if not code:
        return _out(order)

    sms_dao.update_order(db, order, status="code_ready", sms_code=str(code)[:16])
    return _out(order)


def submit_login(db: Session, order_id: int, created_by: Optional[str] = None) -> dict:
    order = sms_dao.get_order(db, order_id)
    if not order:
        raise BizError(NOT_FOUND, "接码订单不存在")
    if order.status != "code_ready" or not order.phone or not order.sms_code:
        raise BizError(PARAM_INVALID, "请先获取手机号和验证码")

    code_url = (order.raw_json or {}).get("code_url")
    login = login_service.create_login_with_code(
        db,
        platform_id=order.platform_id,
        phone=order.phone,
        code=order.sms_code,
        created_by=created_by,
        code_url=code_url,
        sms_order_id=order.id,
    )
    sms_dao.update_order(db, order, status="logging", login_id=login.id)
    return {"order": _out(order).model_dump(), "login": login.model_dump()}


def cancel_order(db: Session, order_id: int) -> SmsOrderOut:
    order = sms_dao.get_order(db, order_id)
    if not order:
        raise BizError(NOT_FOUND, "接码订单不存在")
    if order.status in ("success", "failed", "cancelled", "expired"):
        raise BizError(PARAM_INVALID, "当前状态不能取消")

    provider = sms_dao.get_provider(db, order.provider_id)
    if provider:
        try:
            _adapter(provider.code).release(order, provider)
        except Exception:  # noqa: BLE001 释放失败不影响本地取消
            pass
    sms_dao.update_order(db, order, status="cancelled")
    return _out(order)


def handle_result(db: Session, data: SmsResultIn) -> SmsOrderOut:
    """采集节点回写接码结果（取号 / 取码）。"""
    order = sms_dao.get_order(db, data.order_id)
    if not order:
        raise BizError(NOT_FOUND, "接码订单不存在")

    raw = dict(order.raw_json or {})
    if data.raw:
        raw.update(data.raw)
    if data.code_url:
        raw["code_url"] = data.code_url

    if data.action == "acquire":
        if data.status == "success":
            phone = (data.phone or "").strip()
            if not phone:
                sms_dao.update_order(
                    db, order, status="failed", error="采集节点未返回手机号"
                )
            else:
                sms_dao.update_order(
                    db,
                    order,
                    status="number_ready",
                    phone=phone,
                    provider_order_id=data.provider_order_id,
                    raw_json=raw or None,
                    error=None,
                    expires_at=datetime.now() + timedelta(minutes=10),
                )
        elif data.status == "failed":
            sms_dao.update_order(
                db, order, status="failed", error=(data.error or "取号失败")[:512]
            )
        else:
            sms_dao.update_order(db, order, raw_json=raw or None)
    else:  # fetch_code
        if data.status == "success":
            code = (data.code or "").strip()
            if not code:
                sms_dao.update_order(db, order, raw_json=raw or None)
            else:
                sms_dao.update_order(
                    db,
                    order,
                    status="code_ready",
                    sms_code=code[:16],
                    raw_json=raw or None,
                    error=None,
                )
        elif data.status == "failed":
            sms_dao.update_order(
                db, order, status="failed", error=(data.error or "取码失败")[:512]
            )
        else:
            sms_dao.update_order(db, order, raw_json=raw or None)
    return _out(order)