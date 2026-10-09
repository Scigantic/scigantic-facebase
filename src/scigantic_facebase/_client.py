"""Shared HTTP plumbing for FaceBase: one lazily-built requests.Session,
retry with backoff on transient failures, and the two FaceBase endpoints this
package talks to.

FaceBase publishes no rate limit. Its metadata (ERMrest) and open-access file
store (Hatrac) answer anonymous requests, so there is no key or login here.
Retries cover 429/5xx and connection errors only. A 404 is a real answer and
raises FacebaseNotFoundError at once. A 401 or 403 means the data is behind
FaceBase's data access request process and raises FacebaseAccessError.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import requests

from ._version import __version__

SITE = "https://www.facebase.org"
ERMREST = f"{SITE}/ermrest/catalog/1"

_USER_AGENT = f"scigantic-facebase/{__version__} (+https://scigantic.com; mailto:support@scigantic.com)"

_MAX_RETRIES = 4
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}

_session: requests.Session | None = None
_session_lock = threading.Lock()


class FacebaseError(Exception):
    """An HTTP error after retries were exhausted, or a malformed response."""


class FacebaseNotFoundError(FacebaseError):
    """A dataset, file or path that does not exist (HTTP 404)."""


class FacebaseAccessError(FacebaseError):
    """The data needs authentication (HTTP 401 or 403). FaceBase holds
    protected human-subjects data behind a data access request, and this
    package only reads the open-access part."""


def get_session() -> requests.Session:
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                _session = requests.Session()
                _session.headers["User-Agent"] = _USER_AGENT
    return _session


def send(
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    stream: bool = False,
    timeout: float = 60.0,
) -> requests.Response:
    """Issue one request with retry on 429/5xx and connection errors."""
    session = get_session()
    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = session.request(
                method, url, params=params, headers=headers, stream=stream, timeout=timeout
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt == _MAX_RETRIES:
                break
            time.sleep(1.5 * (2**attempt))
            continue
        if resp.status_code == 404:
            resp.close()
            raise FacebaseNotFoundError(f"404 for {resp.url}")
        if resp.status_code in (401, 403):
            resp.close()
            raise FacebaseAccessError(
                f"HTTP {resp.status_code} for {resp.url}: this data is not open access. "
                "FaceBase releases protected human-subjects data only through a data access request."
            )
        if resp.status_code in _RETRY_STATUS_CODES and attempt < _MAX_RETRIES:
            resp.close()
            time.sleep(1.5 * (2**attempt))
            continue
        if resp.status_code >= 400:
            body = resp.text[:300]
            resp.close()
            raise FacebaseError(f"HTTP {resp.status_code} for {resp.url}: {body}")
        return resp
    raise FacebaseError(f"request to {url} failed after {_MAX_RETRIES + 1} attempts: {last_error}")


def ermrest(path: str) -> Any:
    """GET an ERMrest path (everything after /catalog/1) and return parsed JSON."""
    resp = send("GET", f"{ERMREST}/{path.lstrip('/')}")
    try:
        return resp.json()
    except ValueError as exc:
        raise FacebaseError(f"non-JSON response from {resp.url}") from exc
