from typing import List, Optional, Tuple

from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.db.models import ItemGroup, ItemGroupRel


# ==================== 商品组 ====================

def create_item_group(db: Session, data: dict) -> ItemGroup:
    """新增商品组。"""
    obj = ItemGroup(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def list_item_groups(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
    status: Optional[int] = None,
) -> Tuple[List[ItemGroup], int]:
    """分页查询商品组列表。"""
    q = db.query(ItemGroup).filter(ItemGroup.is_deleted == 0)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            or_(
                ItemGroup.group_name.ilike(like),
                ItemGroup.group_code.ilike(like),
            )
        )
    if status is not None:
        q = q.filter(ItemGroup.status == status)
    total = q.count()
    rows = q.order_by(ItemGroup.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def get_item_group(db: Session, group_id: int) -> Optional[ItemGroup]:
    """根据 ID 获取商品组。"""
    return (
        db.query(ItemGroup)
        .filter(ItemGroup.id == group_id, ItemGroup.is_deleted == 0)
        .first()
    )


def update_item_group(db: Session, group_id: int, data: dict) -> Optional[ItemGroup]:
    """更新商品组。"""
    group = get_item_group(db, group_id)
    if not group:
        return None
    for k, v in data.items():
        setattr(group, k, v)
    db.commit()
    db.refresh(group)
    return group


def delete_item_group(db: Session, group_id: int) -> bool:
    """软删除商品组。"""
    group = get_item_group(db, group_id)
    if not group:
        return False
    group.is_deleted = 1
    db.commit()
    return True


# ==================== 商品组关联 ====================

def add_item_to_group(db: Session, data: dict) -> ItemGroupRel:
    """将商品加入组。"""
    obj = ItemGroupRel(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def list_group_items(
    db: Session,
    group_id: int,
) -> List[ItemGroupRel]:
    """获取组内所有商品关联。"""
    return (
        db.query(ItemGroupRel)
        .filter(ItemGroupRel.group_id == group_id)
        .order_by(ItemGroupRel.id.asc())
        .all()
    )


def remove_item_from_group(db: Session, group_id: int, item_id: int) -> bool:
    """将商品移出组。"""
    rel = (
        db.query(ItemGroupRel)
        .filter(ItemGroupRel.group_id == group_id, ItemGroupRel.item_id == item_id)
        .first()
    )
    if not rel:
        return False
    db.delete(rel)
    db.commit()
    return True


def set_base_item(db: Session, group_id: int, item_id: int) -> bool:
    """设置组内基准商品。"""
    # 先取消所有基准
    db.query(ItemGroupRel).filter(ItemGroupRel.group_id == group_id).update(
        {ItemGroupRel.is_base: 0}, synchronize_session=False
    )
    # 设置新基准
    rel = (
        db.query(ItemGroupRel)
        .filter(ItemGroupRel.group_id == group_id, ItemGroupRel.item_id == item_id)
        .first()
    )
    if not rel:
        return False
    rel.is_base = 1
    db.commit()
    return True
