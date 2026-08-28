"""DS-era saves: Diamond/Pearl, Platinum, HeartGold/SoulSilver, and Gen5.

Gen4 splits the save into a general block and a storage block, each written
twice into a 0x40000-byte partition; the copy with the higher footer counter is
the live one. Gen5 instead uses a flat table of CRC-checked blocks, each with a
checksum and a mirrored copy of that checksum near the end of the file.
"""

from __future__ import annotations

import json
from functools import lru_cache

from ..binio import read_u16, read_u32, write_u16
from ..data import DATA_DIR
from ..pkm.formats import PK4, PK5
from . import checksums
from .base import SaveFile

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

    def _slot(self, base: int, offset: int, size: int):
        start = base + offset
        raw = bytes(self.data[start:start + size])
        if not self.slot_present(raw):
            return None
        entity = PK4(PK4.decrypt_buffer(raw))
        return entity if entity.species else None

    def get_box_slot(self, box: int, slot: int):
        return self._slot(self.storage_base, self.box_slot_offset(box, slot),
                          self.SIZE_BOXSLOT)

    def set_box_slot(self, box: int, slot: int, entity) -> None:
        start = self.storage_base + self.box_slot_offset(box, slot)
        self.data[start:start + self.SIZE_BOXSLOT] = self._slot_bytes(
            entity, self.SIZE_BOXSLOT)

    def get_party_slot(self, slot: int):
        return self._slot(self.general_base, self.party_offset(slot),
                          self.SIZE_PARTY_SLOT)

    def _write_party_slot(self, slot: int, entity) -> None:
        start = self.general_base + self.party_offset(slot)
        self.data[start:start + self.SIZE_PARTY_SLOT] = self._slot_bytes(
            entity, self.SIZE_PARTY_SLOT)

    # --- trainer -------------------------------------------------------------

    def _general_u16(self, offset: int) -> int:
        return read_u16(self.data, self.general_base + offset)

    @property
    def trainer_name(self) -> str:
        start = self.general_base + self.TRAINER_OFFSET
        return self.decode_string(bytes(self.data[start:start + 16]))

    @property
    def tid16(self) -> int:
        return self._general_u16(self.TRAINER_OFFSET + 0x10)

    @property
    def sid16(self) -> int:
        return self._general_u16(self.TRAINER_OFFSET + 0x12)

    @property
    def money(self) -> int:
        return read_u32(self.data, self.general_base + self.TRAINER_OFFSET + 0x14)

    @property
    def trainer_gender(self) -> int:
        return self.data[self.general_base + self.TRAINER_OFFSET + 0x18]

    @property
    def language(self) -> int:
        return self.data[self.general_base + self.TRAINER_OFFSET + 0x19]

    @property
    def play_time(self) -> tuple[int, int, int]:
        base = self.general_base + self.TRAINER_OFFSET
        return (read_u16(self.data, base + 0x22),
                self.data[base + 0x24], self.data[base + 0x25])

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


class SAV4Pt(SAV4):
    KEY = "pt"
    GAME = "Platinum"
    GENERAL_SIZE = 0xCF2C
    STORAGE_SIZE = 0x121E4
    STORAGE_START = 0xCF2C
    TRAINER_OFFSET = 0x68
    PARTY_OFFSET = 0xA0


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

    # --- trainer -------------------------------------------------------------

    @property
    def _trainer_base(self) -> int:
        return self.blocks[self.TRAINER_BLOCK]["offset"]

    @property
    def trainer_name(self) -> str:
        start = self._trainer_base + 4
        return self.decode_string(bytes(self.data[start:start + 0x10]))

    @property
    def tid16(self) -> int:
        return read_u16(self.data, self._trainer_base + 0x14)

    @property
    def sid16(self) -> int:
        return read_u16(self.data, self._trainer_base + 0x16)

    @property
    def language(self) -> int:
        return self.data[self._trainer_base + 0x1E]

    @property
    def version(self) -> int:
        return self.data[self._trainer_base + 0x1F]

    @property
    def trainer_gender(self) -> int:
        return self.data[self._trainer_base + 0x21]

    @property
    def play_time(self) -> tuple[int, int, int]:
        base = self._trainer_base + 0x24
        return read_u16(self.data, base), self.data[base + 2], self.data[base + 3]

    @property
    def money(self) -> int | None:
        if len(self.blocks) <= self.MISC_BLOCK:
            return None
        return read_u32(self.data, self.blocks[self.MISC_BLOCK]["offset"]
                        + self.MISC_MONEY_OFFSET)

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
    KEY = "b2w2"
    GAME = "Black 2/White 2"
    BLOCK_TABLE = "b2w2"
