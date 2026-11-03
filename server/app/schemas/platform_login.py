from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class PlatformLoginCreate(BaseModel):
    platform_id: int = Field(..., gt=0)
    phone: str = Field(..., min_length=11, max_length=11, pattern=r"^1[3-9]\d{9}$")


class PlatformLoginSubmitCode(BaseModel):
    code: str = Field(..., min_length=4, max_length=8)


class PlatformLoginOut(BaseModel):
    id: int
    platform_id: int
    platform_code: str
    phone: str
    status: str
    error: Optional[str] = None
    expires_at: Optional[datetime] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlatformLoginResultIn(BaseModel):
    login_id: int
    status: str = Field(..., pattern="^(success|failed|expired)$")
    cookies: Optional[Any] = None
    storage_state: Optional[dict] = None
    error: Optional[str] = None
