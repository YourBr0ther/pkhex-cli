"""Shared fixtures.

Most tests run against the entity and save files that ship with PKHeX's own test
suite. They are not vendored here, so the tests skip when the reference checkout
is absent; point PKHEX_REFERENCE at it to run them.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ENTITY_EXTENSIONS = {
    "pk1", "pk2", "pk3", "pk4", "pk5", "pk6", "pk7", "pk8", "pk9",
    "pb7", "pb8", "pa8", "pa9", "ck3", "xk3", "sk2", "bk4", "rk4",
}


def reference_root() -> Path | None:
    root = Path(os.environ.get("PKHEX_REFERENCE", "reference_PKHeX"))
    tests = root / "Tests"
    return tests if tests.is_dir() else None


@pytest.fixture(scope="session")
def reference() -> Path:
    root = reference_root()
    if root is None:
        pytest.skip("PKHeX reference checkout not present")
    return root


@pytest.fixture(scope="session")
def entity_files(reference: Path) -> list[Path]:
    files = sorted(p for p in reference.rglob("*")
                   if p.suffix[1:].lower() in ENTITY_EXTENSIONS)
    if not files:
        pytest.skip("no entity fixtures found")
    return files


@pytest.fixture(scope="session")
def save_file(reference: Path) -> Path:
    matches = sorted(reference.rglob("*.main"))
    if not matches:
        pytest.skip("no save fixture found")
    return matches[0]


#: Files inside the save corpus that are not saves: archive leftovers, tiny
#: sidecar files, and GameCube memory-card containers this port does not read.
NON_SAVE_NAMES = {"main2", "poke_trade", "backup"}
NON_SAVE_SUFFIXES = {".zip", ".json", ".txt", ".md", ".gci", ".gitinclude"}


@pytest.fixture(scope="session")
def real_saves() -> list[Path]:
    """Real save files, downloaded by tools/fetch_test_saves.sh.

    These are other people's game saves from three public collections, so they
    are not vendored. Set PKHEXPY_SAVES to wherever you put them.
    """
    root = Path(os.environ.get("PKHEXPY_SAVES", "test-saves"))
    if not root.is_dir():
        pytest.skip("real save corpus not present; run tools/fetch_test_saves.sh")
    files = [
        p for p in sorted(root.rglob("*"))
        if p.is_file()
        and ".git" not in p.parts
        and p.name not in NON_SAVE_NAMES
        and p.suffix.lower() not in NON_SAVE_SUFFIXES
        and p.stat().st_size > 0x4000
    ]
    if not files:
        pytest.skip("save corpus is empty")
    return files
