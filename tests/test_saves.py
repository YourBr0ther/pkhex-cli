"""Save file parsing, checksums, and JSON round trips."""

from __future__ import annotations

import base64
import collections
import json
from pathlib import Path

import pytest

from pkhexpy import binio, saves
from pkhexpy.binio import write_u16, write_u32
from pkhexpy.pkm import formats
from pkhexpy.pkm import io as entity_io
from pkhexpy.saves import base, gen3, gen89, swish
from pkhexpy.saves.gen3 import FOOTER_COUNTER, FOOTER_ID, SIZE_MAIN, SIZE_SECTOR
from pkhexpy.saves.swish import SCBlock, SCTypeCode


def test_detects_real_save(save_file: Path) -> None:
    sav = saves.read_file(save_file)
    assert sav.GENERATION == 7
    assert sav.checksums_valid
    assert sav.trainer_name


def test_reads_storage(save_file: Path) -> None:
    sav = saves.read_file(save_file)
    stored = list(sav.iter_boxes())
    assert len(stored) > 100
    for _, _, entity in stored:
        assert entity.species > 0
        assert entity.checksum_valid


def test_save_round_trip_is_byte_exact(save_file: Path) -> None:
    raw = save_file.read_bytes()
    assert saves.read_file(save_file).to_bytes() == raw


def test_save_json_round_trip(save_file: Path) -> None:
    raw = save_file.read_bytes()
    sav = saves.read_file(save_file)
    document = json.loads(json.dumps(sav.to_dict(include_raw=True),
                                     ensure_ascii=False))
    rebuilt = saves.from_bytes(base64.b64decode(document["raw_base64"]))
    rebuilt.apply_dict(document)
    assert rebuilt.to_bytes() == raw


def test_editing_a_save_touches_only_that_slot(save_file: Path) -> None:
    raw = save_file.read_bytes()
    sav = saves.read_file(save_file)
    document = sav.to_dict(include_raw=False)
    document["boxes"][0]["slots"][0]["entity"]["fields"]["Nickname"] = "Renamed"

    edited = saves.from_bytes(raw)
    edited.apply_dict(document)
    assert edited.checksums_valid
    assert edited.get_box_slot(0, 0).nickname == "Renamed"

    out = edited.to_bytes()
    changed = sum(1 for a, b in zip(raw, out, strict=False) if a != b)
    assert 0 < changed < 64, "an edit should not rewrite the whole file"


# --- SwishCrypto (Gen8/9) --------------------------------------------------


def test_swish_block_round_trip() -> None:
    blocks = [
        SCBlock(0x0D66012C, SCTypeCode.OBJECT, bytearray(range(256)) * 4),
        SCBlock(0x4F35D0DD, SCTypeCode.UINT32, bytearray((999_999).to_bytes(4, "little"))),
        SCBlock(0x017C3CBB, SCTypeCode.BOOL2),
    ]
    raw = swish.encrypt(blocks)
    assert swish.is_hash_valid(raw)
    decoded = swish.decrypt(raw)
    assert [b.key for b in decoded] == [b.key for b in blocks]
    assert decoded[0].data == blocks[0].data
    assert decoded[1].get_value() == 999_999
    assert decoded[2].get_value() is True
    assert swish.encrypt(decoded) == raw


def test_xorpad_is_involutive() -> None:
    data = bytearray(range(256)) * 3
    original = bytes(data)
    swish.crypt_static_xorpad(data)
    assert bytes(data) != original
    swish.crypt_static_xorpad(data)
    assert bytes(data) == original


