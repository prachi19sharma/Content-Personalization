"""Brand (workspace) payloads."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BrandRead(BaseModel):
    id: uuid.UUID
    domain: str
    label: str
    is_active: bool
    is_configured: bool
    profile_data: dict[str, Any] = Field(default_factory=dict)
    revision: int
    created_at: datetime
    updated_at: datetime


class BrandList(BaseModel):
    brands: list[BrandRead]
    #: Convenience for the switcher; also derivable from ``is_active``.
    active_id: uuid.UUID | None = None


class BrandCreate(BaseModel):
    label: str = Field(default="", max_length=160)
    domain: str | None = None
    #: Optional answers up front. Left empty the brand starts unconfigured and
    #: the UI walks the user through setup, which is the normal path.
    profile_data: dict[str, Any] = Field(default_factory=dict)


class BrandRename(BaseModel):
    label: str = Field(min_length=1, max_length=160)
