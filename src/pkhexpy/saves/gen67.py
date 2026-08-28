"""3DS-era saves: X/Y, Omega Ruby/Alpha Sapphire, Sun/Moon, Ultra Sun/Moon, Let's Go.

These files end with a "BEEF" metadata chunk listing every block's length, id,
and checksum. Block offsets are fixed per game, so the tables in
``data/save_blocks.json`` are enough to locate the party, the boxes, and the
trainer record.
"""

from __future__ import annotations

import json
from functools import lru_cache

from .. import crypto
from ..binio import read_u16, read_u32, write_u16, write_u32
from ..data import DATA_DIR
from ..pkm.formats import PB7, PK6, PK7
from . import checksums
from .base import ExtraRegion, SaveFile

#: Offset of the block-info table within the metadata chunk.
BLOCK_TABLE_OFFSET = 0x14
#: Each entry is {u32 length, u16 id, u16 checksum}.
BLOCK_ENTRY_SIZE = 8
BEEF_MAGIC = 0x42454546


@lru_cache(maxsize=1)
def _block_tables() -> dict:
    return json.loads((DATA_DIR / "save_blocks.json").read_text())


def has_beef_footer(data: bytes) -> bool:
    """Every Gen6/7 save marks its metadata chunk with "BEEF"."""
    return len(data) > 0x1F0 and read_u32(data, len(data) - 0x1F0) == BEEF_MAGIC


