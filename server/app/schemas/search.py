from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SearchTaskCreate(BaseModel):
    platform_id: int = Field(..., gt=0)
    keyword: str = Field(..., min_length=1, max_length=128)
    limit_count: int = Field(default=20, ge=1, le=50, comment="取列表前N条")


class SearchTaskOut(BaseModel):
    id: int
    task_id: str
    platform_id: int
    platform_code: str
    keyword: str
    limit_count: int
    status: str
    total_count: int
    new_count: int
    dup_count: int
    added_count: int = 0
    error: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SearchResultIn(BaseModel):
    task_id: str = Field(..., max_length=64)
    items: List[dict] = Field(default_factory=list, max_length=100)


class SearchResultOut(BaseModel):
    task_id: str
    total: int = 0
    new: int = 0
    dup: int = 0


class SearchCandidateOut(BaseModel):
    id: int
    task_id: str
    platform_id: int
    keyword: str
    platform_item_id: str
    title: Optional[str] = None
    url: Optional[str] = None
    image: Optional[str] = None
    price: Optional[float] = None
    original_price: Optional[float] = None
    status: str
    monitor_item_id: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SearchConfirmIn(BaseModel):
    candidate_ids: List[int] = Field(default_factory=list)
    select_all: bool = False


class SearchConfirmOut(BaseModel):
    task_id: str
    added: int = 0
    dup: int = 0
    skipped: int = 0