def test_gen9_save_storage(entity_files: list[Path]) -> None:
    """Build a Scarlet/Violet-shaped save and read a Pokemon back out of it."""
    source = entity_io.read_file(next(p for p in entity_files if p.suffix == ".pk9"))
    encrypted = source.encrypted_bytes()

    box = bytearray(0x158 * 30 * 32)
    box[:len(encrypted)] = encrypted
    party = bytearray(0x158 * 6 + 1)
    party[:len(encrypted)] = encrypted
    party[0x158 * 6] = 1

    raw = swish.encrypt([
        SCBlock(0x0D66012C, SCTypeCode.OBJECT, box),
        SCBlock(0x3AA1A9AD, SCTypeCode.OBJECT, party),
        SCBlock(0xE3E89BD1, SCTypeCode.OBJECT, bytearray(0x100)),
        SCBlock(0xEDAFF794, SCTypeCode.OBJECT, bytearray(8)),
    ])
    sav = gen89.SAV9SV(raw)
    assert sav.checksums_valid
    assert sav.party_count == 1
    assert sav.get_party_slot(0).species == source.species
    assert sav.get_box_slot(0, 0).species == source.species
    assert sav.to_bytes() == raw


# --- Generation 3 -----------------------------------------------------------


def _blank_gen3() -> bytearray:
    data = bytearray(0x20000)
    for slot in range(2):
        for sector in range(14):
            offset = slot * SIZE_MAIN + sector * SIZE_SECTOR
            write_u16(data, offset + FOOTER_ID, sector)
            write_u32(data, offset + 0xFF8, 0x08012025)
            write_u32(data, offset + FOOTER_COUNTER, 7 if slot == 0 else 3)
    return data


def test_gen3_sectors_and_checksums(entity_files: list[Path]) -> None:
    source = entity_io.read_file(next(p for p in entity_files if p.suffix == ".pk3"))
    sav = gen3.SAV3E(_blank_gen3())
    write_u32(sav.large, sav.MONEY_OFFSET, 55_555)
    sav.large[sav.PARTY_COUNT_OFFSET] = 1
    sav.set_party_slot(0, source)
    sav.set_box_slot(0, 0, source)
    sav.set_box_slot(13, 29, source)

    out = sav.to_bytes()
    reloaded = gen3.SAV3E(out)
    assert reloaded.checksums_valid
    assert reloaded.money == 55_555
    assert reloaded.get_party_slot(0).species == source.species
    assert reloaded.get_box_slot(0, 0).species == source.species
    assert reloaded.get_box_slot(13, 29).species == source.species
    assert reloaded.to_bytes() == out


def test_gen3_active_slot_prefers_higher_counter() -> None:
    data = _blank_gen3()
    assert gen3._active_slot(bytes(data)) == 0
    for sector in range(14):
        write_u32(data, SIZE_MAIN + sector * SIZE_SECTOR + FOOTER_COUNTER, 99)
    assert gen3._active_slot(bytes(data)) == 1


def test_writing_a_short_entity_does_not_resize_the_buffer(
        entity_files: list[Path]) -> None:
    """A stored-size record in a party-size slot must be padded, not shrink the buffer."""
    source = entity_io.read_file(next(p for p in entity_files if p.suffix == ".pk3"))
    sav = gen3.SAV3E(_blank_gen3())
    before = len(sav.large)
    sav.set_party_slot(0, source)
    assert len(sav.large) == before


def test_unknown_size_is_rejected() -> None:
    with pytest.raises(saves.SaveFormatError):
        saves.from_bytes(bytes(1234))


# --- Formats with no public save to test against ----------------------------
#
# Brilliant Diamond has one real save in the corpus; Legends Z-A has none I
# could find anywhere public. These build a save of the right shape so the
# geometry, detection, and round trip are still exercised.


def _build_switch_save(blocks, target_size: int | None = None) -> bytes:
    """Pack SCBlocks, optionally padding to a real save size for detection."""
    if target_size is not None:
        used = sum(b.serialized_length() for b in blocks) + swish.SIZE_HASH
        blocks = [
            *blocks,
            SCBlock(0xDEADBEEF, SCTypeCode.OBJECT, bytearray(target_size - used - 9)),
        ]
    return swish.encrypt(blocks)


def test_legends_za_geometry_differs_from_scarlet_violet() -> None:
    """Z-A shares SV's block keys but pads every slot."""
    sv, za = gen89.SAV9SV(b""), gen89.SAV9ZA(b"")
    assert sv.box_stride == 0x158 and sv.party_stride == 0x158
    assert za.box_stride == 0x158 + 0x40
    assert za.party_stride == 0x158 + 0x48 + 0x40
    assert za.SIZE_BOXSLOT == sv.SIZE_BOXSLOT, "the record inside a slot is the same"
    assert za.KEY_BOX == sv.KEY_BOX and za.KEY_PARTY == sv.KEY_PARTY


