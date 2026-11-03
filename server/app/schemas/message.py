from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class MessageOut(BaseModel):
    id: int
    title: str
    content: Optional[str] = None
    msg_type: str
    level: str
    link: Optional[str] = None
    ref_type: Optional[str] = None
    ref_id: Optional[str] = None
    is_read: int
    read_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UnreadCountOut(BaseModel):
    count: int = 0
