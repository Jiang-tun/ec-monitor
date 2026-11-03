from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ==================== 质量问题 Schema =====

class QualityIssueBase(BaseModel):
    item_id: int = Field(..., gt=0)
    sku_id: Optional[str] = Field(default=None, max_length=64)
    snapshot_id: Optional[int] = Field(default=None, gt=0)
    issue_type: str = Field(..., max_length=32)
    severity: str = Field(default="warn", max_length=16)
    detail: dict = Field(default_factory=dict)
    summary: Optional[str] = Field(default=None, max_length=512)
    review_status: str = Field(default="pending", max_length=16)
    review_note: Optional[str] = Field(default=None, max_length=512)
    occurred_at: Optional[datetime] = None


class QualityIssueCreate(QualityIssueBase):
    pass


class QualityIssueUpdate(BaseModel):
    review_status: Optional[str] = Field(default=None, max_length=16)
    review_note: Optional[str] = Field(default=None, max_length=512)


class QualityIssueOut(QualityIssueBase):
    id: int
    review_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class QualityIssueReview(BaseModel):
    review_status: str = Field(..., pattern="^(confirmed|ignored|fixed)$")
    review_note: Optional[str] = Field(default=None, max_length=512)


class QualityIssuePage(BaseModel):
    items: List[QualityIssueOut]
    total: int
    page: int
    page_size: int

    model_config = {"from_attributes": True}
