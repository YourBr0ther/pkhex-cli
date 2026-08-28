"""Entity parsing, round trips, and JSON conversion against PKHeX's fixtures."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pkhexpy.pkm import io, serialize
from pkhexpy.pkm.formats import ALL_FORMATS, PK9

#: PKHeX names its files "<dex><shiny> - <nickname> - <hex>", so the filename is
#: an independent check on what the parser reads out of the bytes.
NAME_RE = re.compile(r"^(\d{3,4})(?:-\d+)?\s*(★)?\s*-\s*([^-]+?)\s*-\s*[0-9A-Fa-f]{4,}")

#: The full naming scheme, which also encodes the form, the checksum, and the
#: encryption constant: "{Species:0000}{-Form:00}{ *} - {Nickname} - {chk:X4}{EC:X8}".
FULL_NAME_RE = re.compile(
    r"^(?P<species>\d{3,4})(?:-(?P<form>\d{2}))?(?P<star> ★)? - (?P<nick>.*) - "
    r"(?P<hex>[0-9A-Fa-f]{4}|[0-9A-Fa-f]{12})(?:[ .].*)?$"
)


def test_every_format_declares_its_geometry() -> None:
    for cls in ALL_FORMATS:
        assert cls.SIZE_STORED > 0, cls.__name__
        assert cls.SIZE_PARTY >= cls.SIZE_STORED, cls.__name__
        assert 1 <= cls.FORMAT <= 9, cls.__name__
        assert cls.CONTEXT, cls.__name__


def test_species_matches_filename(entity_files: list[Path]) -> None:
    checked = 0
    for path in entity_files:
        match = NAME_RE.match(path.name)
        if not match:
            continue
        entity = io.read_file(path)
        assert entity.species == int(match.group(1)), path.name
        checked += 1
    assert checked > 100, "expected the fixture set to cover many files"


def test_shiny_matches_filename(entity_files: list[Path]) -> None:
    starred = 0
    for path in entity_files:
        match = NAME_RE.match(path.name)
        if not match or match.group(2) != "★":
            continue
        starred += 1
        assert io.read_file(path).is_shiny, path.name
    assert starred > 10


def test_form_matches_filename(entity_files: list[Path]) -> None:
    """Form is derived from the PID in Gen3 and from the DVs in Gen2."""
    checked = 0
    for path in entity_files:
        match = FULL_NAME_RE.match(path.stem)
        if not match:
            continue
        entity = io.read_file(path)
        assert entity.form == int(match.group("form") or 0), path.name
        checked += 1
    assert checked > 150


def test_checksum_and_encryption_constant_match_filename(
        entity_files: list[Path]) -> None:
    """The filename's hex suffix is the stored checksum and encryption constant.

    Getting the encryption constant right matters most: it is the value the
    block shuffle and the cipher are both keyed from, so a wrong read would
    corrupt everything downstream of it.
    """
    from pkhexpy import crypto
    from pkhexpy.saves import checksums

    checked = 0
    for path in entity_files:
        match = FULL_NAME_RE.match(path.stem)
        if not match or len(match.group("hex")) != 12:
            continue
        entity = io.read_file(path)
        want_checksum = int(match.group("hex")[:4], 16)
        want_ec = int(match.group("hex")[4:], 16)

        assert entity.encryption_constant == want_ec, path.name

        stored = getattr(entity, "checksum", None)
        if stored is None:
            stored = crypto.add16(entity.data, 8, entity.SIZE_STORED)
        # The GameCube formats were named with a CRC over the whole record
        # rather than the usual 16-bit sum.
        whole = checksums.crc16_ccitt(bytes(entity.data))
        assert want_checksum in (stored, whole), (
            f"{path.name}: checksum {stored:04X} / crc {whole:04X} != {want_checksum:04X}"
        )
        checked += 1
    assert checked > 150


def test_byte_exact_round_trip(entity_files: list[Path]) -> None:
    for path in entity_files:
        raw = path.read_bytes()
        assert io.to_bytes(io.read_file(path)) == raw, path.name


def test_json_round_trip(entity_files: list[Path]) -> None:
    for path in entity_files:
        raw = path.read_bytes()
        document = json.loads(json.dumps(serialize.to_dict(io.read_file(path)),
                                         ensure_ascii=False))
        assert io.to_bytes(serialize.from_dict(document)) == raw, path.name


def test_checksums_valid(entity_files: list[Path]) -> None:
    for path in entity_files:
        entity = io.read_file(path)
        assert entity.checksum_valid, path.name


def test_editing_through_json_changes_the_bytes(entity_files: list[Path]) -> None:
    path = next(p for p in entity_files if p.suffix == ".pk9")
    document = serialize.to_dict(io.read_file(path))
    document["fields"]["Nickname"] = "Renamed"
    document["fields"]["EV_HP"] = 252
    entity = serialize.from_dict(document)
    assert entity.nickname == "Renamed"
    assert entity.ev_hp == 252
    assert entity.checksum_valid

    reparsed = io.from_bytes(io.to_bytes(entity), extension=".pk9")
    assert reparsed.nickname == "Renamed"
    assert reparsed.ev_hp == 252


def test_unencodable_name_is_rejected() -> None:
    """A Japanese Gen3 record has no half-width Latin letters to spell with."""
    from pkhexpy.pkm.formats import PK3

    entity = PK3()
    entity.language = 1
    with pytest.raises(ValueError, match="cannot be written"):
        entity.nickname = "Edited"
    entity.nickname = "ホエルコ"          # the full-width table has these
    assert entity.nickname == "ホエルコ"

    english = PK3()
    english.language = 2
    english.nickname = "Edited"
    assert english.nickname == "Edited"


def test_long_name_is_truncated_not_rejected() -> None:
    entity = PK9()
    entity.nickname = "A" * 40
    assert entity.nickname == "A" * entity.MAX_STRING_LENGTH_NICKNAME


def test_unknown_field_assignment_is_rejected() -> None:
    entity = PK9()
    with pytest.raises(AttributeError):
        entity.not_a_real_field = 1


def test_level_follows_experience() -> None:
    entity = PK9()
    entity.species = 25          # Pikachu, medium-fast growth
    entity.current_level = 50
    assert entity.exp == 125_000
    assert entity.current_level == 50


def test_ivs_pack_into_one_word() -> None:
    entity = PK9()
    entity.ivs = (31, 0, 31, 15, 31, 31)
    assert entity.ivs == (31, 0, 31, 15, 31, 31)
    assert entity.iv32 == 0x3FF7FC1F
