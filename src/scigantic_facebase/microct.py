"""Zip-of-TIFF micro-CT stacks, read in place.

Many FaceBase micro-CT datasets ship each scan as one .zip holding a stack of
reconstructed TIFF slices plus a SkyScan scan log. A zip keeps a directory at
its end, so a single slice can be read with one HTTP range request; a 50 MB
scan is never downloaded just to look at one cross-section.
"""

from __future__ import annotations

import io
import re
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from . import catalog
from .models import Dataset, File
from .remote import RangeFile, open_remote

_TIF = re.compile(r"\.tiff?$", re.IGNORECASE)


class Stack:
    """A remote zip of TIFF slices. Create with open_stack()."""

    def __init__(self, source: RangeFile, name: str = "") -> None:
        self.name = name
        self._source = source
        self._zip = zipfile.ZipFile(source)
        self._lock = threading.Lock()
        self.slice_names: list[str] = sorted(
            i.filename for i in self._zip.infolist() if _TIF.search(i.filename) and not i.is_dir()
        )
        self._logs = [i.filename for i in self._zip.infolist() if i.filename.lower().endswith(".log")]

    def __len__(self) -> int:
        return len(self.slice_names)

    @property
    def requests(self) -> int:
        """HTTP requests made so far, to see how little was fetched."""
        return self._source.requests

    @property
    def bytes_fetched(self) -> int:
        return self._source.bytes_fetched

    def read_slice(self, index: int) -> npt.NDArray[Any]:
        """One slice as a 2-D array (decoded with tifffile)."""
        import tifffile

        with self._lock:
            raw = self._zip.read(self.slice_names[index])
        return np.asarray(tifffile.imread(io.BytesIO(raw)))

    def volume(self, *, step: int = 1, start: int = 0, stop: int | None = None, workers: int = 4) -> npt.NDArray[Any]:
        """Slices start:stop:step stacked into a (z, y, x) array. Slices are
        read in parallel; each worker reuses the same cached connection."""
        idx = list(range(start, len(self) if stop is None else stop, step))
        if not idx:
            raise ValueError("no slices selected")
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            slices = list(pool.map(self.read_slice, idx))
        return np.stack(slices)

    def scan_log(self) -> dict[str, dict[str, str]]:
        """The SkyScan scan log as {section: {key: value}}; empty when the
        zip has none."""
        if not self._logs:
            return {}
        with self._lock:
            text = self._zip.read(self._logs[0]).decode("latin-1")
        out: dict[str, dict[str, str]] = {}
        section = ""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                out.setdefault(section, {})
            elif "=" in line and section:
                key, _, val = line.partition("=")
                out[section][key.strip()] = val.strip()
        return out

    @property
    def voxel_size_um(self) -> float | None:
        """Isotropic voxel edge in micrometres, from the scan log."""
        log = self.scan_log()
        for section in ("Reconstruction", "Acquisition"):
            for key in ("Pixel Size (um)", "Image Pixel Size (um)", "Scaled Image Pixel Size (um)"):
                val = log.get(section, {}).get(key)
                if val:
                    try:
                        return float(val)
                    except ValueError:
                        continue
        return None

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> Stack:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def open_stack(file: File) -> Stack:
    """Open a zip-of-TIFFs file from FaceBase without downloading it."""
    return Stack(open_remote(file), name=file.filename)


@dataclass(frozen=True)
class ThyroidScan:
    """One scan in the zebrafish thyroid-hormone craniofacial atlas."""

    dataset: Dataset
    condition: str  # hypothyroid, euthyroid or hyperthyroid
    standard_length_mm: float


_TITLE = re.compile(r"microCT scan of ([\d.]+) mm (hypothyroid|euthyroid|hyperthyroid) Danio rerio head", re.IGNORECASE)


def parse_thyroid_title(title: str) -> tuple[float, str] | None:
    """(standard length in mm, condition) from an atlas dataset title."""
    m = _TITLE.search(title)
    return (float(m.group(1)), m.group(2).lower()) if m else None


def thyroid_atlas() -> list[ThyroidScan]:
    """The zebrafish head micro-CT series: fish from 12 to 25 mm standard
    length raised hypothyroid, euthyroid (normal) or hyperthyroid, one dataset
    per fish. Sorted by condition then length."""
    scans = []
    for ds in catalog.search("microCT Danio rerio head thyroid", limit=300):
        parsed = parse_thyroid_title(ds.title)
        if parsed:
            scans.append(ThyroidScan(ds, parsed[1], parsed[0]))
    return sorted(scans, key=lambda s: (s.condition, s.standard_length_mm, s.dataset.rid))
