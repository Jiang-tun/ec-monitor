from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ==================== 死信 Schema =====

class DeadLetterBase(BaseModel):
    item_id: int = Field(..., gt=0)
    sku_id: Optional[str] = Field(default=None, max_length=64)
    fail_stage: str = Field(..., max_length=16)
    fail_reason: str = Field(..., max_length=512)
    raw_error: Optional[str] = None
    fail_strategy: Optional[str] = Field(default=None, max_length=16)
    max_retry: int = Field(default=5, ge=0)
    task_id: Optional[str] = Field(default=None, max_length=64)


class DeadLetterCreate(DeadLetterBase):
    pass


class DeadLetterUpdate(BaseModel):
    status: Optional[str] = Field(default=None, max_length=16)
    resolved_by: Optional[str] = Field(default=None, max_length=64)


class DeadLetterOut(DeadLetterBase):
    id: int
    retry_count: int
    status: str
    first_fail_at: datetime
    last_fail_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DeadLetterRetry(BaseModel):
    dead_ids: List[int]


class DeadLetterPage(BaseModel):
    items: List[DeadLetterOut]
    total: int
    page: int
    page_size: int

    model_config = {"from_attributes": True}
