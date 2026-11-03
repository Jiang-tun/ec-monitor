from typing import List, Optional

from pydantic import BaseModel, Field


# ==================== 商品组 Schema =====

class ItemGroupBase(BaseModel):
    group_name: str = Field(..., min_length=1, max_length=128)
    group_code: Optional[str] = Field(default=None, max_length=64)
    base_item_id: Optional[int] = Field(default=None, gt=0)
    owner: Optional[str] = Field(default=None, max_length=64)
    status: int = Field(default=1, ge=0, le=1)


class ItemGroupCreate(ItemGroupBase):
    pass


class ItemGroupUpdate(BaseModel):
    group_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    group_code: Optional[str] = Field(default=None, max_length=64)
    base_item_id: Optional[int] = Field(default=None, gt=0)
    owner: Optional[str] = Field(default=None, max_length=64)
    status: Optional[int] = Field(default=None, ge=0, le=1)


class ItemGroupOut(ItemGroupBase):
    id: int
    is_deleted: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ==================== 商品组关联 Schema =====

class ItemGroupRelBase(BaseModel):
    group_id: int = Field(..., gt=0)
    item_id: int = Field(..., gt=0)
    platform_id: int = Field(..., gt=0)
    is_base: int = Field(default=0, ge=0, le=1)


class ItemGroupRelCreate(ItemGroupRelBase):
    pass


class ItemGroupRelOut(ItemGroupRelBase):
    id: int
    created_at: str

    model_config = {"from_attributes": True}


# ==================== 商品组比价 Schema =====

class ItemCompareOut(BaseModel):
    group_id: int
    group_name: str
    items: List[dict]

    model_config = {"from_attributes": True}
