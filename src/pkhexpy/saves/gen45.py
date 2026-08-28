"""DS-era saves: Diamond/Pearl, Platinum, HeartGold/SoulSilver, and Gen5.

Gen4 splits the save into a general block and a storage block, each written
twice into a 0x40000-byte partition; the copy with the higher footer counter is
the live one. Gen5 instead uses a flat table of CRC-checked blocks, each with a
checksum and a mirrored copy of that checksum near the end of the file.
"""

from __future__ import annotations

from typing import ClassVar

import json
from functools import lru_cache

from .. import crypto
from ..binio import read_u16, read_u32, write_u16, write_u32
from ..data import DATA_DIR
from ..pkm.formats import PK4, PK5
from . import checksums
from . import fields
from .base import ExtraRegion, SaveFile

SIZE_G4RAW = 0x80000
SIZE_G5RAW = 0x80000
PARTITION_SIZE = 0x40000

MAGIC_JAPAN_INTL = 0x20060623
MAGIC_KOREAN = 0x20070903


def _compare_counters(a: int, b: int) -> int:
    """0 = first is newer, 1 = second, 2 = equal. Mirrors PKHeX's rollover rules."""
    if a == 0xFFFFFFFF and b != 0xFFFFFFFE:
        return 1
    if b == 0xFFFFFFFF and a != 0xFFFFFFFE:
        return 0
    if a > b:
        return 0
    if a < b:
        return 1
    return 2


def compare_footers(data: bytes, offset1: int, offset2: int) -> int:
    major = _compare_counters(read_u32(data, offset1), read_u32(data, offset2))
    if major != 2:
        return major
    minor = _compare_counters(read_u32(data, offset1 + 4), read_u32(data, offset2 + 4))
    return 1 if minor == 1 else 0


# --------------------------------------------------------------------------
# Generation 4
# --------------------------------------------------------------------------


