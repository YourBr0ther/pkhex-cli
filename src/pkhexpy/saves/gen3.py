"""Generation 3 saves: Ruby/Sapphire, Emerald, FireRed/LeafGreen.

The file holds two rotating copies of the save, each split into 14 sectors of
0x1000 bytes. A sector's trailing footer says which logical chunk it holds, so
reading means reassembling three buffers - small, large, and storage - from
whichever copy saved most recently.
"""

from __future__ import annotations


from .. import crypto
from ..binio import read_i16, read_u16, read_u32, write_u16, write_u32
from ..pkm.formats import PK3
from . import checksums
from .base import ExtraRegion, SaveFile

SIZE_SECTOR = 0x1000
SIZE_SECTOR_USED = 0xF80
COUNT_MAIN = 14
COUNT_EXTRA = 4
SIZE_MAIN = COUNT_MAIN * SIZE_SECTOR
SIZE_RAW = 0x20000
SIZE_RAW_HALF = 0x10000
EXTRA_SECTOR_START = 0x1C000

#: Offsets within a sector's 12-byte footer.
FOOTER_ID = 0xFF4
FOOTER_CHECKSUM = 0xFF6
FOOTER_SIGNATURE = 0xFF8
FOOTER_COUNTER = 0xFFC

SMALL_SECTORS = 1
LARGE_SECTORS = 4
STORAGE_SECTORS = 9


def all_main_sectors_present(data: bytes, slot: int) -> tuple[bool, int]:
    """Whether every one of the 14 sector ids appears once in this copy."""
    start = SIZE_MAIN * slot
    if start + SIZE_MAIN > len(data):
        return False, 0
    seen = 0
    sector0 = 0
    for offset in range(start, start + SIZE_MAIN, SIZE_SECTOR):
        sector_id = read_i16(data, offset + FOOTER_ID)
        if not 0 <= sector_id < COUNT_MAIN:
            return False, 0
        seen |= 1 << sector_id
        if sector_id == 0:
            sector0 = offset
    return seen == 0x3FFF, sector0


