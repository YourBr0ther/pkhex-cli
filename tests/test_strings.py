"""Character encoding round trips across every generation."""

from __future__ import annotations

import pytest

from pkhexpy import strings
from pkhexpy.strings import tables


@pytest.mark.parametrize("generation,text,size", [
    (1, "RED", 11), (2, "GOLD", 11), (3, "MAY", 8), (4, "Lucas", 16),
    (5, "Hilda", 16), (6, "Calem", 26), (7, "Sun", 26), (8, "Gloria", 26),
    (9, "Juliana", 26),
])
def test_round_trip(generation: int, text: str, size: int) -> None:
    buffer = bytearray(size)
    strings.set_string(buffer, text, 12, generation, language=2)
    assert strings.get_string(bytes(buffer), generation, language=2) == text


def test_japanese_gen1() -> None:
    buffer = bytearray(11)
    strings.set_string(buffer, "サトシ", 5, 1, jp=True, language=1)
    assert strings.get_string(bytes(buffer), 1, jp=True, language=1) == "サトシ"


def test_max_length_truncates() -> None:
    buffer = bytearray(26)
    strings.set_string(buffer, "AAAAAAAAAAAAAAAA", 12, 9)
    assert strings.get_string(bytes(buffer), 9) == "A" * 12


def test_gender_symbol_normalizes_for_display() -> None:
    """Gen4/5 store ♂ in a private-use slot but should read back as ♂."""
    buffer = bytearray(20)
    strings.set_string(buffer, "Nidoran♂", 12, 5)
    assert strings.get_string(bytes(buffer), 5) == "Nidoran♂"


def test_tables_match_upstream_sizes() -> None:
    assert len(tables.G1_EN) == 256
    assert len(tables.G3_EN) == 256
    assert len(tables.G4_INT) == 493
    assert len(tables.G4_KOR) == 2406


def test_known_encodings() -> None:
    assert tables.G1_EN[0x80] == "A"
    assert tables.G3_EN[0xBB] == "A"
    assert tables.G4_INT[0x121] == "0"


def test_gen2_ligatures_expand_to_the_two_characters_they_stand_for() -> None:
    """One byte in a Gen2 box name can mean an apostrophe plus a letter. Only
    box names and mail use them, which is why the entity decoder leaves them."""
    from pkhexpy.strings.gen12 import inflate_ligatures

    # Index 4 is 's in English and 's in French, the one French entry that
    # takes the apostrophe first.
    assert inflate_ligatures("MOM４", 2) == "MOM’s"
    assert inflate_ligatures("MOM８", 3) == "MOM’s"
    # Everything else in French and German puts the apostrophe last, and the
    # two languages carry different letters at the same index.
    assert inflate_ligatures("０", 3) == "c’"
    assert inflate_ligatures("０", 2) == "’d"
    # Japanese and Korean have none.
    assert inflate_ligatures("MOM４", 1) == "MOM４"
    assert inflate_ligatures("MOM４", 8) == "MOM４"
    # A character that is not a ligature code passes through untouched.
    assert inflate_ligatures("BEST {}", 2) == "BEST {}"