class SAV4(SaveFile):
    GENERATION = 4
    STRING_GENERATION = 4
    ENTITY = PK4
    BOX_COUNT = 18
    BOX_SLOT_COUNT = 30
    SIZE_BOXSLOT = 136
    SIZE_PARTY_SLOT = 236
    MAX_STRING_LENGTH_TRAINER = 7

    GENERAL_SIZE: int = 0
    STORAGE_SIZE: int = 0
    STORAGE_START: int = 0
    FOOTER_SIZE: int = 0x14
    #: Offsets within the general block.
    TRAINER_OFFSET: int = 0x64
    PARTY_OFFSET: int = 0x98
    #: Offset of box 0 within the storage block, past the current-box index.
    BOX_START: int = 4
    #: Bytes per box chunk. Sinnoh packs boxes back to back; HG/SS pads each
    #: chunk out to 0x1000.
    BOX_STRIDE: int = 30 * 136

    #: Offset of the daycare inside the general block. Two slots, spaced a
    #: party-sized record apart, of which only the stored part is the record;
    #: the tail of each holds the experience earned while deposited.
    DAYCARE_OFFSET: int | None = None
    #: HG/SS parks the Pokemon out on a Pokewalker course here. It lives
    #: nowhere else in the save, so a walk in progress is lost without it.
    WALKER_OFFSET: int | None = None

    def extra_regions(self) -> tuple[ExtraRegion, ...]:
        regions: list[ExtraRegion] = []
        if self.DAYCARE_OFFSET is not None:
            regions.append(ExtraRegion(
                "daycare", 2, crypto.SIZE_4PARTY, self.DAYCARE_OFFSET,
                size=crypto.SIZE_4STORED))
        if self.WALKER_OFFSET is not None:
            regions.append(ExtraRegion(
                "pokewalker", 1, 0, self.WALKER_OFFSET,
                size=crypto.SIZE_4STORED))
        return tuple(regions)

    def _extra_base(self, region: ExtraRegion) -> tuple[bytearray, int]:
        return self.data, self.general_base

    def __init__(self, data: bytes | bytearray) -> None:
        super().__init__(data)
        self.general_base = self._active_base(0, self.GENERAL_SIZE)
        self.storage_base = self._active_base(self.STORAGE_START, self.STORAGE_SIZE)

    def _active_base(self, start: int, length: int) -> int:
        footer = start + length - 0x14
        newest = compare_footers(bytes(self.data), footer, footer + PARTITION_SIZE)
        return (0 if newest == 0 else PARTITION_SIZE) + start

    # --- block slices --------------------------------------------------------

    @property
    def general(self) -> memoryview:
        return memoryview(self.data)[self.general_base:self.general_base + self.GENERAL_SIZE]

    @property
    def storage(self) -> memoryview:
        return memoryview(self.data)[self.storage_base:self.storage_base + self.STORAGE_SIZE]

    # --- storage -------------------------------------------------------------

    def _box_offset(self, box: int) -> int:
        return self.BOX_START + box * self.BOX_STRIDE

    def _party_offset(self, slot: int) -> int:
        return self.PARTY_OFFSET + self.SIZE_PARTY_SLOT * slot

    @property
    def party_count(self) -> int:
        return self.data[self.general_base + self.PARTY_OFFSET - 4]

    def _set_party_count(self, count: int) -> None:
        self.data[self.general_base + self.PARTY_OFFSET - 4] = count

    def get_box_slot(self, box: int, slot: int):
        return self.read_slot(self.data,
                              self.storage_base + self.box_slot_offset(box, slot),
                              self.SIZE_BOXSLOT)

    def set_box_slot(self, box: int, slot: int, entity) -> None:
        start = self.storage_base + self.box_slot_offset(box, slot)
        self.data[start:start + self.SIZE_BOXSLOT] = self._slot_bytes(
            entity, self.SIZE_BOXSLOT)

    def get_party_slot(self, slot: int):
        return self.read_slot(self.data,
                              self.general_base + self.party_offset(slot),
                              self.SIZE_PARTY_SLOT)

    def _write_party_slot(self, slot: int, entity) -> None:
        start = self.general_base + self.party_offset(slot)
        self.data[start:start + self.SIZE_PARTY_SLOT] = self._slot_bytes(
            entity, self.SIZE_PARTY_SLOT)

    # --- trainer -------------------------------------------------------------

    def region(self, name: str) -> tuple[bytearray, int]:
        if name == "trainer":
            return self.data, self.general_base + self.TRAINER_OFFSET
        raise KeyError(f"{self.GAME} has no {name!r} region")

    def _general_u16(self, offset: int) -> int:
        return read_u16(self.data, self.general_base + offset)

    trainer_name = fields.Text("trainer", 0x00, 16)
    tid16 = fields.U16("trainer", 0x10)
    sid16 = fields.U16("trainer", 0x12)
    money = fields.U32("trainer", 0x14)
    trainer_gender = fields.U8("trainer", 0x18)
    language = fields.U8("trainer", 0x19)

    @property
    def play_time(self) -> tuple[int, int, int]:
        base = self.general_base + self.TRAINER_OFFSET
        return (read_u16(self.data, base + 0x22),
                self.data[base + 0x24], self.data[base + 0x25])

    @play_time.setter
    def play_time(self, value: tuple[int, int, int]) -> None:
        base = self.general_base + self.TRAINER_OFFSET
        hours, minutes, seconds = value
        write_u16(self.data, base + 0x22, hours)
        self.data[base + 0x24] = minutes
        self.data[base + 0x25] = seconds

    # --- integrity -----------------------------------------------------------

    def _block_checksum(self, base: int, length: int) -> int:
        return checksums.crc16_ccitt(bytes(self.data[base:base + length - self.FOOTER_SIZE]))

    def _stored_checksum(self, base: int, length: int) -> int:
        return read_u16(self.data, base + length - 2)

    @property
    def checksums_valid(self) -> bool:
        return (self._block_checksum(self.general_base, self.GENERAL_SIZE)
                == self._stored_checksum(self.general_base, self.GENERAL_SIZE)
                and self._block_checksum(self.storage_base, self.STORAGE_SIZE)
                == self._stored_checksum(self.storage_base, self.STORAGE_SIZE))

    def fix_checksums(self) -> None:
        write_u16(self.data, self.general_base + self.GENERAL_SIZE - 2,
                  self._block_checksum(self.general_base, self.GENERAL_SIZE))
        write_u16(self.data, self.storage_base + self.STORAGE_SIZE - 2,
                  self._block_checksum(self.storage_base, self.STORAGE_SIZE))