class SAV67(SaveFile):
    """Common structure for the BEEF-footer saves."""

    #: Key into the packaged block tables.
    BLOCK_TABLE: str = ""
    #: Block index holding the trainer record.
    STATUS_BLOCK: int = 0
    #: Offset of the trainer name inside that block.
    STATUS_OT_OFFSET: int = 0x48
    STATUS_LANGUAGE_OFFSET: int = 0x2D
    #: Block index holding play time, and the one holding money.
    PLAYTIME_BLOCK: int = 0
    MISC_BLOCK: int | None = None
    MISC_MONEY_OFFSET: int = 0x4
    #: Block indices for the party and box areas; None means a fixed offset.
    PARTY_BLOCK: int | None = None
    BOX_BLOCK: int | None = None
    PARTY_FIXED_OFFSET: int | None = None
    BOX_FIXED_OFFSET: int | None = None
    #: Party count is stored just past the party block for Gen6/7.
    PARTY_COUNT_OFFSET: int = 6 * 0x104

    #: Block holding the box names, and the bytes each name occupies.
    BOX_LAYOUT_BLOCK: int | None = None
    BOX_NAME_LENGTH: int = 0x22

    #: Block holding the MemeCrypto signature. The game signs it after computing
    #: checksums, so its stored checksum is deliberately stale and recomputing it
    #: would corrupt a file that is otherwise byte-identical.
    SIGNATURE_BLOCK: int | None = None

    def __init__(self, data: bytes | bytearray) -> None:
        super().__init__(data)
        table = _block_tables()[self.BLOCK_TABLE]
        self.blocks = table["blocks"]
        self.metadata_offset = table["metadata_offset"]
        self.checksum_name = table["checksum"]

    # --- block plumbing ------------------------------------------------------

    #: Blocks holding Pokemon outside the party and boxes. Gen6 and Gen7 lay
    #: out the daycare differently: Gen6 prefixes each slot with an occupied
    #: flag and the experience earned, Gen7 with a single flag byte.
    DAYCARE_BLOCK: int | None = None
    DAYCARE_SLOT_COUNT: int = 2
    DAYCARE_SLOT_SIZE: int = 4 + crypto.SIZE_6STORED + 4
    DAYCARE_RECORD_OFFSET: int = 8
    BATTLE_BOX_BLOCK: int | None = None
    #: Kyurem's other half, and in Ultra Sun/Moon the two Necrozma fusions.
    FUSED_BLOCK: int | None = None
    FUSED_COUNT: int = 1
    FUSED_PARTY_SIZED: bool = False

    def extra_regions(self) -> tuple[ExtraRegion, ...]:
        regions: list[ExtraRegion] = []
        if self.DAYCARE_BLOCK is not None:
            regions.append(ExtraRegion(
                "daycare", self.DAYCARE_SLOT_COUNT, self.DAYCARE_SLOT_SIZE,
                self.DAYCARE_RECORD_OFFSET, size=crypto.SIZE_6STORED,
                source=self.DAYCARE_BLOCK))
        if self.FUSED_BLOCK is not None:
            # The stride is the party-sized struct, but only the stored part
            # of each is a record.
            stride = (crypto.SIZE_6PARTY if self.FUSED_PARTY_SIZED
                      else crypto.SIZE_6STORED)
            regions.append(ExtraRegion(
                "fused", self.FUSED_COUNT, stride, party_format=True,
                size=crypto.SIZE_6STORED, source=self.FUSED_BLOCK))
        if self.BATTLE_BOX_BLOCK is not None:
            regions.append(ExtraRegion(
                "battle_box", 6, crypto.SIZE_6STORED,
                size=crypto.SIZE_6STORED, source=self.BATTLE_BOX_BLOCK))
        return tuple(regions)

    def _extra_base(self, region: ExtraRegion) -> tuple[bytearray, int]:
        assert region.source is not None
        return self.data, self.block_offset(region.source)

    def block_offset(self, index: int) -> int:
        return self.blocks[index]["offset"]

    def block_length(self, index: int) -> int:
        return self.blocks[index]["length"]

    def block_bytes(self, index: int) -> bytes:
        offset = self.block_offset(index)
        return bytes(self.data[offset:offset + self.block_length(index)])

    def _checksum_offset(self, index: int) -> int:
        block_id = self.blocks[index]["id"]
        return self.metadata_offset + BLOCK_TABLE_OFFSET + block_id * BLOCK_ENTRY_SIZE + 6

    def _block_checksum(self, index: int) -> int:
        return checksums.ALGORITHMS[self.checksum_name](self.block_bytes(index))

    def _checked_blocks(self) -> range | list[int]:
        return [i for i in range(len(self.blocks)) if i != self.SIGNATURE_BLOCK]

    @property
    def checksums_valid(self) -> bool:
        return not self.invalid_blocks()

    def invalid_blocks(self) -> list[int]:
        return [i for i in self._checked_blocks()
                if read_u16(self.data, self._checksum_offset(i)) != self._block_checksum(i)]

    def fix_checksums(self) -> None:
        for i in self._checked_blocks():
            write_u16(self.data, self._checksum_offset(i), self._block_checksum(i))

    # --- storage -------------------------------------------------------------

    @property
    def _party_base(self) -> int:
        if self.PARTY_FIXED_OFFSET is not None:
            return self.PARTY_FIXED_OFFSET
        return self.block_offset(self.PARTY_BLOCK)

    @property
    def _box_base(self) -> int:
        if self.BOX_FIXED_OFFSET is not None:
            return self.BOX_FIXED_OFFSET
        return self.block_offset(self.BOX_BLOCK)

    def _party_offset(self, slot: int) -> int:
        return self._party_base + self.SIZE_PARTY_SLOT * slot

    def _box_offset(self, box: int) -> int:
        return self._box_base + self.SIZE_BOXSLOT * self.BOX_SLOT_COUNT * box

    @property
    def party_count(self) -> int:
        return self.data[self._party_base + self.PARTY_COUNT_OFFSET]

    def _set_party_count(self, count: int) -> None:
        self.data[self._party_base + self.PARTY_COUNT_OFFSET] = count

    def box_name(self, box: int) -> str | None:
        if self.BOX_LAYOUT_BLOCK is None:
            return None
        start = self.block_offset(self.BOX_LAYOUT_BLOCK) + box * self.BOX_NAME_LENGTH
        name = self.decode_string(bytes(self.data[start:start + self.BOX_NAME_LENGTH]))
        return name or None

    # --- trainer -------------------------------------------------------------

    @property
    def _status_base(self) -> int:
        return self.block_offset(self.STATUS_BLOCK)

    @property
    def trainer_name(self) -> str:
        start = self._status_base + self.STATUS_OT_OFFSET
        return self.decode_string(bytes(self.data[start:start + 0x1A]))

    @trainer_name.setter
    def trainer_name(self, value: str) -> None:
        start = self._status_base + self.STATUS_OT_OFFSET
        self.data[start:start + 0x1A] = self.encode_trainer_name(0x1A, value)

    @property
    def tid16(self) -> int:
        return read_u16(self.data, self._status_base)

    @tid16.setter
    def tid16(self, value: int) -> None:
        write_u16(self.data, self._status_base, value)

    @property
    def sid16(self) -> int:
        return read_u16(self.data, self._status_base + 2)

    @sid16.setter
    def sid16(self, value: int) -> None:
        write_u16(self.data, self._status_base + 2, value)

    @property
    def version(self) -> int:
        return self.data[self._status_base + 4]

    @property
    def trainer_gender(self) -> int:
        return self.data[self._status_base + 5]

    @trainer_gender.setter
    def trainer_gender(self, value: int) -> None:
        self.data[self._status_base + 5] = value

    @property
    def language(self) -> int:
        return self.data[self._status_base + self.STATUS_LANGUAGE_OFFSET]

    @property
    def play_time(self) -> tuple[int, int, int]:
        base = self.block_offset(self.PLAYTIME_BLOCK)
        return read_u16(self.data, base), self.data[base + 2], self.data[base + 3]

    @play_time.setter
    def play_time(self, value: tuple[int, int, int]) -> None:
        base = self.block_offset(self.PLAYTIME_BLOCK)
        hours, minutes, seconds = value
        write_u16(self.data, base, hours)
        self.data[base + 2] = minutes
        self.data[base + 3] = seconds

    @property
    def money(self) -> int | None:
        if self.MISC_BLOCK is None:
            return None
        return read_u32(self.data, self.block_offset(self.MISC_BLOCK) + self.MISC_MONEY_OFFSET)

    @money.setter
    def money(self, value: int) -> None:
        if self.MISC_BLOCK is None:
            raise NotImplementedError(f"{self.GAME} has no money block")
        write_u32(self.data,
                  self.block_offset(self.MISC_BLOCK) + self.MISC_MONEY_OFFSET, value)


