"""Data models owned by the list_builder service."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EmployerEntry(BaseModel):
    """One company read from the text list."""

    name: str
    bucket: str
    starred: bool = False
    suggested: bool = False  # "Suggested star" column (e.g. a mentor's pick)
    careers_url: str | None = None
    line: int = Field(..., description="Line number in the text file, for messages")


class ListSettings(BaseModel):
    """Optional settings that personalise the workbook."""

    university: str | None = None  # names the alumni column, e.g. "Leeds"
    cv_versions: list[str] = []  # choices for the "CV version" dropdown


class ParsedList(BaseModel):
    """The employers read from a text list, plus anything worth telling the user."""

    employers: list[EmployerEntry]
    settings: ListSettings = Field(default_factory=ListSettings)
    warnings: list[str] = Field(default_factory=list)

    @property
    def buckets(self) -> list[str]:
        """Buckets in order of first appearance."""
        return list(dict.fromkeys(e.bucket for e in self.employers))
