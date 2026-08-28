"""Save file parsing, checksums, and JSON round trips."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from pkhexpy import saves
from pkhexpy.binio import write_u16, write_u32
from pkhexpy.pkm import io as entity_io
from pkhexpy.saves import gen3, gen89, swish
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
    changed = sum(1 for a, b in zip(raw, out) if a != b)
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
        blocks = list(blocks) + [
            SCBlock(0xDEADBEEF, SCTypeCode.OBJECT, bytearray(target_size - used - 9))
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