class SAV4DP(SAV4):
    KEY = "dp"
    GAME = "Diamond/Pearl"
    GENERAL_SIZE = 0xC100
    STORAGE_SIZE = 0x121E0
    STORAGE_START = 0xC100
    TRAINER_OFFSET = 0x64
    PARTY_OFFSET = 0x98
    DAYCARE_OFFSET = 0x141C


class SAV4Pt(SAV4):
    KEY = "pt"
    GAME = "Platinum"
    GENERAL_SIZE = 0xCF2C
    STORAGE_SIZE = 0x121E4
    STORAGE_START = 0xCF2C
    TRAINER_OFFSET = 0x68
    PARTY_OFFSET = 0xA0
    DAYCARE_OFFSET = 0x1654


class SAV4HGSS(SAV4):
    KEY = "hgss"
    GAME = "HeartGold/SoulSilver"
    GENERAL_SIZE = 0xF628
    STORAGE_SIZE = 0x12310
    #: HG/SS leaves a gap between the general and storage blocks.
    STORAGE_START = 0xF628 + 0xD8
    FOOTER_SIZE = 0x10
    TRAINER_OFFSET = 0x64
    PARTY_OFFSET = 0x98
    DAYCARE_OFFSET = 0x15FC
    WALKER_OFFSET = 0xE5E0
    BOX_START = 0
    BOX_STRIDE = 0x1000


# --------------------------------------------------------------------------
# Generation 5
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _block_tables() -> dict:
    return json.loads((DATA_DIR / "save_blocks.json").read_text())


