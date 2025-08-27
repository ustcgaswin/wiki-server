import enum
from uuid import uuid4, UUID
from typing import Optional
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class WikiStatus(str, enum.Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    GENERATED = "generated"
    FAILED = "failed"


class Project(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = Field(default=None)  # <-- Add this line
    github_url: Optional[str] = Field(default=None)
    wiki_status: WikiStatus = Field(default=WikiStatus.PENDING)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    analysis_start_time: Optional[datetime] = Field(default=None)
    analysis_end_time: Optional[datetime] = Field(default=None)
