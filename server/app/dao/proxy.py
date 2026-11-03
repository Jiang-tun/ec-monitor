from typing import List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.models import Proxy


def list_proxies(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    bind_site_group: Optional[str] = None,
    available: Optional[bool] = None,
    protocol: Optional[str] = None,
    keyword: Optional[str] = None,
) -> Tuple[List[Proxy], int]:
    q = db.query(Proxy).filter(Proxy.is_deleted == 0)
    if bind_site_group:
        q = q.filter(Proxy.bind_site_group == bind_site_group)
    if protocol:
        q = q.filter(Proxy.protocol == protocol)
    if available is not None:
        q = q.filter(Proxy.available == (1 if available else 0))
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(or_(Proxy.ip.ilike(like), Proxy.source.ilike(like)))
    total = q.count()
    rows = (
        q.order_by(Proxy.is_active.desc(), Proxy.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total


def exists(db: Session, ip: str, port: int) -> bool:
    return (
        db.query(Proxy)
        .filter(Proxy.ip == ip, Proxy.port == port, Proxy.is_deleted == 0)
        .first()
        is not None
    )


def add_proxy(db: Session, **kwargs) -> Proxy:
    obj = Proxy(**kwargs)
    db.add(obj)
    db.flush()
    return obj


def create_proxy(db: Session, **kwargs) -> Proxy:
    obj = add_proxy(db, **kwargs)
    db.commit()
    db.refresh(obj)
    return obj


def get_proxy(db: Session, proxy_id: int) -> Optional[Proxy]:
    return (
        db.query(Proxy)
        .filter(Proxy.id == proxy_id, Proxy.is_deleted == 0)
        .first()
    )


def update_proxy(db: Session, proxy_id: int, **kwargs) -> Optional[Proxy]:
    proxy = get_proxy(db, proxy_id)
    if not proxy:
        return None
    for k, v in kwargs.items():
        setattr(proxy, k, v)
    db.commit()
    db.refresh(proxy)
    return proxy


def delete_proxy(db: Session, proxy_id: int) -> bool:
    proxy = get_proxy(db, proxy_id)
    if not proxy:
        return False
    proxy.is_deleted = 1
    proxy.is_active = 0
    db.commit()
    return True


def toggle_proxy(db: Session, proxy_id: int, available: bool) -> Optional[Proxy]:
    proxy = get_proxy(db, proxy_id)
    if not proxy:
        return None
    proxy.available = 1 if available else 0
    if not available:
        proxy.is_active = 0
    db.commit()
    db.refresh(proxy)
    return proxy


def get_active_proxy(db: Session) -> Optional[Proxy]:
    return (
        db.query(Proxy)
        .filter(Proxy.is_active == 1, Proxy.is_deleted == 0)
        .first()
    )


def set_active_proxy(db: Session, proxy_id: int) -> Optional[Proxy]:
    """全局唯一启用：先把所有代理 is_active 置 0，再启用指定代理。"""
    proxy = get_proxy(db, proxy_id)
    if not proxy:
        return None
    db.query(Proxy).filter(Proxy.is_active == 1).update(
        {"is_active": 0}, synchronize_session=False
    )
    proxy.is_active = 1
    proxy.available = 1
    db.add(proxy)
    db.commit()
    db.refresh(proxy)
    return proxy


def clear_active_proxy(db: Session) -> int:
    n = (
        db.query(Proxy)
        .filter(Proxy.is_active == 1)
        .update({"is_active": 0}, synchronize_session=False)
    )
    db.commit()
    return n


def get_proxy_stats(db: Session) -> dict:
    q = db.query(Proxy).filter(Proxy.is_deleted == 0)
    total = q.count()
    enabled = q.filter(Proxy.available == 1).count()
    disabled = total - enabled
    avg = (
        db.query(func.avg(Proxy.response_time))
        .filter(Proxy.is_deleted == 0, Proxy.response_time.isnot(None))
        .scalar()
    )
    return {
        "total": total,
        "enabled": enabled,
        "disabled": disabled,
        "avg_response_time": float(avg) if avg is not None else None,
    }
