import json
import socket
import time
from datetime import datetime
from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from redis import Redis as RedisPy
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.dao import proxy as proxy_dao
from app.db.models import Proxy
from app.schemas.proxy import (
    ProxyBatchIn,
    ProxyCreate,
    ProxyOut,
    ProxyStatsOut,
    ProxyTestRequest,
    ProxyTestResult,
    ProxyUpdate,
)

settings = get_settings()

ALLOWED_PROTOCOLS = ("http", "https", "socks5")


# ==================== Redis：当前采集使用的代理 ====================

def _redis() -> RedisPy:
    return RedisPy.from_url(settings.redis_url_compat)


def _write_active(proxy: Proxy) -> None:
    payload = {
        "id": proxy.id,
        "protocol": proxy.protocol,
        "server": f"{proxy.protocol}://{proxy.ip}:{proxy.port}",
        "username": proxy.username or "",
        "password": proxy.password_enc or "",
    }
    try:
        r = _redis()
        r.set("proxy:active", json.dumps(payload, ensure_ascii=False))
        r.set("proxy:active:ts", int(time.time()))
    except Exception:  # noqa: BLE001 Redis 不可用不影响数据库标记
        pass


def _clear_active() -> None:
    try:
        r = _redis()
        r.delete("proxy:active")
        # 更新时间戳，触发详情 Worker 重启以停用代理
        r.set("proxy:active:ts", int(time.time()))
    except Exception:  # noqa: BLE001
        pass


# ==================== CRUD ====================

def list_proxies_service(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    bind_site_group: Optional[str] = None,
    available: Optional[bool] = None,
    protocol: Optional[str] = None,
    keyword: Optional[str] = None,
) -> Tuple[List[ProxyOut], int]:
    rows, total = proxy_dao.list_proxies(
        db=db,
        page=page,
        page_size=page_size,
        bind_site_group=bind_site_group,
        available=available,
        protocol=protocol,
        keyword=keyword,
    )
    return [ProxyOut.model_validate(r) for r in rows], total


def create_proxy_service(db: Session, data: ProxyCreate) -> ProxyOut:
    if proxy_dao.exists(db, data.ip, data.port):
        raise HTTPException(status_code=400, detail="该代理已存在")
    obj = proxy_dao.create_proxy(db=db, **data.model_dump())
    return ProxyOut.model_validate(obj)


def get_proxy_service(db: Session, proxy_id: int) -> ProxyOut:
    proxy = proxy_dao.get_proxy(db, proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="代理不存在")
    return ProxyOut.model_validate(proxy)


def update_proxy_service(db: Session, proxy_id: int, data: ProxyUpdate) -> ProxyOut:
    proxy = proxy_dao.get_proxy(db, proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="代理不存在")
    update_data = {
        k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None
    }
    proxy = proxy_dao.update_proxy(db=db, proxy_id=proxy_id, **update_data)
    return ProxyOut.model_validate(proxy)


def delete_proxy_service(db: Session, proxy_id: int) -> None:
    proxy = proxy_dao.get_proxy(db, proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="代理不存在")
    was_active = proxy.is_active == 1
    proxy_dao.delete_proxy(db, proxy_id)
    if was_active:
        _clear_active()


def toggle_proxy_service(db: Session, proxy_id: int, enabled: bool) -> ProxyOut:
    proxy = proxy_dao.toggle_proxy(db=db, proxy_id=proxy_id, available=enabled)
    if not proxy:
        raise HTTPException(status_code=404, detail="代理不存在")
    # 同步 Redis 中的当前启用代理
    active = proxy_dao.get_active_proxy(db)
    if active:
        _write_active(active)
    else:
        _clear_active()
    return ProxyOut.model_validate(proxy)


# ==================== 选择使用 / 取消（全局唯一） ====================

def activate_proxy_service(db: Session, proxy_id: int) -> ProxyOut:
    proxy = proxy_dao.set_active_proxy(db, proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="代理不存在")
    _write_active(proxy)
    return ProxyOut.model_validate(proxy)


