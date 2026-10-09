"""Live checks against facebase.org. Skipped with `-m 'not live'`."""

from __future__ import annotations

import pytest

import scigantic_facebase as fb

pytestmark = pytest.mark.live


def test_search_and_get() -> None:
    hits = fb.search("zebrafish thyroid microCT", limit=5)
    assert hits and all(h.open_access for h in hits)
    assert fb.count("zebrafish thyroid microCT") >= 80
    assert fb.get("2E-YW20").doi == "10.25550/2E-YW20"


def test_citation_has_doi_and_year() -> None:
    c = fb.cite("2E-YW20")
    assert "https://doi.org/10.25550/2E-YW20" in c and "(2024)" in c and "FaceBase Consortium" in c


def test_stack_read_in_place() -> None:
    f = fb.files("2E-YW20")[0]
    with fb.microct.open_stack(f) as stack:
        assert len(stack) > 500
        assert stack.voxel_size_um and 10 < stack.voxel_size_um < 11
        img = stack.read_slice(len(stack) // 2)
        assert img.ndim == 2
        assert stack.bytes_fetched < f.size // 4


def test_atlas_is_three_conditions() -> None:
    atlas = fb.microct.thyroid_atlas()
    assert {s.condition for s in atlas} == {"hypothyroid", "euthyroid", "hyperthyroid"}
    assert len(atlas) >= 80


def test_protected_dataset_files_raise() -> None:
    ds = next(d for d in fb.search(include_protected=True, limit=400) if d.protected)
    files = fb.files(ds)
    assert files, "protected dataset lists its files (metadata is public)"
    with pytest.raises(fb.FacebaseAccessError):
        fb.open_remote(files[0]).read(1)
