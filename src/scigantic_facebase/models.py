"""Typed records for FaceBase datasets and files."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._client import SITE


@dataclass(frozen=True)
class Dataset:
    """One FaceBase dataset. `rid` is FaceBase's record id, the same string
    that appears in the dataset's landing page and DOI."""

    rid: str
    accession: str | None
    title: str
    description: str
    release_date: str | None
    doi: str | None
    project_id: int | None
    protected: bool
    internal_id: int

    @property
    def url(self) -> str:
        return f"{SITE}/id/{self.rid}"

    @property
    def doi_url(self) -> str | None:
        return f"https://doi.org/{self.doi}" if self.doi else None

    @property
    def open_access(self) -> bool:
        """False for datasets behind FaceBase's data access request."""
        return not self.protected


@dataclass(frozen=True)
class Project:
    id: int
    name: str
    doi: str | None
    funding: str | None


@dataclass(frozen=True)
class File:
    """One file in a FaceBase dataset. `url` is absolute and anonymous for
    open-access datasets; byte-range requests are honoured."""

    rid: str
    dataset_rid: str
    filename: str
    size: int
    md5: str | None
    url: str
    format: str | None = None
    relative_path: str | None = None
    description: str | None = None
    protected: bool = field(default=False, compare=False)

    @property
    def path(self) -> str:
        """Path within the dataset, folders included."""
        return f"{self.relative_path or ''}{self.filename}"
