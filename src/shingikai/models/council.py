from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class SourceUrls(BaseModel):
    portal: str
    meetings: str
    meetings_archives: list[str] = Field(default_factory=list)


class Council(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    council_id: str = Field(alias="id")
    title: str
    parent: str = Field(validation_alias=AliasChoices("parent", "organization"))
    source_urls: SourceUrls

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Council":
        return cls.model_validate(data)
