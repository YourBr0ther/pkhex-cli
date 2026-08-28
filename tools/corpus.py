"""Which files in the save corpus count as saves.

Shared by tests/conftest.py and tools/audit_fields.py so the two never disagree
about what "the corpus" contains. They did once: the audit read 18,570 entities
where the tests read 18,513, because only the tests skipped the backup copies.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Files the archives ship alongside a save that are not saves themselves.
#: "backup" is a second copy of the same playthrough, so counting it would
#: double that save's contribution without adding coverage.
NON_SAVE_NAMES = frozenset({"main2", "poke_trade", "backup"})

NON_SAVE_SUFFIXES = frozenset({
    ".zip", ".json", ".txt", ".md", ".gitinclude",
    ".gci",   # GameCube memory-card container, not a bare save
})

#: Nothing smaller than this is a save; the smallest supported is 0x8000.
MIN_SAVE_SIZE = 0x4000

#: Where fetch_test_saves.sh puts the corpus, overridable for a different path.
DEFAULT_ROOT = "test-saves"
ROOT_ENV_VAR = "PKHEXPY_SAVES"


def corpus_root() -> Path:
    return Path(os.environ.get(ROOT_ENV_VAR, DEFAULT_ROOT))


def is_candidate(path: Path) -> bool:
    return (
        path.is_file()
        and ".git" not in path.parts
        and path.name not in NON_SAVE_NAMES
        and path.suffix.lower() not in NON_SAVE_SUFFIXES
        and path.stat().st_size >= MIN_SAVE_SIZE
    )


def find_saves(root: Path | None = None) -> list[Path]:
    """Every file under ``root`` that could be a save, in a stable order."""
    root = corpus_root() if root is None else root
    if not root.is_dir():
        return []
    return [p for p in sorted(root.rglob("*")) if is_candidate(p)]