class SAV5(SaveFile):
    GENERATION = 5
    STRING_GENERATION = 5
    ENTITY = PK5
    BOX_COUNT = 24
    BOX_SLOT_COUNT = 30
    SIZE_BOXSLOT = 136
    SIZE_PARTY_SLOT = 220
    MAX_STRING_LENGTH_TRAINER = 7

    BLOCK_TABLE: str = ""
    BOX_BASE = 0x400
    PARTY_BASE = 0x18E00
    #: Block index holding the trainer record.
    TRAINER_BLOCK = 27
    #: Block index holding money and other miscellany.
    MISC_BLOCK = 52
    MISC_MONEY_OFFSET = 0

    def __init__(self, data: bytes | bytearray) -> None:
        super().__init__(data)
        table = _block_tables()[self.BLOCK_TABLE]
        self.blocks = table["blocks"]
        self.main_size = table["size"]

    # --- storage -------------------------------------------------------------

    def _box_offset(self, box: int) -> int:
        # Each box chunk is padded by 0x10 bytes past its 30 slots.
        return self.BOX_BASE + self.SIZE_BOXSLOT * self.BOX_SLOT_COUNT * box + box * 0x10

    def _party_offset(self, slot: int) -> int:
        return self.PARTY_BASE + 8 + self.SIZE_PARTY_SLOT * slot

    @property
    def party_count(self) -> int:
        return self.data[self.PARTY_BASE + 4]

    def _set_party_count(self, count: int) -> None:
        self.data[self.PARTY_BASE + 4] = count

    #: Block holding the six Battle Box slots, each a plain stored record.
    BATTLE_BOX_BLOCK = 49
    #: Block holding the daycare. Each slot is an occupied flag, a party-sized
    #: record, and the experience earned while deposited.
    DAYCARE_BLOCK = 50
    DAYCARE_SLOT_SIZE = 4 + crypto.SIZE_5PARTY + 4

    #: The last Pokemon offered to the GTS, and the last uploaded to the
    #: Global Link. Both are kept party-sized.
    GTS_BLOCK = 46
    GLOBAL_LINK_BLOCK = 35
    #: Black 2 and White 2 store the Pokemon fused into Kyurem here. It exists
    #: nowhere else in the save, so leaving it out loses a legendary.
    FUSED_BLOCK: int | None = None

    EXTRA_REGIONS: ClassVar[tuple[ExtraRegion, ...]] = (
        ExtraRegion("daycare", 2, DAYCARE_SLOT_SIZE, 4, source=DAYCARE_BLOCK),
        ExtraRegion("battle_box", 6, crypto.SIZE_5STORED,
                    source=BATTLE_BOX_BLOCK),
        ExtraRegion("gts", 1, 0, 0, source=GTS_BLOCK),
        ExtraRegion("global_link", 1, 0, 8, source=GLOBAL_LINK_BLOCK),
    )

    def extra_regions(self) -> tuple[ExtraRegion, ...]:
        regions = self.EXTRA_REGIONS
        if self.FUSED_BLOCK is not None:
            regions += (ExtraRegion("fused", 1, 0, 4, source=self.FUSED_BLOCK),)
        return tuple(r for r in regions
                     if r.source is not None and len(self.blocks) > r.source)

    def _extra_base(self, region: ExtraRegion) -> tuple[bytearray, int]:
        assert region.source is not None
        return self.data, self.blocks[region.source]["offset"]

    # --- trainer -------------------------------------------------------------

    @property
    def _trainer_base(self) -> int:
        return self.blocks[self.TRAINER_BLOCK]["offset"]

    def region(self, name: str) -> tuple[bytearray, int]:
        if name == "trainer":
            return self.data, self._trainer_base
        raise KeyError(f"{self.GAME} has no {name!r} region")

    trainer_name = fields.Text("trainer", 0x04, 0x10)
    tid16 = fields.U16("trainer", 0x14)
    sid16 = fields.U16("trainer", 0x16)
    language = fields.U8("trainer", 0x1E)
    version = fields.U8("trainer", 0x1F)
    trainer_gender = fields.U8("trainer", 0x21)

    @property
    def play_time(self) -> tuple[int, int, int]:
        base = self._trainer_base + 0x24
        return read_u16(self.data, base), self.data[base + 2], self.data[base + 3]

    @play_time.setter
    def play_time(self, value: tuple[int, int, int]) -> None:
        base = self._trainer_base + 0x24
        hours, minutes, seconds = value
        write_u16(self.data, base, hours)
        self.data[base + 2] = minutes
        self.data[base + 3] = seconds

    @property
    def money(self) -> int | None:
        """Money lives in a different block from the rest of the trainer record."""
        if len(self.blocks) <= self.MISC_BLOCK:
            return None
        return read_u32(self.data, self.blocks[self.MISC_BLOCK]["offset"]
                        + self.MISC_MONEY_OFFSET)

    @money.setter
    def money(self, value: int) -> None:
        if len(self.blocks) <= self.MISC_BLOCK:
            raise NotImplementedError(f"{self.GAME} has no money block")
        write_u32(self.data, self.blocks[self.MISC_BLOCK]["offset"]
                  + self.MISC_MONEY_OFFSET, value)

    # --- integrity -----------------------------------------------------------

    def _block_checksum(self, block: dict) -> int:
        start = block["offset"]
        return checksums.crc16_ccitt(bytes(self.data[start:start + block["length"]]))

    @property
    def checksums_valid(self) -> bool:
        for block in self.blocks:
            expected = self._block_checksum(block)
            if read_u16(self.data, block["checksum"]) != expected:
                return False
            if read_u16(self.data, block["mirror"]) != expected:
                return False
        return True

    def fix_checksums(self) -> None:
        for block in self.blocks:
            expected = self._block_checksum(block)
            write_u16(self.data, block["checksum"], expected)
            write_u16(self.data, block["mirror"], expected)


class SAV5BW(SAV5):
    KEY = "bw"
    GAME = "Black/White"
    BLOCK_TABLE = "bw"


class SAV5B2W2(SAV5):
    FUSED_BLOCK = 43
    KEY = "b2w2"
    GAME = "Black 2/White 2"
    BLOCK_TABLE = "b2w2"
