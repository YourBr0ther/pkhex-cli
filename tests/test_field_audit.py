"""Field-level checks across the real save corpus.

A byte-exact round trip proves no data is lost. It proves nothing about
interpretation: reading Ability from the wrong offset still writes it back to
that same wrong offset. These tests look at the values themselves.
"""

from __future__ import annotations

import collections
import contextlib
from pathlib import Path

import pytest

from pkhexpy import data, saves

#: Upper bound each field's value must respect. "iv" and "ev" defer to the
#: format's own maximum, which differs between generations.
LIMITS: dict[str, object] = {
    "IV_HP": "iv", "IV_ATK": "iv", "IV_DEF": "iv",
    "IV_SPE": "iv", "IV_SPA": "iv", "IV_SPD": "iv",
    "EV_HP": "ev", "EV_ATK": "ev", "EV_DEF": "ev",
    "EV_SPE": "ev", "EV_SPA": "ev", "EV_SPD": "ev",
    "Nature": 24, "StatNature": 24, "StatAlignment": 24,
    "Gender": 2, "AbilityNumber": 4,
    "CurrentFriendship": 255, "OriginalTrainerFriendship": 255,
    "HandlingTrainerFriendship": 255,
    "PokerusStrain": 15, "PokerusDays": 4,
    "MetLevel": 100, "Stat_Level": 100,
    "ContestCool": 255, "ContestBeauty": 255, "ContestCute": 255,
    "ContestSmart": 255, "ContestTough": 255, "ContestSheen": 255,
    "Move1_PPUps": 3, "Move2_PPUps": 3, "Move3_PPUps": 3, "Move4_PPUps": 3,
    "Language": 12,
}

#: Fields that index a packaged name list.
NAME_LIMITS = {
    "Species": "species", "Ability": "abilities",
    "Move1": "moves", "Move2": "moves", "Move3": "moves", "Move4": "moves",
    "RelearnMove1": "moves", "RelearnMove2": "moves",
    "RelearnMove3": "moves", "RelearnMove4": "moves",
}

#: Fields a large population of Pokemon must vary in. A constant value here is
#: what a wrong offset looks like.
MUST_VARY = [
    "Species", "PID", "TID16", "EXP", "Nature", "Ability", "Ball",
    "MetLocation", "IV_HP", "IV_ATK", "IV_DEF", "IV_SPE", "IV_SPA", "IV_SPD",
    "Move1", "Move2", "Move3", "Move4", "CurrentFriendship", "Gender",
    "MetLevel", "OriginalTrainerFriendship",
]

#: Games that genuinely removed a mechanic, so the field really is constant.
EXPECTED_CONSTANT = {
    ("PB7", "EV_HP"), ("PB7", "EV_ATK"), ("PB7", "EV_DEF"),
    ("PB7", "EV_SPE"), ("PB7", "EV_SPA"), ("PB7", "EV_SPD"),  # Let's Go uses AVs
}


@pytest.fixture(scope="module")
def population(real_saves: list[Path]):
    """Every Pokemon in the corpus, grouped by entity format."""
    grouped: dict[str, list] = collections.defaultdict(list)
    for path in real_saves:
        try:
            sav = saves.from_bytes(path.read_bytes())
        except saves.SaveFormatError:
            continue
        for _, _, entity in sav.iter_boxes():
            grouped[type(entity).__name__].append(entity)
        for _, entity in sav.iter_party():
            grouped[type(entity).__name__].append(entity)
    if not grouped:
        pytest.skip("no entities read from the corpus")
    return grouped


@pytest.fixture(scope="module")
def party_population(real_saves: list[Path]):
    """Party Pokemon only, grouped by format.

    Only the party keeps a live stat block. A boxed Pokemon holds whatever
    stats it had when it was last withdrawn, so it says nothing about whether
    the recomputation is right.
    """
    grouped: dict[str, list] = collections.defaultdict(list)
    for path in real_saves:
        try:
            sav = saves.from_bytes(path.read_bytes())
        except saves.SaveFormatError:
            continue
        for _, entity in sav.iter_party():
            grouped[type(entity).__name__].append(entity)
    if not grouped:
        pytest.skip("no party entities read from the corpus")
    return grouped


def test_population_is_large_enough(population) -> None:
    total = sum(len(v) for v in population.values())
    assert total > 5000, f"only {total} Pokemon; the audit needs a big sample"
    assert len(population) >= 8, f"only {sorted(population)} formats represented"


