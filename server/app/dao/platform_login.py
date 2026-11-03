from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import PlatformLogin


def create_login(db: Session, **kwargs) -> PlatformLogin:
    obj = PlatformLogin(**kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_login(db: Session, login_id: int) -> Optional[PlatformLogin]:
    return db.query(PlatformLogin).filter(PlatformLogin.id == login_id).first()


def list_logins(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    platform_id: Optional[int] = None,
    status: Optional[str] = None,
) -> Tuple[List[PlatformLogin], int]:
    q = db.query(PlatformLogin)
    if platform_id is not None:
        q = q.filter(PlatformLogin.platform_id == platform_id)
    if status:
        q = q.filter(PlatformLogin.status == status)
    total = q.count()
    rows = (
        q.order_by(PlatformLogin.created_at.desc(), PlatformLogin.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total


def update_login(db: Session, login: PlatformLogin, **fields) -> PlatformLogin:
    for key, value in fields.items():
        setattr(login, key, value)
    db.commit()
    db.refresh(login)
    return login
