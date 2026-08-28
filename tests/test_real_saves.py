"""Validation against real save files from public collections.

These cover the generations the synthetic tests cannot reach honestly: a save
built from this library's own understanding of a format proves only that the
library agrees with itself. Run tools/fetch_test_saves.sh first.
"""

from __future__ import annotations

import base64
import collections
import json
from pathlib import Path

import pytest

from pkhexpy import saves


@pytest.fixture(scope="module")
def parsed(real_saves: list[Path]) -> list[tuple[Path, bytes, object]]:
    """Every recognized save, parsed once and shared across the module.

    Re-parsing 40 MB per test dominated the suite runtime.
    """
    out = []
    for path in real_saves:
        raw = path.read_bytes()
        try:
            out.append((path, raw, saves.from_bytes(raw)))
        except saves.SaveFormatError:
            continue
    if not out:
        pytest.fail("the corpus is present but nothing in it parsed as a save")
    return out


def test_corpus_covers_many_games(parsed) -> None:
    games = collections.Counter(sav.GAME for _, _, sav in parsed)
    assert len(games) >= 8, f"expected a broad corpus, got {dict(games)}"


def test_corpus_reaches_every_generation(parsed) -> None:
    generations = {sav.GENERATION for _, _, sav in parsed}
    missing = set(range(1, 10)) - generations
    assert not missing, f"no real save covering generation(s) {sorted(missing)}"


def test_every_recognized_save_round_trips(parsed) -> None:
    checked = 0
    for path, raw, sav in parsed:
        assert sav.to_bytes() == raw, f"{path.name} ({sav.GAME}) changed on write"
        checked += 1
    assert checked >= 10


def test_json_round_trip(parsed) -> None:
    checked = 0
    for path, raw, sav in parsed:
        document = json.loads(json.dumps(sav.to_dict(include_raw=True),
                                         ensure_ascii=False))
        rebuilt = saves.from_bytes(base64.b64decode(document["raw_base64"]))
        rebuilt.apply_dict(document)
        assert rebuilt.to_bytes() == raw, f"{path.name} ({sav.GAME}) failed via JSON"
        checked += 1
    # Without this the test passes vacuously if detection stops recognizing
    # anything, since the loop body would never run.
    assert checked >= 10


def test_stored_pokemon_are_sane(parsed) -> None:
    total = 0
    for path, _, sav in parsed:
        for box, slot, entity in sav.iter_boxes():
            assert entity.checksum_valid, f"{path.name} box {box} slot {slot}"
            assert 0 < entity.species <= 1025, f"{path.name} box {box} slot {slot}"
            assert 1 <= entity.current_level <= 100
            total += 1
        for slot, entity in sav.iter_party():
            assert entity.checksum_valid, f"{path.name} party {slot}"
            assert 0 < entity.species <= 1025
            total += 1
    assert total > 1000, f"expected a large corpus, read {total}"


def test_trainer_details_are_plausible(parsed) -> None:
    checked = 0
    for path, _, sav in parsed:
        assert sav.checksums_valid, f"{path.name} ({sav.GAME}) has bad checksums"
        assert 0 <= sav.tid16 <= 0xFFFF
        if sav.money is not None:
            assert 0 <= sav.money <= 9_999_999, f"{path.name} money {sav.money}"
        played = sav.play_time
        if played is not None:
            hours, minutes, seconds = played
            assert 0 <= hours <= 9999, f"{path.name} play time {played}"
            assert 0 <= minutes < 60 or minutes == 0
            assert 0 <= seconds < 60 or seconds == 0
        checked += 1
    assert checked >= 10


def _encodable_name(entity) -> str:
    """A nickname the entity's own encoding can represent.

    Gen1-4 use per-language glyph tables, so a Japanese Pokemon has no
    half-width Latin letters to spell an ASCII name with.
    """
    for candidate in ("Edited", "ＥＤＩＴ", "エディト"):
        try:
            entity.clone().nickname = candidate
        except ValueError:
            continue
        return candidate
    return ""


def test_editing_touches_only_the_edited_slot(parsed) -> None:
    checked = 0
    for path, raw, sav in parsed:
        boxed = next(iter(sav.iter_boxes()), None)
        if boxed is None:
            continue
        box, slot, entity = boxed
        name = _encodable_name(entity)
        if not name:
            continue
        document = sav.to_dict(include_raw=False)
        target = next(b for b in document["boxes"] if b["box"] == box)
        record = next(s for s in target["slots"] if s["slot"] == slot)
        record["entity"]["fields"]["Nickname"] = name

        edited = saves.from_bytes(raw)
        edited.apply_dict(document)
        assert edited.checksums_valid, path.name
        assert edited.get_box_slot(box, slot).nickname == name, path.name

        changed = sum(1 for a, b in zip(raw, edited.to_bytes()) if a != b)
        # Gen4/5 re-encrypt the whole record when its checksum changes, so allow
        # a slot's worth of movement; anything larger means unrelated damage.
        assert 0 < changed <= sav.SIZE_BOXSLOT + 64, f"{path.name} changed {changed}"
        checked += 1
    assert checked >= 5
