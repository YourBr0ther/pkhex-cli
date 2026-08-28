"""Species id conversion between internal and National Dex numbering.

Gen1 uses an unrelated internal ordering. Gen3 and Gen9 mostly match the Dex but
diverge past a point, so PKHeX stores the difference as a delta table indexed
from the first misaligned id.
"""

from __future__ import annotations

import json
from functools import lru_cache

from ..data import DATA_DIR


@lru_cache(maxsize=1)
def _tables() -> dict:
    return json.loads((DATA_DIR / "species_convert.json").read_text())


def to_national1(raw: int) -> int:
    table = _tables()["1_to_national"]
    return table[raw] if 0 <= raw < len(table) else 0


def to_internal1(species: int) -> int:
    table = _tables()["1_to_internal"]
    return table[species] if 0 <= species < len(table) else 0


def _shifted(raw: int, table: list[int], first: int, out_of_range: int | None) -> int:
    shift = raw - first
    if not (0 <= shift < len(table)):
        return raw if out_of_range is None else out_of_range
    return raw + table[shift]


def to_internal3(species: int) -> int:
    t = _tables()
    return _shifted(species, t["3_to_internal"], t["first_unaligned"]["national3"], None)


def to_national3(raw: int) -> int:
    t = _tables()
    first_national = t["first_unaligned"]["national3"]
    if raw < first_national:
        return raw
    return _shifted(raw, t["3_to_national"], t["first_unaligned"]["internal3"], 0)


def to_internal9(species: int) -> int:
    t = _tables()
    return _shifted(species, t["9_to_internal"], t["first_unaligned"]["national9"], None)


def to_national9(raw: int) -> int:
    t = _tables()
    return _shifted(raw, t["9_to_national"], t["first_unaligned"]["internal9"], None)
