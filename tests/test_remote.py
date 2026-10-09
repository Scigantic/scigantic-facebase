"""RangeFile and download against a local Range-capable server (offline)."""

from __future__ import annotations

import hashlib
import http.server
import io
import threading
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from scigantic_facebase import File, RangeFile, download
from scigantic_facebase.microct import Stack

PAYLOAD = bytes(range(256)) * 20000  # ~5 MB


class _Handler(http.server.BaseHTTPRequestHandler):
    body = PAYLOAD
    hits: list[str] = []

    def log_message(self, *a: object) -> None:  # silence
        pass

    def do_GET(self) -> None:
        rng = self.headers.get("Range")
        data = self.body
        if rng:
            a, _, b = rng.removeprefix("bytes=").partition("-")
            lo, hi = int(a), min(int(b), len(data) - 1)
            self.hits.append(rng)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {lo}-{hi}/{len(data)}")
            chunk = data[lo : hi + 1]
        else:
            self.send_response(200)
            chunk = data
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        self.wfile.write(chunk)


@pytest.fixture()
def server() -> Iterator[str]:
    _Handler.hits = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/f.bin"
    srv.shutdown()


def test_random_access_reads_only_needed_blocks(server: str) -> None:
    f = RangeFile(server)
    assert len(f) == len(PAYLOAD)
    f.seek(3_000_000)
    assert f.read(10) == PAYLOAD[3_000_000:3_000_010]
    assert f.requests == 1  # the size probe is not counted; one block read here
    assert f.bytes_fetched <= 1 << 20


def test_read_past_end_and_seek_end(server: str) -> None:
    f = RangeFile(server)
    f.seek(-5, 2)
    assert f.read() == PAYLOAD[-5:]
    assert f.read(10) == b""


def test_download_verifies_md5(server: str, tmp_path: Path) -> None:
    good = File("r", "d", "f.bin", len(PAYLOAD), hashlib.md5(PAYLOAD).hexdigest(), server)
    out = download(good, tmp_path)
    assert out.read_bytes() == PAYLOAD
    bad = File("r", "d", "g.bin", len(PAYLOAD), "0" * 32, server)
    with pytest.raises(Exception, match="MD5"):
        download(bad, tmp_path)
    assert not (tmp_path / "g.bin").exists()


def test_stack_reads_one_slice_from_a_remote_zip(tmp_path: Path) -> None:
    import numpy as np
    import tifffile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for i in range(5):
            t = io.BytesIO()
            tifffile.imwrite(t, np.full((8, 9), i, dtype=np.uint16))
            z.writestr(f"scan/s{i:04d}.tif", t.getvalue())
        z.writestr("scan/scan.log", "[Acquisition]\nImage Pixel Size (um)=12.5\n")
    _Handler.body = buf.getvalue()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        stack = Stack(RangeFile(f"http://127.0.0.1:{srv.server_port}/z.zip"))
        assert len(stack) == 5
        assert int(stack.read_slice(3).mean()) == 3
        assert stack.volume(step=2).shape == (3, 8, 9)
        assert stack.voxel_size_um == 12.5
    finally:
        srv.shutdown()
        _Handler.body = PAYLOAD
