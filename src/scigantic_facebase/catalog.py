"""Search FaceBase datasets and list their files through the open ERMrest
metadata API. Everything here is a metadata call; no file bytes move."""

from __future__ import annotations

import re
from typing import Any
from functools import lru_cache
from urllib.parse import quote

from ._client import SITE, FacebaseNotFoundError, ermrest
from .models import Dataset, File, Project

_OPEN = "released=true&protected_human_subjects=false"


def _q(value: str) -> str:
    return quote(value, safe="")


# FaceBase records name species inconsistently ("zebrafish" in some titles,
# "Danio rerio" in most). A search word that is a common name also matches
# the Latin name, and the other way round.
_SYNONYMS = {
    "zebrafish": ("zebrafish", "danio rerio"),
    "danio": ("zebrafish", "danio rerio"),
    "mouse": ("mouse", "mice", "mus musculus"),
    "mice": ("mouse", "mice", "mus musculus"),
    "human": ("human", "homo sapiens"),
    "chick": ("chick", "gallus gallus"),
    "microct": ("microct", "micro-ct", "micro ct", "\u00b5ct"),
}


def _filter(text: str | None, include_protected: bool) -> str:
    parts = [_OPEN if not include_protected else "released=true"]
    for word in (text or "").split():
        options = _SYNONYMS.get(word.lower(), (word,))
        pattern = "|".join(re.escape(o) for o in options)
        parts.append(f"*::ciregexp::{_q(pattern)}")
    return "&".join(parts)


def _str(row: dict[str, Any], key: str) -> str | None:
    val = row.get(key)
    return val if isinstance(val, str) else None


def _dataset(row: dict[str, Any]) -> Dataset:
    project_id = row.get("project")
    return Dataset(
        rid=str(row["RID"]),
        accession=_str(row, "accession"),
        title=str(row.get("title") or ""),
        description=str(row.get("description") or ""),
        release_date=_str(row, "release_date"),
        doi=_str(row, "DOI"),
        project_id=project_id if isinstance(project_id, int) else None,
        protected=bool(row.get("protected_human_subjects")),
        internal_id=int(row["id"]),
    )


def search(text: str | None = None, *, limit: int = 50, include_protected: bool = False) -> list[Dataset]:
    """Find datasets, newest first. Every word in `text` must appear somewhere
    in the dataset's title, description or keywords (case-insensitive).
    Protected human-subjects datasets are left out unless include_protected=True;
    their metadata is public but their files need a data access request."""
    path = f"entity/isa:dataset/{_filter(text, include_protected)}@sort(release_date::desc::,RID)"
    rows = ermrest(f"{path}?limit={int(limit)}")
    return [_dataset(r) for r in rows]


def count(text: str | None = None, *, include_protected: bool = False) -> int:
    """How many datasets match `text` (same rules as search)."""
    rows = ermrest(f"aggregate/isa:dataset/{_filter(text, include_protected)}/n:=cnt(RID)")
    return int(rows[0]["n"])


def get(rid: str) -> Dataset:
    """One dataset by FaceBase record id (e.g. '2E-YW20')."""
    rows = ermrest(f"entity/isa:dataset/RID={_q(rid)}")
    if not rows:
        raise FacebaseNotFoundError(f"no FaceBase dataset {rid!r}")
    return _dataset(rows[0])


@lru_cache(maxsize=1)
def _formats() -> dict[str, str]:
    out: dict[str, str] = {}
    for r in ermrest("entity/vocab:file_format?limit=500"):
        key = r.get("id") or r.get("ID")
        name = r.get("name") or r.get("Name")
        if key and name:
            out[str(key)] = str(name)
    return out


def files(dataset: Dataset | str) -> list[File]:
    """Every file in a dataset, with size, MD5 and an absolute download URL."""
    ds = get(dataset) if isinstance(dataset, str) else dataset
    rows = ermrest(f"entity/isa:file/dataset={_q(ds.rid)}@sort(filename)?limit=20000")
    fmt = _formats()
    return [
        File(
            rid=str(r["RID"]),
            dataset_rid=ds.rid,
            filename=str(r["filename"]),
            size=int(r.get("byte_count") or 0),
            md5=_str(r, "md5"),
            url=SITE + str(r["url"]),
            format=fmt.get(str(r["file_format"])) if r.get("file_format") else None,
            relative_path=_str(r, "relative_path"),
            description=_str(r, "description"),
            protected=ds.protected,
        )
        for r in rows
    ]


def project(dataset: Dataset) -> Project | None:
    """The project (grant and investigator group) a dataset belongs to."""
    if dataset.project_id is None:
        return None
    rows = ermrest(f"entity/isa:project/id={dataset.project_id}")
    if not rows:
        return None
    r = rows[0]
    return Project(
        id=int(r["id"]),
        name=str(r.get("name") or ""),
        doi=_str(r, "DOI"),
        funding=_str(r, "funding"),
    )


def contributors(dataset: Dataset) -> list[str]:
    rows = ermrest(f"attribute/isa:dataset_contributor/dataset_id={dataset.internal_id}/order,full_name@sort(order)")
    return [str(r["full_name"]) for r in rows if r.get("full_name")]


def cite(dataset: Dataset | str) -> str:
    """The citation FaceBase's Terms of Use ask for: authors, title,
    FaceBase Consortium, DOI link and release year."""
    ds = get(dataset) if isinstance(dataset, str) else dataset
    authors = ", ".join(contributors(ds)) or "FaceBase Consortium contributors"
    year = (ds.release_date or "")[:4]
    link = ds.doi_url or ds.url
    return f"{authors}. {ds.title}. FaceBase Consortium {link}" + (f" ({year})." if year else ".")