class SAV6XY(SAV67):
    KEY = "xy"
    GAME = "X/Y"
    GENERATION = 6
    STRING_GENERATION = 6
    ENTITY = PK6
    BOX_COUNT = 31
    SIZE_BOXSLOT = 0xE8
    SIZE_PARTY_SLOT = 0x104
    BLOCK_TABLE = "xy"
    STATUS_BLOCK = 17
    PLAYTIME_BLOCK = 6
    MISC_BLOCK = 11
    MISC_MONEY_OFFSET = 0x8
    BOX_LAYOUT_BLOCK = 12
    BATTLE_BOX_BLOCK = 13
    FUSED_BLOCK = 22
    DAYCARE_BLOCK = 38
    PARTY_FIXED_OFFSET = 0x14200
    BOX_FIXED_OFFSET = 0x22600


class SAV6AO(SAV67):
    KEY = "ao"
    GAME = "Omega Ruby/Alpha Sapphire"
    GENERATION = 6
    STRING_GENERATION = 6
    ENTITY = PK6
    BOX_COUNT = 31
    SIZE_BOXSLOT = 0xE8
    SIZE_PARTY_SLOT = 0x104
    BLOCK_TABLE = "ao"
    STATUS_BLOCK = 17
    PLAYTIME_BLOCK = 6
    MISC_BLOCK = 11
    MISC_MONEY_OFFSET = 0x8
    BOX_LAYOUT_BLOCK = 12
    BATTLE_BOX_BLOCK = 13
    FUSED_BLOCK = 22
    DAYCARE_BLOCK = 38
    PARTY_FIXED_OFFSET = 0x14200
    BOX_FIXED_OFFSET = 0x33000