def test_legends_za_save_round_trips() -> None:
    from pkhexpy.pkm.formats import PA9

    entity = PA9()
    entity.encryption_constant = 0xC0FFEE01
    entity.pid = 0x1234ABCD
    entity.species = 653
    entity.nickname = "Foxy"
    entity.ivs = (31, 30, 29, 28, 27, 26)
    entity.current_level = 42
    encrypted = entity.encrypted_bytes()

    box = bytearray(gen89.SAV9ZA.BOX_SLOT_STRIDE * 30 * 32)
    party = bytearray(gen89.SAV9ZA.PARTY_SLOT_STRIDE * 6)
    second_box = gen89.SAV9ZA.BOX_SLOT_STRIDE * 30
    box[0:len(encrypted)] = encrypted
    box[second_box:second_box + len(encrypted)] = encrypted
    party[0:len(encrypted)] = encrypted

    raw = _build_switch_save([
        SCBlock(gen89.SAV9ZA.KEY_BOX, SCTypeCode.OBJECT, box),
        SCBlock(gen89.SAV9ZA.KEY_PARTY, SCTypeCode.OBJECT, party),
        SCBlock(gen89.SAV9ZA.KEY_MY_STATUS, SCTypeCode.OBJECT, bytearray(0x100)),
        SCBlock(gen89.SAV9ZA.KEY_PLAY_TIME, SCTypeCode.OBJECT, bytearray(12)),
    ], target_size=0x2F3284)

    sav = saves.from_bytes(raw)
    assert type(sav) is gen89.SAV9ZA, "a real Z-A size should detect as Z-A"
    assert sav.checksums_valid
    assert sav.party_count == 1
    assert sav.get_party_slot(0).species == entity.species
    assert sav.get_box_slot(0, 0).species == entity.species
    assert sav.get_box_slot(1, 0).species == entity.species
    assert sav.get_box_slot(0, 1) is None, "the pad between slots is not a slot"
    assert sav.to_bytes() == raw


def test_bdsp_detects_every_shipped_revision() -> None:
    from pkhexpy.saves import gen8b

    for size, revision in gen8b.VERSION_BY_SIZE.items():
        data = bytearray(size)
        write_u32(data, 0, revision)
        sav = saves.from_bytes(bytes(data))
        assert type(sav) is gen8b.SAV8BS, f"size 0x{size:X} did not detect as BDSP"
        assert sav.BOX_COUNT == 40


def test_bdsp_round_trips_with_a_pokemon_in_it(entity_files: list[Path]) -> None:
    from pkhexpy.saves import gen8b

    source = entity_io.read_file(next(p for p in entity_files if p.suffix == ".pb8"))
    data = bytearray(0xEF0A4)
    write_u32(data, 0, gen8b.VERSION_BY_SIZE[0xEF0A4])
    sav = gen8b.SAV8BS(data)
    sav.set_party_slot(0, source)
    sav.data[sav.PARTY_BASE + sav.PARTY_COUNT_OFFSET] = 1
    sav.set_box_slot(0, 0, source)
    sav.set_box_slot(39, 29, source)

    raw = sav.to_bytes()
    reloaded = saves.from_bytes(raw)
    assert reloaded.checksums_valid, "the MD5 over the file should verify"
    assert reloaded.get_party_slot(0).species == source.species
    assert reloaded.get_box_slot(39, 29).species == source.species
    assert reloaded.to_bytes() == raw


def test_block_key_derivation() -> None:
    """Switch-era block keys are the low 32 bits of FNV-1a over the block name.

    These three names are hardcoded in PKHeX's SAV9SV, which is what makes them
    usable as a check on the hash rather than on this code.
    """
    assert swish.block_key("FSYS_CLUB_HUD_COACH_TEACHER_MATH") == 0xFA1952E8
    assert swish.block_key("FSYS_CLUB_HUD_COACH_TEACHER_LANGUAGE") == 0xE3FFF180
    assert swish.block_key("FEVT_SUB_014_KUI_01_RELEASE") == 0x12AC859B