def is_gen3(data: bytes) -> bool:
    # A half-size file holds only the first copy; emulators with a misconfigured
    # FLASH size produce these and the games still read them.
    if len(data) not in (SIZE_RAW, SIZE_RAW_HALF):
        return False
    return any(all_main_sectors_present(data, slot)[0]
               for slot in range(len(data) // SIZE_RAW_HALF))


def _active_slot(data: bytes) -> int:
    """Pick the copy that was written most recently."""
    if len(data) == SIZE_RAW_HALF:
        return 0
    valid0, sector0_a = all_main_sectors_present(data, 0)
    valid1, sector0_b = all_main_sectors_present(data, 1)
    if not valid0:
        return 1 if valid1 else 0
    if not valid1:
        return 0
    # Both copies are intact; the higher save counter wins, with 0 treated as
    # uninitialized and wraparound handled the way the games do.
    count_a = read_u32(data, sector0_a + FOOTER_COUNTER)
    count_b = read_u32(data, sector0_b + FOOTER_COUNTER)
    if count_a == 0xFFFFFFFF and count_b == 0:
        return 1
    if count_b == 0xFFFFFFFF and count_a == 0:
        return 0
    return 0 if count_a > count_b else 1


def detect_version(small: bytes) -> str:
    """Tell RS, Emerald, and FR/LG apart by what sits at 0xAC in the small block."""
    value = read_u32(small, 0xAC)
    if value == 1:
        return "frlg"          # fixed value in FR/LG
    if value == 0:
        return "rs"            # no battle tower record
    # RS data stops at 0x890; anything past it means Emerald.
    return "e" if any(small[0x890:0xF2C]) else "rs"


class SAV3(SaveFile):
    """Common structure for the GBA mainline saves."""

    GENERATION = 3
    STRING_GENERATION = 3
    ENTITY = PK3
    BOX_COUNT = 14
    BOX_SLOT_COUNT = 30
    SIZE_BOXSLOT = 80
    SIZE_PARTY_SLOT = 100
    MAX_STRING_LENGTH_TRAINER = 7

    #: Offset of the party inside the large buffer, per game.
    #: Daycare, in the large block. Emerald and FireRed pad each slot with the
    #: held mail and the experience earned while deposited.
    DAYCARE_OFFSET: int | None = None
    DAYCARE_SLOT_SIZE: int = crypto.SIZE_3STORED + 0x3C
    def extra_regions(self) -> tuple[ExtraRegion, ...]:
        if self.DAYCARE_OFFSET is None:
            return ()
        return (ExtraRegion("daycare", 2, self.DAYCARE_SLOT_SIZE,
                            self.DAYCARE_OFFSET),)

    def _extra_base(self, region: ExtraRegion) -> tuple[bytearray, int]:
        return self.large, 0

    PARTY_COUNT_OFFSET: int = 0x234
    PARTY_OFFSET: int = 0x238
    MONEY_OFFSET: int = 0x0490
    #: Emerald and FR/LG XOR money and coins with a per-save key. None means the
    #: value is stored in the clear, as Ruby/Sapphire do.
    SECURITY_KEY_OFFSET: int | None = None

    def __init__(self, data: bytes | bytearray) -> None:
        super().__init__(data)
        self.active_slot = _active_slot(bytes(self.data))
        self.small = bytearray(SMALL_SECTORS * SIZE_SECTOR_USED)
        self.large = bytearray(LARGE_SECTORS * SIZE_SECTOR_USED)
        self.storage = bytearray(STORAGE_SECTORS * SIZE_SECTOR_USED)
        self._read_sectors(self.active_slot)
        #: Japanese saves leave the last two OT-name bytes untouched, so they read 0.
        self.is_japanese = read_i16(self.small, 0x6) == 0

    # --- sector plumbing -----------------------------------------------------

    def _chunk(self, sector_id: int) -> tuple[bytearray, int]:
        if sector_id >= 5:
            return self.storage, (sector_id - 5) * SIZE_SECTOR_USED
        if sector_id >= 1:
            return self.large, (sector_id - 1) * SIZE_SECTOR_USED
        return self.small, 0

    def _read_sectors(self, slot: int) -> None:
        start = slot * SIZE_MAIN
        for offset in range(start, start + SIZE_MAIN, SIZE_SECTOR):
            sector_id = read_i16(self.data, offset + FOOTER_ID)
            buffer, at = self._chunk(sector_id)
            buffer[at:at + SIZE_SECTOR_USED] = self.data[offset:offset + SIZE_SECTOR_USED]

    def _write_sectors(self, slot: int) -> None:
        start = slot * SIZE_MAIN
        for offset in range(start, start + SIZE_MAIN, SIZE_SECTOR):
            sector_id = read_i16(self.data, offset + FOOTER_ID)
            buffer, at = self._chunk(sector_id)
            self.data[offset:offset + SIZE_SECTOR_USED] = buffer[at:at + SIZE_SECTOR_USED]

    # --- storage -------------------------------------------------------------

    def _box_offset(self, box: int) -> int:
        # The storage buffer opens with a 4-byte current-box index.
        return 4 + self.SIZE_BOXSLOT * self.BOX_SLOT_COUNT * box

    def _party_offset(self, slot: int) -> int:
        return self.PARTY_OFFSET + self.SIZE_PARTY_SLOT * slot

    @property
    def party_count(self) -> int:
        return self.large[self.PARTY_COUNT_OFFSET]

    def _set_party_count(self, count: int) -> None:
        self.large[self.PARTY_COUNT_OFFSET] = count

    def get_box_slot(self, box: int, slot: int):
        return self.read_slot(self.storage, self.box_slot_offset(box, slot),
                              self.SIZE_BOXSLOT)

    def set_box_slot(self, box: int, slot: int, entity) -> None:
        offset = self.box_slot_offset(box, slot)
        self.storage[offset:offset + self.SIZE_BOXSLOT] = self._slot_bytes(
            entity, self.SIZE_BOXSLOT)

    def get_party_slot(self, slot: int):
        return self.read_slot(self.large, self.party_offset(slot),
                              self.SIZE_PARTY_SLOT)

    def _write_party_slot(self, slot: int, entity) -> None:
        offset = self.party_offset(slot)
        self.large[offset:offset + self.SIZE_PARTY_SLOT] = self._slot_bytes(
            entity, self.SIZE_PARTY_SLOT)

    @property
    def current_box(self) -> int:
        return self.storage[0]

    # --- trainer -------------------------------------------------------------

    @property
    def trainer_name(self) -> str:
        return self.decode_string(bytes(self.small[0:8]))

    @trainer_name.setter
    def trainer_name(self, value: str) -> None:
        self.small[0:8] = self.encode_trainer_name(8, value)

    @property
    def trainer_gender(self) -> int:
        return self.small[8]

    @trainer_gender.setter
    def trainer_gender(self, value: int) -> None:
        self.small[8] = value

    @property
    def tid16(self) -> int:
        return read_u16(self.small, 0x0A)

    @tid16.setter
    def tid16(self, value: int) -> None:
        write_u16(self.small, 0x0A, value)

    @property
    def sid16(self) -> int:
        return read_u16(self.small, 0x0C)

    @sid16.setter
    def sid16(self, value: int) -> None:
        write_u16(self.small, 0x0C, value)

    @property
    def play_time(self) -> tuple[int, int, int]:
        return read_u16(self.small, 0x0E), self.small[0x10], self.small[0x11]

    @play_time.setter
    def play_time(self, value: tuple[int, int, int]) -> None:
        hours, minutes, seconds = value
        write_u16(self.small, 0x0E, hours)
        self.small[0x10] = minutes
        self.small[0x11] = seconds

    @property
    def security_key(self) -> int:
        if self.SECURITY_KEY_OFFSET is None:
            return 0
        return read_u32(self.small, self.SECURITY_KEY_OFFSET)

    @property
    def money(self) -> int:
        return read_u32(self.large, self.MONEY_OFFSET) ^ self.security_key

    @money.setter
    def money(self, value: int) -> None:
        write_u32(self.large, self.MONEY_OFFSET, value ^ self.security_key)

    @property
    def language(self) -> int:
        return 1 if self.is_japanese else 2

    # --- integrity -----------------------------------------------------------

    @staticmethod
    def _sector_uninitialized(sector: bytes) -> bool:
        return all(b in (0, 0xFF) for b in sector)

    @property
    def checksums_valid(self) -> bool:
        """Whether the sectors holding the trainer, party, and boxes check out."""
        start = self.active_slot * SIZE_MAIN
        for offset in range(start, start + SIZE_MAIN, SIZE_SECTOR):
            body = bytes(self.data[offset:offset + SIZE_SECTOR_USED])
            if checksums.checksum32(body) != read_u16(self.data, offset + FOOTER_CHECKSUM):
                return False
        return True

    @property
    def extra_sectors_valid(self) -> bool:
        """Whether the Hall of Fame region past the two save copies checks out.

        Real saves are sometimes inconsistent here while the main data is
        perfectly fine, so this is reported separately and never rewritten.
        """
        if len(self.data) < SIZE_RAW:
            return True  # a half-size file has no extra sectors
        for i in range(COUNT_EXTRA):
            offset = EXTRA_SECTOR_START + i * SIZE_SECTOR
            sector = bytes(self.data[offset:offset + SIZE_SECTOR])
            if self._sector_uninitialized(sector):
                continue
            stored = read_u16(self.data, offset + FOOTER_ID)
            if checksums.checksum32(sector[:SIZE_SECTOR_USED]) != stored:
                return False
        return True

    def fix_checksums(self) -> None:
        """Recompute the main sectors only.

        The Hall of Fame region is never read or written here, so rewriting its
        checksums would change bytes the caller did not touch.
        """
        self._write_sectors(self.active_slot)
        start = self.active_slot * SIZE_MAIN
        for offset in range(start, start + SIZE_MAIN, SIZE_SECTOR):
            body = bytes(self.data[offset:offset + SIZE_SECTOR_USED])
            write_u16(self.data, offset + FOOTER_CHECKSUM, checksums.checksum32(body))


class SAV3RS(SAV3):
    KEY = "rs"
    GAME = "Ruby/Sapphire"
    #: Ruby and Sapphire keep daycare mail elsewhere, so a slot is just the record.
    DAYCARE_OFFSET = 0x2F9C
    DAYCARE_SLOT_SIZE = crypto.SIZE_3STORED


class SAV3E(SAV3):
    KEY = "e"
    GAME = "Emerald"
    SECURITY_KEY_OFFSET = 0x0AC
    DAYCARE_OFFSET = 0x3030


class SAV3FRLG(SAV3):
    KEY = "frlg"
    GAME = "FireRed/LeafGreen"
    PARTY_COUNT_OFFSET = 0x034
    PARTY_OFFSET = 0x038
    MONEY_OFFSET = 0x0290
    SECURITY_KEY_OFFSET = 0xF20
    DAYCARE_OFFSET = 0x2F80


BY_VERSION = {"rs": SAV3RS, "e": SAV3E, "frlg": SAV3FRLG}
