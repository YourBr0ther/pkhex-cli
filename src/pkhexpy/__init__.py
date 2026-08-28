"""Read Pokemon save files and entity files, convert them to JSON, and back.

A Python port of the file-format layer of PKHeX (https://github.com/kwsch/PKHeX).
"""

from __future__ import annotations

__version__ = "0.1.0"

from .pkm import io as entity_io
from .pkm import serialize as entity_json

__all__ = ["__version__", "entity_io", "entity_json"]
