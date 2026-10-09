"""Search FaceBase and read its open-access craniofacial data from Python.

    import scigantic_facebase as fb

    hits = fb.search("zebrafish thyroid microCT")
    fb.cite(hits[0])
    stack = fb.microct.open_stack(fb.files(hits[0])[0])
    stack.read_slice(300)

Metadata comes from FaceBase's open ERMrest API and files from its open-access
file store, both anonymous. Copyright for the data stays with the contributing
investigators and FaceBase's Terms of Use apply: cite the dataset DOI
(`cite()`), and send other people to FaceBase rather than redistributing files.
"""

from . import microct
from ._client import FacebaseAccessError, FacebaseError, FacebaseNotFoundError
from ._version import __version__
from .catalog import cite, contributors, count, files, get, project, search
from .models import Dataset, File, Project
from .remote import RangeFile, download, open_remote

__all__ = [
    "Dataset",
    "FacebaseAccessError",
    "FacebaseError",
    "FacebaseNotFoundError",
    "File",
    "Project",
    "RangeFile",
    "__version__",
    "cite",
    "contributors",
    "count",
    "download",
    "files",
    "get",
    "microct",
    "open_remote",
    "project",
    "search",
]
