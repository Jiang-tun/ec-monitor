from typing import List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.models import (
    OperationLog,
    SysDict,
    SysDictItem,
    SysRole,
    SysUser,
    SysUserRole,
)


# ==================== 字典类型表 ====================


def list_dicts(db: Session, page: int = 1, page_size: int = 20, keyword: Optional[str] = None) -> Tuple[List[SysDict], int]:
    """分页查询字典类型"""
    q = db.query(SysDict).filter(SysDict.is_deleted == 0)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(or_(SysDict.dict_name.ilike(like), SysDict.dict_code.ilike(like)))
    total = q.count()
    rows = q.order_by(SysDict.sort.asc(), SysDict.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def get_dict_by_code(db: Session, code: str) -> Optional[SysDict]:
    """根据编码获取字典类型"""
    return db.query(SysDict).filter(SysDict.dict_code == code, SysDict.is_deleted == 0).first()


def create_dict(db: Session, **kwargs) -> SysDict:
    """新增字典类型"""
    obj = SysDict(**kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_dict(db: Session, dict_code: str, **kwargs) -> Optional[SysDict]:
    """更新字典类型"""
    item = get_dict_by_code(db, dict_code)
    if not item:
        return None
    for k, v in kwargs.items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


def delete_dict(db: Session, dict_code: str) -> bool:
    """删除字典类型（级联删除字典项）"""
    item = get_dict_by_code(db, dict_code)
    if not item:
        return False
    db.query(SysDictItem).filter(SysDictItem.dict_code == dict_code).delete()
    item.is_deleted = 1
    db.commit()
    return True


# ==================== 字典项表 ====================


def list_dict_items(db: Session, dict_code: str, page: int = 1, page_size: int = 20, status: Optional[int] = None, keyword: Optional[str] = None) -> Tuple[List[SysDictItem], int]:
    """分页查询字典项"""
    q = db.query(SysDictItem).filter(SysDictItem.dict_code == dict_code, SysDictItem.is_deleted == 0)
    if status is not None:
        q = q.filter(SysDictItem.status == status)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(or_(SysDictItem.dict_label.ilike(like), SysDictItem.dict_value.ilike(like)))
    total = q.count()
    rows = q.order_by(SysDictItem.sort.asc()).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def get_dict_item(db: Session, item_id: int) -> Optional[SysDictItem]:
    """根据 ID 获取字典项"""
    return db.query(SysDictItem).filter(SysDictItem.id == item_id, SysDictItem.is_deleted == 0).first()


def create_dict_item(db: Session, **kwargs) -> SysDictItem:
    """新增字典项"""
    obj = SysDictItem(**kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_dict_item(db: Session, item_id: int, **kwargs) -> Optional[SysDictItem]:
    """更新字典项"""
    item = get_dict_item(db, item_id)
    if not item:
        return None
    for k, v in kwargs.items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


def delete_dict_item(db: Session, item_id: int) -> bool:
    """逻辑删除字典项"""
    item = get_dict_item(db, item_id)
    if not item:
        return False
    item.is_deleted = 1
    db.commit()
    return True


# ==================== 用户表 ====================


def list_users(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
    status: Optional[int] = None,
) -> Tuple[List[SysUser], int]:
    q = db.query(SysUser)
    if status is not None:
        q = q.filter(SysUser.status == status)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            or_(
                SysUser.username.ilike(like),
                SysUser.nickname.ilike(like),
                SysUser.email.ilike(like),
            )
        )
    total = q.count()
    rows = (
        q.order_by(SysUser.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total


def get_user(db: Session, user_id: int) -> Optional[SysUser]:
    return db.query(SysUser).filter(SysUser.id == user_id).first()


def get_user_by_username(db: Session, username: str) -> Optional[SysUser]:
    return db.query(SysUser).filter(SysUser.username == username).first()


def create_user(db: Session, **kwargs) -> SysUser:
    obj = SysUser(**kwargs)
    db.add(obj)
    db.flush()
    return obj


def delete_user(db: Session, user: SysUser) -> None:
    db.query(SysUserRole).filter(SysUserRole.user_id == user.id).delete()
    db.delete(user)
    db.commit()


def get_user_role_ids(db: Session, user_id: int) -> List[int]:
    rows = db.query(SysUserRole.role_id).filter(SysUserRole.user_id == user_id).all()
    return [r[0] for r in rows]


def set_user_roles(db: Session, user_id: int, role_ids: List[int]) -> None:
    db.query(SysUserRole).filter(SysUserRole.user_id == user_id).delete()
    for rid in dict.fromkeys(role_ids):
        db.add(SysUserRole(user_id=user_id, role_id=rid))
    db.commit()


# ==================== 角色表 ====================


def list_roles(db: Session, keyword: Optional[str] = None) -> List[SysRole]:
    q = db.query(SysRole)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(or_(SysRole.role_code.ilike(like), SysRole.role_name.ilike(like)))
    return q.order_by(SysRole.id.asc()).all()


def get_role(db: Session, role_id: int) -> Optional[SysRole]:
    return db.query(SysRole).filter(SysRole.id == role_id).first()


def get_role_by_code(db: Session, role_code: str) -> Optional[SysRole]:
    return db.query(SysRole).filter(SysRole.role_code == role_code).first()


def create_role(db: Session, **kwargs) -> SysRole:
    obj = SysRole(**kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def delete_role(db: Session, role: SysRole) -> None:
    db.query(SysUserRole).filter(SysUserRole.role_id == role.id).delete()
    db.delete(role)
    db.commit()


def count_role_users(db: Session) -> dict:
    rows = (
        db.query(SysUserRole.role_id, func.count(SysUserRole.id))
        .group_by(SysUserRole.role_id)
        .all()
    )
    return {rid: cnt for rid, cnt in rows}


# ==================== 操作日志 ====================


def list_operation_logs(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    operator: Optional[str] = None,
    action: Optional[str] = None,
    result: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Tuple[List[OperationLog], int]:
    q = db.query(OperationLog)
    if operator:
        q = q.filter(OperationLog.operator.ilike(f"%{operator}%"))
    if action:
        q = q.filter(OperationLog.action.ilike(f"%{action}%"))
    if result:
        q = q.filter(OperationLog.result == result)
    if start:
        q = q.filter(OperationLog.created_at >= start)
    if end:
        q = q.filter(OperationLog.created_at <= end)
    total = q.count()
    rows = (
        q.order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total


def create_operation_log(db: Session, **kwargs) -> OperationLog:
    obj = OperationLog(**kwargs)
    db.add(obj)
    db.commit()
    return obj