def _one_per_generation(real_saves: list[Path]) -> list:
    """One readable save from each generation the corpus covers."""
    picked: dict[int, object] = {}
    for path in real_saves:
        try:
            sav = saves.from_bytes(path.read_bytes())
        except saves.SaveFormatError:
            continue
        picked.setdefault(sav.GENERATION, sav)
    if not picked:
        pytest.skip("no saves read from the corpus")
    return [picked[gen] for gen in sorted(picked)]


def test_slot_index_out_of_range_is_rejected(real_saves: list[Path]) -> None:
    """An index past the end would otherwise be turned into an offset anyway,
    and the write would land on whatever else lives there."""
    checked = 0
    for sav in _one_per_generation(real_saves):
        occupant = sav.get_box_slot(0, 0) or sav.get_party_slot(0)
        for box, slot in ((sav.BOX_COUNT, 0), (0, sav.BOX_SLOT_COUNT), (-1, 0)):
            with pytest.raises(IndexError):
                sav.get_box_slot(box, slot)
            with pytest.raises(IndexError):
                sav.set_box_slot(box, slot, occupant)
            checked += 1
        for slot in (sav.PARTY_SLOT_COUNT, -1):
            with pytest.raises(IndexError):
                sav.get_party_slot(slot)
            with pytest.raises(IndexError):
                sav.set_party_slot(slot, occupant)
            checked += 1
    assert checked >= 5 * 5, f"only {checked} bounds checks ran"


def test_entity_from_another_generation_is_rejected(real_saves: list[Path]) -> None:
    """PK4 and PK5 share a stored size, so an unchecked write succeeds and the
    bytes are silently reinterpreted under the wrong layout."""
    by_gen = {sav.GENERATION: sav for sav in _one_per_generation(real_saves)}
    checked = 0
    for gen, sav in by_gen.items():
        alien = next((other.get_box_slot(0, 0) or other.get_party_slot(0)
                      for g, other in by_gen.items() if g != gen), None)
        if alien is None or isinstance(alien, sav.ENTITY):
            continue
        with pytest.raises(TypeError):
            sav.set_box_slot(0, 0, alien)
        with pytest.raises(TypeError):
            sav.set_party_slot(0, alien)
        checked += 1
    assert checked >= 2, f"only {checked} formats were offered an alien entity"


def test_removing_a_party_member_closes_the_gap(real_saves: list[Path]) -> None:
    """The games read a count and expect the party to sit at the front, so a
    hole at the lead is a state no game would have written."""
    checked = 0
    for sav in _one_per_generation(real_saves):
        before = [entity.species_name for _, entity in sav.iter_party()]
        if len(before) < 2:
            continue
        try:
            sav.set_party_slot(0, None)
        except NotImplementedError:
            # Let's Go stores its party as pointers into the box list.
            continue
        reloaded = saves.from_bytes(sav.to_bytes())
        assert reloaded.party_count == len(before) - 1
        assert [e.species_name for _, e in reloaded.iter_party()] == before[1:]
        assert reloaded.checksums_valid
        checked += 1
    assert checked >= 4, f"only {checked} saves had a party to shrink"


def test_adding_a_party_member_raises_the_count(real_saves: list[Path]) -> None:
    checked = 0
    for sav in _one_per_generation(real_saves):
        count = sav.party_count
        if count == 0 or count >= sav.PARTY_SLOT_COUNT:
            continue
        try:
            sav.set_party_slot(count, sav.get_party_slot(0))
        except NotImplementedError:
            continue
        reloaded = saves.from_bytes(sav.to_bytes())
        assert reloaded.party_count == count + 1
        assert len(list(reloaded.iter_party())) == count + 1
        assert reloaded.checksums_valid
        checked += 1
    assert checked >= 2, f"only {checked} saves had room in the party"