def deactivate_proxy_service(db: Session) -> dict:
    n = proxy_dao.clear_active_proxy(db)
    _clear_active()
    return {"cleared": n}


def get_active_proxy_service(db: Session) -> Optional[dict]:
    proxy = proxy_dao.get_active_proxy(db)
    if not proxy:
        return None
    return ProxyOut.model_validate(proxy).model_dump()


# ==================== 批量录入 ====================

def _parse_line(raw: str, default_protocol: str) -> dict:
    """解析一条代理，支持：
        ip:port
        ip:port:username:password
        protocol://ip:port
        protocol://username:password@ip:port
    """
    line = raw.strip()
    if not line or line.startswith("#") or line.startswith("//"):
        raise ValueError("空行/注释")

    protocol = default_protocol
    rest = line
    if "://" in line:
        protocol, rest = line.split("://", 1)
        protocol = protocol.strip().lower()
    if protocol not in ALLOWED_PROTOCOLS:
        raise ValueError(f"不支持的协议 {protocol}")

    username = None
    password = None
    if "@" in rest:
        userinfo, rest = rest.split("@", 1)
        if ":" in userinfo:
            username, password = userinfo.split(":", 1)
        else:
            username = userinfo

    parts = rest.split(":")
    if len(parts) >= 4 and username is None:
        ip, port_s, username, password = parts[0], parts[1], parts[2], ":".join(parts[3:])
    elif len(parts) == 2:
        ip, port_s = parts[0], parts[1]
    else:
        raise ValueError("格式不正确，应为 ip:port 或 ip:port:user:pass")

    ip = ip.strip()
    if not ip:
        raise ValueError("IP 为空")
    try:
        port = int(port_s)
    except (TypeError, ValueError):
        raise ValueError(f"端口非法: {port_s}")
    if not (1 <= port <= 65535):
        raise ValueError("端口超出范围")
    return {
        "ip": ip,
        "port": port,
        "protocol": protocol,
        "username": (username or None),
        "password_enc": (password or None),
    }


def batch_create_service(db: Session, data: ProxyBatchIn) -> dict:
    created = 0
    skipped = 0
    errors: List[dict] = []
    seen_ip_port = set()

    for idx, line in enumerate(data.text.splitlines(), start=1):
        try:
            item = _parse_line(line, data.protocol)
        except ValueError as exc:
            if str(exc) == "空行/注释":
                continue
            errors.append({"line": idx, "text": line[:80], "reason": str(exc)})
            continue

        key = (item["ip"], item["port"])
        if key in seen_ip_port or proxy_dao.exists(db, item["ip"], item["port"]):
            skipped += 1
            continue
        seen_ip_port.add(key)
        proxy_dao.add_proxy(
            db,
            bind_site_group=data.bind_site_group or "default",
            source=data.source or "batch-import",
            available=1,
            **item,
        )
        created += 1

    db.commit()
    return {"created": created, "skipped": skipped, "errors": errors}


# ==================== 统计 / 测试 ====================

def get_proxy_stats_service(db: Session) -> ProxyStatsOut:
    return ProxyStatsOut(**proxy_dao.get_proxy_stats(db=db))


def test_proxy_service(db: Session, data: ProxyTestRequest) -> ProxyTestResult:
    proxy = proxy_dao.get_proxy(db, data.proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="代理不存在")

    start = datetime.now()
    success = False
    error: Optional[str] = None
    try:
        with socket.create_connection((proxy.ip, proxy.port), timeout=data.timeout):
            success = True
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
    response_time = int((datetime.now() - start).total_seconds() * 1000)

    proxy_dao.update_proxy(
        db=db,
        proxy_id=proxy.id,
        last_check_at=datetime.now(),
        last_used_at=datetime.now(),
        response_time=response_time,
        available=1 if success else 0,
        fail_count=0 if success else (proxy.fail_count or 0) + 1,
    )
    active = proxy_dao.get_active_proxy(db)
    if active:
        _write_active(active)

    return ProxyTestResult(
        proxy_id=proxy.id,
        success=success,
        response_time=response_time,
        status_code=200 if success else None,
        error=error,
        tested_at=datetime.now(),
    )
