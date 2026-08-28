"""Save file reading, writing, and JSON conversion."""

from __future__ import annotations

from .base import SaveFile
from .detect import KNOWN_SIZES, SaveFormatError, from_bytes, read_file

__all__ = ["KNOWN_SIZES", "SaveFile", "SaveFormatError", "from_bytes", "read_file"]
