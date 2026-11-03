from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import SmsOrder, SmsProvider


def list_providers(db: Session, enabled_only: bool = False) -> List[SmsProvider]:
    q = db.query(SmsProvider)
    if enabled_only:
        q = q.filter(SmsProvider.enabled == 1)
    return q.order_by(SmsProvider.id.asc()).all()


def get_provider(db: Session, provider_id: int) -> Optional[SmsProvider]:
    return db.query(SmsProvider).filter(SmsProvider.id == provider_id).first()


def get_provider_by_code(db: Session, code: str) -> Optional[SmsProvider]:
    return db.query(SmsProvider).filter(SmsProvider.code == code).first()


def create_order(db: Session, **kwargs) -> SmsOrder:
    obj = SmsOrder(**kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_order(db: Session, order_id: int) -> Optional[SmsOrder]:
    return db.query(SmsOrder).filter(SmsOrder.id == order_id).first()


def list_orders(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    provider_id: Optional[int] = None,
    platform_id: Optional[int] = None,
    status: Optional[str] = None,
) -> Tuple[List[SmsOrder], int]:
    q = db.query(SmsOrder)
    if provider_id is not None:
        q = q.filter(SmsOrder.provider_id == provider_id)
    if platform_id is not None:
        q = q.filter(SmsOrder.platform_id == platform_id)
    if status:
        q = q.filter(SmsOrder.status == status)
    total = q.count()
    rows = (
        q.order_by(SmsOrder.created_at.desc(), SmsOrder.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total


def update_order(db: Session, order: SmsOrder, **fields) -> SmsOrder:
    for key, value in fields.items():
        setattr(order, key, value)
    db.commit()
    db.refresh(order)
    return order