def test_writing_past_the_party_end_is_refused(real_saves: list[Path]) -> None:
    """Writing into slot 4 of a party of two would leave a hole behind it."""
    checked = 0
    for sav in _one_per_generation(real_saves):
        count = sav.party_count
        if count == 0 or count + 1 >= sav.PARTY_SLOT_COUNT:
            continue
        with pytest.raises((IndexError, NotImplementedError)):
            sav.set_party_slot(count + 1, sav.get_party_slot(0))
        checked += 1
    assert checked >= 2, f"only {checked} saves had room to leave a gap"


def test_trainer_edits_survive_a_write(real_saves: list[Path]) -> None:
    """Every generation must write back what it reports reading."""
    checked = 0
    for sav in _one_per_generation(real_saves):
        wanted: dict[str, object] = {"tid16": 4242, "play_time": (11, 22, 33)}
        if sav.money is not None:
            wanted["money"] = 12345
        for name, value in wanted.items():
            setattr(sav, name, value)
        reloaded = saves.from_bytes(sav.to_bytes())
        for name, value in wanted.items():
            assert getattr(reloaded, name) == value, (
                f"{type(sav).__name__}.{name} did not survive")
        assert reloaded.checksums_valid
        checked += 1
    assert checked >= 6, f"only {checked} generations were exercised"


def test_trainer_name_survives_a_write(real_saves: list[Path]) -> None:
    """ASCII is representable in every generation's encoding."""
    checked = 0
    for sav in _one_per_generation(real_saves):
        sav.trainer_name = "ASH"
        reloaded = saves.from_bytes(sav.to_bytes())
        assert reloaded.trainer_name == "ASH", type(sav).__name__
        assert reloaded.checksums_valid
        checked += 1
    assert checked >= 6, f"only {checked} generations were exercised"


def test_unencodable_trainer_name_is_rejected(real_saves: list[Path]) -> None:
    """Gen1 to 4 index a per-language glyph table, so a name those glyphs
    cannot spell would be stored truncated at the first one missing."""
    checked = 0
    for sav in _one_per_generation(real_saves):
        # Gen4 indexes one unified table that already contains kana.
        if sav.GENERATION > 3 or sav.japanese:
            continue
        with pytest.raises(ValueError):
            sav.trainer_name = "ひらがな"
        checked += 1
    assert checked >= 2, f"only {checked} legacy saves were exercised"


def test_trainer_edits_made_in_json_reach_the_save(real_saves: list[Path]) -> None:
    """The loop the README advertises: export, edit, write a game file back."""
    checked = 0
    for sav in _one_per_generation(real_saves):
        if sav.money is None:
            continue
        document = sav.to_dict(include_raw=True)
        document["trainer"]["Money"] = 777
        document["trainer"]["TID16"] = 999
        rebuilt = saves.from_bytes(base64.b64decode(document["raw_base64"]))
        rebuilt.apply_dict(document)
        reloaded = saves.from_bytes(rebuilt.to_bytes())
        assert (reloaded.money, reloaded.tid16) == (777, 999)
        assert reloaded.checksums_valid
        checked += 1
    assert checked >= 5, f"only {checked} saves carried money"


def test_unknown_trainer_field_is_rejected(real_saves: list[Path]) -> None:
    """Silently ignoring it is how an edit disappears without a word."""
    sav = _one_per_generation(real_saves)[0]
    with pytest.raises(ValueError, match="unknown trainer field"):
        sav.apply_trainer({"Nonsense": 1})


def test_unedited_trainer_block_changes_nothing(real_saves: list[Path]) -> None:
    """Applying a document straight back must stay byte exact."""
    checked = 0
    for sav in _one_per_generation(real_saves):
        original = bytes(sav.to_bytes())
        document = sav.to_dict(include_raw=True)
        rebuilt = saves.from_bytes(base64.b64decode(document["raw_base64"]))
        rebuilt.apply_dict(document)
        assert rebuilt.to_bytes() == original, type(sav).__name__
        checked += 1
    assert checked >= 6, f"only {checked} generations were exercised"


