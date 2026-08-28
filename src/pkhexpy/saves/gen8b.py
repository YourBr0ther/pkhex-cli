"""Brilliant Diamond and Shining Pearl saves.

Unlike the other Switch games, BDSP is not block-addressed. It is one flat
buffer with fixed offsets, signed by an MD5 hash stored partway through the
file rather than at the end.
"""

from __future__ import annotations

import hashlib

from ..binio import read_u16, read_u32, write_u16, write_u32
from ..pkm.formats import PB8
from .base import SaveFile

#: The four shipped save sizes, one per game revision.
SIZES = (0xE9828, 0xEDC20, 0xEED8C, 0xEF0A4)

#: The hash sits at a fixed offset from the start, not from the end, so it
#: stays put as later revisions appended data.
HASH_LENGTH = 16
HASH_OFFSET = 0xE9828 - HASH_LENGTH

#: Revision marker at offset 0, one value per save size. These are PKHeX's
#: Gem8Version values: 1.0, the November 2021 patch, and the two 2022 patches.
VERSION_BY_SIZE = {0xE9828: 0x25, 0xEDC20: 0x2C, 0xEED8C: 0x32, 0xEF0A4: 0x34}


def is_bdsp(data: bytes) -> bool:
    """BDSP writes its revision at offset 0 and an MD5 partway through."""
    if len(data) not in SIZES:
        return False
    if len(data) < HASH_OFFSET + HASH_LENGTH:
        return False
    return read_u32(data, 0) == VERSION_BY_SIZE[len(data)]


class SAV8BS(SaveFile):
    KEY = "bdsp"
    GAME = "Brilliant Diamond/Shining Pearl"
    GENERATION = 8
    STRING_GENERATION = 8
    ENTITY = PB8
    BOX_COUNT = 40
    BOX_SLOT_COUNT = 30
    #: Boxes hold party-sized records, as Sword/Shield do.
    SIZE_BOXSLOT = 0x158
    SIZE_PARTY_SLOT = 0x158

    PARTY_BASE = 0x14098
    PARTY_COUNT_OFFSET = 6 * 0x158        # count sits just past the six slots
    BOX_BASE = 0x14EF4
    BOX_LAYOUT_BASE = 0x148AA
    BOX_NAME_LENGTH = 0x22
    CONFIG_BASE = 0x79B74
    STATUS_BASE = 0x79BB4
    PLAY_TIME_BASE = 0x79C04

    # --- storage -------------------------------------------------------------

    def _box_offset(self, box: int) -> int:
        return self.BOX_BASE + self.SIZE_BOXSLOT * self.BOX_SLOT_COUNT * box

    def _party_offset(self, slot: int) -> int:
        return self.PARTY_BASE + self.SIZE_PARTY_SLOT * slot

    @property
    def party_count(self) -> int:
        return self.data[self.PARTY_BASE + self.PARTY_COUNT_OFFSET]

    def _set_party_count(self, count: int) -> None:
        self.data[self.PARTY_BASE + self.PARTY_COUNT_OFFSET] = count

    def box_name(self, box: int) -> str | None:
        start = self.BOX_LAYOUT_BASE + box * self.BOX_NAME_LENGTH
        name = self.decode_string(bytes(self.data[start:start + self.BOX_NAME_LENGTH]))
        return name or None

    # --- trainer -------------------------------------------------------------

    @property
    def trainer_name(self) -> str:
        return self.decode_string(bytes(self.data[self.STATUS_BASE:self.STATUS_BASE + 0x1A]))

    @trainer_name.setter
    def trainer_name(self, value: str) -> None:
        start = self.STATUS_BASE
        self.data[start:start + 0x1A] = self.encode_trainer_name(0x1A, value)

    @property
    def tid16(self) -> int:
        return read_u16(self.data, self.STATUS_BASE + 0x1C)

    @tid16.setter
    def tid16(self, value: int) -> None:
        write_u16(self.data, self.STATUS_BASE + 0x1C, value)

    @property
    def sid16(self) -> int:
        return read_u16(self.data, self.STATUS_BASE + 0x1E)

    @sid16.setter
    def sid16(self, value: int) -> None:
        write_u16(self.data, self.STATUS_BASE + 0x1E, value)

    @property
    def money(self) -> int:
        return read_u32(self.data, self.STATUS_BASE + 0x20)

    @money.setter
    def money(self, value: int) -> None:
        write_u32(self.data, self.STATUS_BASE + 0x20, value)

    @property
    def trainer_gender(self) -> int:
        """Stored as a "is male" flag rather than the usual 0/1 gender byte."""
        return 0 if self.data[self.STATUS_BASE + 0x24] == 1 else 1

    @trainer_gender.setter
    def trainer_gender(self, value: int) -> None:
        self.data[self.STATUS_BASE + 0x24] = 1 if value == 0 else 0

    @property
    def language(self) -> int:
        return read_u32(self.data, self.CONFIG_BASE + 4)

    @property
    def play_time(self) -> tuple[int, int, int]:
        base = self.PLAY_TIME_BASE
        return read_u16(self.data, base), self.data[base + 2], self.data[base + 3]

    @play_time.setter
    def play_time(self, value: tuple[int, int, int]) -> None:
        base = self.PLAY_TIME_BASE
        hours, minutes, seconds = value
        write_u16(self.data, base, hours)
        self.data[base + 2] = minutes
        self.data[base + 3] = seconds

    @property
    def version(self) -> int:
        return read_u32(self.data, 0)

    # --- integrity -----------------------------------------------------------

    def _computed_hash(self) -> bytes:
        """MD5 over the whole file with the hash region zeroed first."""
        scratch = bytearray(self.data)
        scratch[HASH_OFFSET:HASH_OFFSET + HASH_LENGTH] = bytes(HASH_LENGTH)
        return hashlib.md5(bytes(scratch)).digest()

    @property
    def checksums_valid(self) -> bool:
        stored = bytes(self.data[HASH_OFFSET:HASH_OFFSET + HASH_LENGTH])
        return stored == self._computed_hash()

    def fix_checksums(self) -> None:
        self.data[HASH_OFFSET:HASH_OFFSET + HASH_LENGTH] = self._computed_hash()