class SAV7SM(SAV67):
    KEY = "sm"
    GAME = "Sun/Moon"
    GENERATION = 7
    STRING_GENERATION = 7
    ENTITY = PK7
    BOX_COUNT = 32
    SIZE_BOXSLOT = 0xE8
    SIZE_PARTY_SLOT = 0x104
    BLOCK_TABLE = "sm"
    STATUS_BLOCK = 3
    STATUS_OT_OFFSET = 0x38
    STATUS_LANGUAGE_OFFSET = 0x35
    PLAYTIME_BLOCK = 16
    MISC_BLOCK = 9
    PARTY_BLOCK = 4
    BOX_BLOCK = 14
    BOX_LAYOUT_BLOCK = 13
    SIGNATURE_BLOCK = 36
    # Gen7 dropped the per-slot experience counter, leaving one flag byte.
    DAYCARE_BLOCK = 33
    DAYCARE_SLOT_SIZE = crypto.SIZE_6STORED + 1
    DAYCARE_RECORD_OFFSET = 1
    FUSED_BLOCK = 8
    FUSED_PARTY_SIZED = True


class SAV7USUM(SAV7SM):
    KEY = "usum"
    GAME = "Ultra Sun/Ultra Moon"
    BLOCK_TABLE = "usum"
    #: Kyurem, then Necrozma fused with Solgaleo and with Lunala.
    FUSED_COUNT = 3


class SAV7b(SAV67):
    """Let's Go stores its 1000 slots as 40 boxes of 25, all party-sized."""

    KEY = "gg"
    GAME = "Let's Go Pikachu/Eevee"
    GENERATION = 7
    STRING_GENERATION = 7
    ENTITY = PB7
    BOX_COUNT = 40
    BOX_SLOT_COUNT = 25
    SIZE_BOXSLOT = 0x104
    #: One Pokemon left with the daycare lady, eight bytes into its block.
    DAYCARE_BLOCK = 13
    DAYCARE_SLOT_COUNT = 1
    DAYCARE_SLOT_SIZE = 0
    DAYCARE_RECORD_OFFSET = 8
    SIZE_PARTY_SLOT = 0x104
    BLOCK_TABLE = "gg"
    STATUS_BLOCK = 2
    STATUS_OT_OFFSET = 0x38
    STATUS_LANGUAGE_OFFSET = 0x35
    PLAYTIME_BLOCK = 10
    MISC_BLOCK = 5
    PARTY_BLOCK = 9
    BOX_BLOCK = 9
    #: Header block holding the party pointers, the starter, and the total count.
    POKE_LIST_HEADER_BLOCK = 8
    #: Pointer values at or above this mean the party slot is empty.
    MAX_STORAGE_SLOTS = 1000

    def _party_pointer(self, slot: int) -> int:
        """Let's Go keeps the party as six indices into the 1000-slot box list."""
        base = self.block_offset(self.POKE_LIST_HEADER_BLOCK)
        return read_u16(self.data, base + slot * 2)

    @property
    def party_count(self) -> int:
        return sum(1 for slot in range(6)
                   if self._party_pointer(slot) < self.MAX_STORAGE_SLOTS)

    def _set_party_count(self, count: int) -> None:
        # The party is a list of pointers into box storage, not slots of its
        # own, so resizing it means rewriting those pointers. Shifting the
        # entities would write Pokemon into box slots the pointers still name.
        raise NotImplementedError(
            "Let's Go stores its party as pointers into the box list; "
            "adding or removing a party member is not supported")

    @property
    def stored_count(self) -> int:
        """Total Pokemon in storage, as the header records it."""
        base = self.block_offset(self.POKE_LIST_HEADER_BLOCK)
        return read_u16(self.data, base + 7 * 2)

    def _party_offset(self, slot: int) -> int:
        pointer = self._party_pointer(slot)
        if pointer >= self.MAX_STORAGE_SLOTS:
            raise IndexError(f"party slot {slot} is empty")
        return self._box_base + pointer * self.SIZE_BOXSLOT

    def get_party_slot(self, slot: int):
        if self._party_pointer(slot) >= self.MAX_STORAGE_SLOTS:
            return None
        return super().get_party_slot(slot)

    def iter_party(self):
        """Yield the party in slot order, skipping empty pointers."""
        for slot in range(6):
            entity = self.get_party_slot(slot)
            if entity is not None:
                yield slot, entity