def test_no_field_exceeds_its_possible_range(population) -> None:
    lengths = {kind: len(data.name_list(kind)) for kind in set(NAME_LIMITS.values())}
    problems: list[str] = []
    for cls, entities in population.items():
        worst: dict[str, tuple[int, int]] = {}
        for entity in entities:
            for field in type(entity)._fields.values():
                name = field.pkhex_name
                limit = LIMITS.get(name)
                if limit == "iv":
                    limit = entity.MAX_IV
                elif limit == "ev":
                    limit = entity.MAX_EV
                elif name in NAME_LIMITS:
                    limit = lengths[NAME_LIMITS[name]] - 1
                if limit is None:
                    continue
                try:
                    value = field.decode(entity)
                except Exception:
                    continue
                if isinstance(value, bool) or not isinstance(value, int):
                    continue
                if not 0 <= value <= limit and value > worst.get(name, (0, 0))[0]:
                    worst[name] = (value, limit)
        for name, (value, limit) in worst.items():
            problems.append(f"{cls}.{name} reached {value} (limit {limit})")
    assert not problems, "fields outside their possible range:\n  " + "\n  ".join(problems)


def test_core_fields_are_not_stuck_at_one_value(population) -> None:
    problems: list[str] = []
    for cls, entities in population.items():
        if len(entities) < 150:
            continue
        seen: dict[str, set] = collections.defaultdict(set)
        for entity in entities:
            for field in type(entity)._fields.values():
                if field.pkhex_name in MUST_VARY:
                    # A field outside a stored-size record simply has no value.
                    with contextlib.suppress(Exception):
                        seen[field.pkhex_name].add(field.decode(entity))
        for name, values in seen.items():
            if len(values) == 1 and (cls, name) not in EXPECTED_CONSTANT:
                problems.append(f"{cls}.{name} is always {values.pop()!r} "
                                f"across {len(entities)} samples")
    assert not problems, "constant where variation is expected:\n  " + "\n  ".join(problems)


def test_level_agrees_with_experience(population) -> None:
    """Level is computed from EXP and the species' growth curve; the stored
    party level should agree with it."""
    mismatches: list[str] = []
    compared = 0
    for cls, entities in population.items():
        for entity in entities:
            # Box slots are often stored-size and have no party stat block.
            stored = getattr(entity, "stat_level", 0)
            if not stored:
                continue
            compared += 1
            computed = entity.current_level
            if abs(stored - computed) > 1:
                mismatches.append(f"{cls} {entity.species_name}: "
                                  f"stored {stored} vs computed {computed}")
    assert compared > 500, f"only {compared} entities carried a stat block"
    # A hacked Pokemon can disagree; a wrong EXP offset makes most of them.
    # The tolerance is a share of what was actually compared, not of the whole
    # population, or a format-wide break would hide under the larger number.
    assert len(mismatches) < compared * 0.02, (
        f"{len(mismatches)}/{compared} levels disagree with EXP:\n  "
        + "\n  ".join(mismatches[:10]))


def test_names_resolve_for_every_species_seen(population) -> None:
    unresolved = set()
    for entities in population.values():
        for entity in entities:
            if entity.species_name in (None, ""):
                unresolved.add(entity.species)
    assert not unresolved, f"no name for species ids {sorted(unresolved)}"


#: Formats whose stored stats match the recomputation exactly across the whole
#: corpus. A single miss here means the formula or an input offset broke.
EXACT_STAT_FORMATS = ("PK2", "PK5", "PK6", "PK7", "PK8", "PK9", "PB8")


def test_party_stats_recompute_from_their_inputs(party_population) -> None:
    """Recompute each stat block from base stats, IVs, EVs, level and nature.

    The games store the result next to every input, so agreement checks all of
    them at once, and it is the only check here that a wrong base-stat table or
    a swapped IV offset cannot survive.

    Disagreement is expected in a minority of cases and is not a bug: the games
    only recompute stats on level-up, so EVs earned since the last one are not
    reflected yet, and edited saves carry stat blocks no input can produce.
    """
    agree: collections.Counter = collections.Counter()
    disagree: collections.Counter = collections.Counter()
    examples: list[str] = []
    for cls, entities in party_population.items():
        for entity in entities:
            stored = entity.stored_stats
            computed = entity.calculated_stats()
            # Stored-size records have no stat block, and Let's Go and Legends
            # Arceus use formulas this port does not implement.
            if stored is None or computed is None or not any(stored):
                continue
            if tuple(stored) == tuple(computed):
                agree[cls] += 1
            else:
                disagree[cls] += 1
                if len(examples) < 10:
                    examples.append(f"{cls} {entity.species_name} "
                                    f"lv{entity.current_level}: stored {stored} "
                                    f"computed {computed}")
    compared = sum(agree.values()) + sum(disagree.values())
    assert compared > 200, f"only {compared} party slots carried a stat block"
    assert sum(agree.values()) > compared * 0.94, (
        f"{sum(disagree.values())}/{compared} stat blocks disagree:\n  "
        + "\n  ".join(examples))

    for cls in EXACT_STAT_FORMATS:
        if agree[cls] + disagree[cls] < 5:
            continue
        assert not disagree[cls], (
            f"{cls} should recompute exactly, but {disagree[cls]} of "
            f"{agree[cls] + disagree[cls]} disagree:\n  " + "\n  ".join(
                e for e in examples if e.startswith(cls)))
