from __future__ import annotations

from pydantic import BaseModel, Field


class MeetingLink(BaseModel):
    title: str
    url: str


class Meeting(BaseModel):
    id: str
    council_id: str
    round_label: int | None
    held_on: str
    agenda: list[str] = Field(default_factory=list)
    source_url: str
    minutes_links: list[MeetingLink] = Field(default_factory=list)
    materials_links: list[MeetingLink] = Field(default_factory=list)
    announcement_links: list[MeetingLink] = Field(default_factory=list)
