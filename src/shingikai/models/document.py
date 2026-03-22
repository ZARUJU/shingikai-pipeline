from __future__ import annotations

from pydantic import BaseModel, Field

from shingikai.models.meeting import MeetingLink


class DocumentBody(BaseModel):
    status: str
    markdown_url: str | None = None
    markdown: str | None = None


class CouncilDocument(BaseModel):
    id: str
    council_id: str
    title: str
    published_on: str
    document_type: str
    source_url: str
    links: list[MeetingLink] = Field(default_factory=list)
    body: DocumentBody
