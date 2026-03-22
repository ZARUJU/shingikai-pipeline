from __future__ import annotations

from pydantic import BaseModel, Field

from shingikai.models.meeting import MeetingLink


class CouncilRoster(BaseModel):
    id: str
    council_id: str
    as_of: str
    source_url: str
    links: list[MeetingLink] = Field(default_factory=list)