def test_extra_slots_hold_real_pokemon(real_saves: list[Path]) -> None:
    """The daycare and its neighbours are ordinary Pokemon the games keep
    outside the party and boxes, so a reader that only walks those two misses
    them entirely."""
    found: dict[str, int] = collections.defaultdict(int)
    for path in real_saves:
        try:
            sav = saves.from_bytes(path.read_bytes())
        except saves.SaveFormatError:
            continue
        for slot, entity in sav.iter_extra():
            # Several of these regions double as scratch space, so anything
            # reported must survive its own checksum and name a real species.
            assert entity.species_name is not None, f"{path.name} {slot.name}"
            assert entity.checksum_valid, f"{path.name} {slot.name}"
            found[slot.kind] += 1
    assert sum(found.values()) >= 40, f"only found {dict(found)}"
    assert found["daycare"] >= 25, f"daycare is the universal one: {dict(found)}"


def test_extra_slots_survive_a_round_trip(real_saves: list[Path]) -> None:
    checked = 0
    for path in real_saves:
        try:
            sav = saves.from_bytes(path.read_bytes())
        except saves.SaveFormatError:
            continue
        before = [(s.kind, s.index, e.species) for s, e in sav.iter_extra()]
        if not before:
            continue
        original = bytes(sav.to_bytes())
        document = sav.to_dict(include_raw=True)
        assert len(document["extra"]) == len(before)
        rebuilt = saves.from_bytes(base64.b64decode(document["raw_base64"]))
        rebuilt.apply_dict(document)
        assert rebuilt.to_bytes() == original, path.name
        assert [(s.kind, s.index, e.species)
                for s, e in rebuilt.iter_extra()] == before
        checked += 1
    assert checked >= 15, f"only {checked} saves carried extra Pokemon"


def test_extra_slots_are_writable(real_saves: list[Path]) -> None:
    checked = 0
    for path in real_saves:
        try:
            sav = saves.from_bytes(path.read_bytes())
        except saves.SaveFormatError:
            continue
        extra = list(sav.iter_extra())
        if not extra:
            continue
        slot, entity = extra[0]
        entity.evs = (252, 0, 0, 0, 0, 0)
        sav.set_extra_slot(slot.kind, slot.index, entity)
        reloaded = saves.from_bytes(sav.to_bytes())
        assert reloaded.get_extra_slot(slot.kind, slot.index).evs[0] == 252
        assert reloaded.checksums_valid
        checked += 1
    assert checked >= 15, f"only {checked} saves carried extra Pokemon"


def test_unknown_extra_slot_is_rejected(real_saves: list[Path]) -> None:
    sav = _one_per_generation(real_saves)[0]
    with pytest.raises(KeyError):
        sav.get_extra_slot("nonsense", 0)


#: Trainer fields that are stored bytes rather than derived, so a save which
#: implements one must also be able to write it back.
WRITABLE_TRAINER_FIELDS = ("trainer_name", "tid16", "sid16", "money", "play_time")


def test_every_implemented_trainer_field_can_be_written(
        real_saves: list[Path]) -> None:
    """A getter without a setter is how an edit made through the JSON gets
    accepted and then silently dropped, which is what happened before these
    became descriptors.

    Only fields the save class actually implements count. SaveFile supplies
    defaults for the rest, so Gen1 reports a secret ID of 0 despite the games
    having no such thing.
    """
    checked = 0
    for sav in _one_per_generation(real_saves):
        for name in WRITABLE_TRAINER_FIELDS:
            owner = next((c for c in type(sav).__mro__ if name in c.__dict__), None)
            if owner is None or owner is base.SaveFile:
                continue
            value = getattr(sav, name)
            if value is None:
                continue
            setattr(sav, name, value)  # writing back what it reported must work
            assert getattr(sav, name) == value, f"{type(sav).__name__}.{name}"
            checked += 1
    assert checked >= 30, f"only {checked} field writes were exercised"


def test_width_generic_reads_and_writes_refuse_to_run_past_the_end() -> None:
    """A short slice used to decode to a plausible smaller number rather than
    failing, which is what the trainer descriptors read through."""
    buffer = bytearray(8)
    assert binio.read_int(buffer, 4, 4) == 0
    binio.write_int(buffer, 4, 4, 1)
    for offset in (5, -1, 99):
        with pytest.raises(IndexError):
            binio.read_int(buffer, offset, 4)
        with pytest.raises(IndexError):
            binio.write_int(buffer, offset, 4, 0)


