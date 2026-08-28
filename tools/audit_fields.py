"""Check every entity field against what its value could plausibly be.

A byte-exact round trip proves nothing about interpretation: reading Ability
from the wrong offset still writes it back to that same wrong offset. This
reads every field of every Pokemon in a corpus and reports three things.

  out of range   a field whose value cannot be what the field claims to be
  always same    a field that never varies across thousands of samples, which
                 usually means the offset is wrong or the field is unused
  never set      a field that is zero everywhere, same suspicion

None of these are proof of a bug on their own. They are the list worth reading.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pkhexpy import saves
from pkhexpy.pkm import io as entity_io

#: Upper bounds a field's value must respect, keyed by PKHeX property name.
#: "max" may be a number or a callable taking the entity.
LIMITS: dict[str, object] = {
    "IV_HP": "max_iv", "IV_ATK": "max_iv", "IV_DEF": "max_iv",
    "IV_SPE": "max_iv", "IV_SPA": "max_iv", "IV_SPD": "max_iv",
    "EV_HP": "max_ev", "EV_ATK": "max_ev", "EV_DEF": "max_ev",
    "EV_SPE": "max_ev", "EV_SPA": "max_ev", "EV_SPD": "max_ev",
    "Nature": 24, "StatNature": 24, "StatAlignment": 24,
    "Gender": 2, "Form": 100, "AbilityNumber": 4,
    "CurrentFriendship": 255, "OriginalTrainerFriendship": 255,
    "HandlingTrainerFriendship": 255,
    "PokerusStrain": 15, "PokerusDays": 4,
    "MetLevel": 100, "Stat_Level": 100,
    "ContestCool": 255, "ContestBeauty": 255, "ContestCute": 255,
    "ContestSmart": 255, "ContestTough": 255, "ContestSheen": 255,
    "Move1_PPUps": 3, "Move2_PPUps": 3, "Move3_PPUps": 3, "Move4_PPUps": 3,
    "Move1_PP": 64, "Move2_PP": 64, "Move3_PP": 64, "Move4_PP": 64,
    "Ball": 64, "Language": 12,
}

#: Fields whose value indexes a name list, checked against that list's length.
NAME_LIMITS = {
    "Species": "species", "Move1": "moves", "Move2": "moves",
    "Move3": "moves", "Move4": "moves",
    "RelearnMove1": "moves", "RelearnMove2": "moves",
    "RelearnMove3": "moves", "RelearnMove4": "moves",
    "Ability": "abilities", "Version": "games",
}


def limit_for(entity, name: str):
    limit = LIMITS.get(name)
    if limit == "max_iv":
        return entity.MAX_IV
    if limit == "max_ev":
        return entity.MAX_EV
    return limit


def audit(entities) -> tuple[dict, dict]:
    """Return per-field value statistics and the range violations found."""
    from pkhexpy import data

    stats: dict[tuple[str, str], collections.Counter] = collections.defaultdict(
        collections.Counter)
    violations: dict[tuple[str, str], list] = collections.defaultdict(list)
    lengths = {kind: len(data.name_list(kind)) for kind in set(NAME_LIMITS.values())}

    for entity in entities:
        cls = type(entity).__name__
        for field in type(entity)._fields.values():
            name = field.pkhex_name
            try:
                value = field.decode(entity)
            except Exception:
                continue
            if isinstance(value, bytes | bytearray):
                value = value.hex()
            key = (cls, name)
            stats[key][value] += 1

            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            limit = limit_for(entity, name)
            if limit is not None and not 0 <= value <= limit:
                violations[key].append((value, limit, entity.species))
            kind = NAME_LIMITS.get(name)
            if kind is not None and not 0 <= value < lengths[kind]:
                violations[key].append((value, lengths[kind] - 1, entity.species))
    return stats, violations


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("roots", nargs="+", type=Path)
    ap.add_argument("--min-samples", type=int, default=50,
                    help="only flag constant fields with at least this many samples")
    args = ap.parse_args()

    entities = []
    per_format = collections.Counter()
    for root in args.roots:
        paths = sorted(p for p in root.rglob("*") if p.is_file())
        for path in paths:
            if ".git" in path.parts:
                continue
            raw = path.read_bytes()
            try:
                sav = saves.from_bytes(raw)
            except Exception:
                try:
                    entity = entity_io.from_bytes(raw, extension=path.suffix)
                except Exception:
                    continue
                entities.append(entity)
                per_format[type(entity).__name__] += 1
                continue
            for _, _, entity in sav.iter_boxes():
                entities.append(entity)
                per_format[type(entity).__name__] += 1
            for _, entity in sav.iter_party():
                entities.append(entity)
                per_format[type(entity).__name__] += 1

    print(f"read {len(entities)} entities: {dict(per_format)}\n")
    stats, violations = audit(entities)

    print(f"=== range violations ({len(violations)} fields) ===")
    for (cls, name), hits in sorted(violations.items()):
        worst = max(h[0] for h in hits)
        print(f"  {cls}.{name}: {len(hits)} bad, max seen {worst} (limit {hits[0][1]})")
    if not violations:
        print("  none")

    print(f"\n=== constant fields with >= {args.min_samples} samples ===")
    constant = []
    for (cls, name), counter in sorted(stats.items()):
        total = sum(counter.values())
        if total >= args.min_samples and len(counter) == 1:
            constant.append((cls, name, next(iter(counter)), total))
    zero = [c for c in constant if c[2] in (0, False, "")]
    other = [c for c in constant if c not in zero]
    print(f"  always zero/empty: {len(zero)}")
    print(f"  always some other single value: {len(other)}")
    for cls, name, value, total in other[:30]:
        shown = value if not isinstance(value, str) or len(value) < 30 else value[:27] + "..."
        print(f"    {cls}.{name} = {shown!r} ({total} samples)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
