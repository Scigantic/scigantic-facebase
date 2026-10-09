"""Read FaceBase files over HTTP without downloading them first.

`RangeFile` is a seekable, read-only file object backed by HTTP Range
requests with a small block cache. Hand it to zipfile.ZipFile or tifffile and
only the bytes they actually touch cross the network. For a 50 MB zip of
600 TIFF slices, opening the archive reads the central directory (one small
request) and each slice costs one request of its own size.
"""

from __future__ import annotations

import hashlib
import io
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from ._client import FacebaseError, send
from .models import File

_BLOCK = 1 << 20  # 1 MiB
_CACHE_BLOCKS = 32


class RangeFile(io.RawIOBase):
    """Seekable read-only view of one remote file."""

    def __init__(self, url: str, size: int | None = None) -> None:
        super().__init__()
        self.url = url
        self._pos = 0
        self._lock = threading.Lock()
        self._cache: OrderedDict[int, bytes] = OrderedDict()
        self.requests = 0
        self.bytes_fetched = 0
        self._size = size if size is not None else self._probe_size()

    def _probe_size(self) -> int:
        resp = send("GET", self.url, headers={"Range": "bytes=0-0"}, stream=True)
        try:
            cr = resp.headers.get("Content-Range", "")
            if "/" in cr and cr.rsplit("/", 1)[1].isdigit():
                return int(cr.rsplit("/", 1)[1])
            length = resp.headers.get("Content-Length")
            if resp.status_code == 200 and length and length.isdigit():
                return int(length)
        finally:
            resp.close()
        raise FacebaseError(f"cannot determine size of {self.url}")

    def __len__(self) -> int:
        return self._size

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if whence == os.SEEK_SET:
            self._pos = offset
        elif whence == os.SEEK_CUR:
            self._pos += offset
        elif whence == os.SEEK_END:
            self._pos = self._size + offset
        else:
            raise ValueError(f"invalid whence: {whence}")
        self._pos = max(self._pos, 0)
        return self._pos

    def _block(self, index: int) -> bytes:
        with self._lock:
            hit = self._cache.get(index)
            if hit is not None:
                self._cache.move_to_end(index)
                return hit
        start = index * _BLOCK
        end = min(start + _BLOCK, self._size) - 1
        resp = send("GET", self.url, headers={"Range": f"bytes={start}-{end}"})
        data = resp.content
        if resp.status_code == 200 and len(data) != end - start + 1:
            raise FacebaseError(f"{self.url} ignored the Range header")
        with self._lock:
            self.requests += 1
            self.bytes_fetched += len(data)
            self._cache[index] = data
            while len(self._cache) > _CACHE_BLOCKS:
                self._cache.popitem(last=False)
        return data

    def read(self, size: int = -1) -> bytes:
        if self._pos >= self._size:
            return b""
        if size is None or size < 0:
            size = self._size - self._pos
        stop = min(self._pos + size, self._size)
        # A request larger than the cache would thrash it; fetch it in one go.
        if stop - self._pos > _BLOCK * 4:
            resp = send("GET", self.url, headers={"Range": f"bytes={self._pos}-{stop - 1}"})
            data = resp.content
            with self._lock:
                self.requests += 1
                self.bytes_fetched += len(data)
            self._pos += len(data)
            return data
        out = bytearray()
        pos = self._pos
        while pos < stop:
            block = self._block(pos // _BLOCK)
            off = pos % _BLOCK
            take = block[off : off + (stop - pos)]
            if not take:
                break
            out += take
            pos += len(take)
        self._pos = pos
        return bytes(out)

    def readinto(self, b: Any) -> int:
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)


def open_remote(file: File) -> RangeFile:
    """Open a FaceBase file as a seekable file object (nothing downloaded)."""
    return RangeFile(file.url, size=file.size or None)


def download(file: File, dest: str | os.PathLike[str], *, verify: bool = True, chunk: int = 1 << 20) -> Path:
    """Download a file to `dest` (a directory or a file path) and return the
    path. Checks size and MD5 against FaceBase's record unless verify=False.
    An existing file with the right size and MD5 is kept, so reruns are free."""
    target = Path(dest)
    if target.is_dir():
        target = target / file.filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size == file.size and (not verify or not file.md5 or _md5(target) == file.md5):
        return target
    tmp = target.with_suffix(target.suffix + ".part")
    md5 = hashlib.md5()
    resp = send("GET", file.url, stream=True, timeout=120.0)
    try:
        with open(tmp, "wb") as fh:
            for part in resp.iter_content(chunk):
                fh.write(part)
                md5.update(part)
    finally:
        resp.close()
    if file.size and tmp.stat().st_size != file.size:
        tmp.unlink(missing_ok=True)
        raise FacebaseError(f"{file.filename}: got {tmp.stat().st_size if tmp.exists() else 0} bytes, expected {file.size}")
    if verify and file.md5 and md5.hexdigest() != file.md5:
        tmp.unlink(missing_ok=True)
        raise FacebaseError(f"{file.filename}: MD5 mismatch")
    tmp.replace(target)
    return target


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for part in iter(lambda: fh.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()