def test_gameboy_daycare_eggs_match_their_parents(real_saves: list[Path]) -> None:
    """Gen1 and Gen2 store the daycare as a scattered record, nickname and OT
    written in front of the body rather than pooled with the box names, so a
    wrong offset here still decodes to something.

    The egg is the check that cannot be faked: it has to be a species those two
    parents could actually produce.
    """
    #: Egg species each parent pair in the corpus must produce.
    expected = {
        frozenset({"Hitmontop", "Ditto"}): "Tyrogue",
        frozenset({"Sandshrew", "Swinub"}): "Swinub",
        frozenset({"Abra", "Jynx"}): "Smoochum",
        frozenset({"Eevee", "Houndour"}): "Houndour",
    }
    checked = 0
    for path in real_saves:
        try:
            sav = saves.from_bytes(path.read_bytes())
        except saves.SaveFormatError:
            continue
        if sav.GENERATION != 2:
            continue
        found = {slot.index: entity for slot, entity in sav.iter_extra()}
        if set(found) != {0, 1, 2}:
            continue
        parents = frozenset(found[i].species_name for i in (0, 1))
        egg = expected.get(parents)
        if egg is None:
            continue
        assert found[2].species_name == egg, (
            f"{path.name}: {sorted(parents)} produced {found[2].species_name}")
        assert found[2].current_level == 5, "a Gen2 egg hatches at level 5"
        checked += 1
    assert checked >= 3, f"only {checked} daycare pairs were checked"


def test_gameboy_special_stat_is_writable_under_both_names(
        entity_files: list[Path]) -> None:
    """Gen1 and Gen2 have one Special value where later games have two. Both
    names read it, so both must write it."""
    entity = formats.PK2()
    entity.ev_spa = 111
    assert entity.ev_spd == entity.ev_spc == 111
    entity.ev_spd = 222
    assert entity.ev_spa == entity.ev_spc == 222


def test_version_exclusive_extra_slots_hold_the_right_species(
        real_saves: list[Path]) -> None:
    """Some extra storage can only ever hold one species, which makes it a
    check on the offset that no other slot gives.

    A wrong offset would have to land on exactly the right Pokemon to pass.
    """
    #: Save key to the only species that slot can hold in that game.
    expected = {
        ("sv", "ride_legend"): {"Koraidon", "Miraidon"},
        ("b2w2", "fused"): {"Zekrom", "Reshiram"},
    }
    checked = 0
    for path in real_saves:
        try:
            sav = saves.from_bytes(path.read_bytes())
        except saves.SaveFormatError:
            continue
        for slot, entity in sav.iter_extra():
            allowed = expected.get((sav.KEY, slot.kind))
            if allowed is None:
                continue
            assert entity.species_name in allowed, (
                f"{path.name} {slot.name}: {entity.species_name} "
                f"is not one of {sorted(allowed)}")
            checked += 1
    assert checked >= 3, f"only {checked} version-exclusive slots were seen"


def test_legends_za_declares_its_own_extra_storage() -> None:
    """Z-A shares Scarlet and Violet's box and party keys but none of the
    keys for storage outside them, so inheriting SV's table would have pointed
    at blocks Z-A does not have."""
    sv_kinds = {region.kind for region in gen89.SAV9SV.EXTRA_REGIONS}
    za_kinds = {region.kind for region in gen89.SAV9ZA.EXTRA_REGIONS}
    assert "ride_legend" in sv_kinds and "ride_legend" not in za_kinds
    assert {"shiny_cache", "event_gift"} <= za_kinds
    sv_keys = {region.source for region in gen89.SAV9SV.EXTRA_REGIONS}
    za_keys = {region.source for region in gen89.SAV9ZA.EXTRA_REGIONS}
    shared = sv_keys & za_keys
    assert shared == {0x916BCA9E}, (
        f"only the Calyrex fusion key is shared, found {shared}")
