"""Game Boy saves: Red/Blue/Yellow and Gold/Silver/Crystal.

Boxes are stored as packed lists - a count byte, a species list, then the record
bodies, then the trainer names and nicknames in parallel arrays. Reading a box
means unpacking that list; writing means packing it back.
"""

from __future__ import annotations

from typing import ClassVar

from ..binio import read_u16, read_u16_be, write_u16
from ..pkm.formats import (
    PK1, PK2, STRING_LENGTH_INTERNATIONAL, STRING_LENGTH_JAPANESE,
)
from .base import SaveFile

SIZE_G1RAW = 0x8000
SIZE_G2RAW_U = 0x8000
SIZE_G2RAW_J = 0x10000


def read_bcd(data: bytes) -> int:
    """Read a big-endian binary-coded-decimal value.

    Each nibble is one decimal digit. Real saves sometimes hold nibbles above 9
    where a value was edited or never initialized, so those are folded in the
    same way the games would rather than raising.
    """
    value = 0
    for byte in data:
        value = value * 100 + 10 * (byte >> 4) + (byte & 0xF)
    return value


def _list_valid(data: bytes, offset: int, max_count: int) -> bool:
    """A packed list starts with a count and terminates its species array with 0xFF."""
    if offset + 1 >= len(data):
        return False
    count = data[offset]
    return count <= max_count and data[offset + 1 + count] == 0xFF


def _has_lists(data: bytes, offset1: int, offset2: int, max_count: int) -> bool:
    return _list_valid(data, offset1, max_count) and _list_valid(data, offset2, max_count)


def is_gen1_international(data: bytes) -> bool:
    return len(data) == SIZE_G1RAW and _has_lists(data, 0x2F2C, 0x30C0, 20)


def is_gen1_japanese(data: bytes) -> bool:
    return len(data) == SIZE_G1RAW and _has_lists(data, 0x2ED5, 0x302D, 30)


def is_gen2_gs_international(data: bytes) -> bool:
    return _has_lists(data, 0x288A, 0x2D6C, 20)


def is_gen2_gs_japanese(data: bytes) -> bool:
    return _has_lists(data, 0x2D10, 0x283E, 30)


def is_gen2_crystal_international(data: bytes) -> bool:
    return _has_lists(data, 0x2865, 0x2D10, 20)


def is_gen2_crystal_japanese(data: bytes) -> bool:
    return _has_lists(data, 0x2D10, 0x281A, 30)


class SAVGB(SaveFile):
    """Shared list-unpacking for the Game Boy saves."""

    #: Where each half of the box list region starts.
    BOX_REGION_1 = 0x4000
    BOX_REGION_2 = 0x6000
    #: Extra bytes between consecutive box lists (Gen2 pads by 2).
    BOX_LIST_GAP = 0

    PARTY_OFFSET: int = 0
    OT_OFFSET: int = 0
    TID_OFFSET: int = 0

    #: Box counts by language: (japanese, international). The class attributes
    #: below carry the international values so the geometry is visible without
    #: an instance; both are set for real in __init__.
    BOX_COUNTS: tuple[int, int] = (0, 0)
    BOX_SLOT_COUNT = 20

    def __init__(self, data: bytes | bytearray, *, japanese: bool = False) -> None:
        super().__init__(data)
        self._japanese = japanese
        self.string_length = (STRING_LENGTH_JAPANESE if japanese
                              else STRING_LENGTH_INTERNATIONAL)
        self.BOX_COUNT = self.BOX_COUNTS[0 if japanese else 1]
        self.BOX_SLOT_COUNT = 30 if japanese else 20

    # --- list geometry -------------------------------------------------------

    @property
    def _entry_size(self) -> int:
        """One packed entry: the record plus both name buffers."""
        return self.SIZE_BOXSLOT + 2 * self.string_length

    def _list_size(self, capacity: int, slot_size: int) -> int:
        return 1 + (capacity + 1) + (slot_size + 2 * self.string_length) * capacity

    def _box_list_offset(self, box: int) -> int:
        half = self.BOX_COUNT // 2 if self.BOX_LIST_GAP == 0 else (6 if self.japanese else 7)
        size = self._list_size(self.BOX_SLOT_COUNT, self.SIZE_BOXSLOT) + self.BOX_LIST_GAP
        if box < half:
            return self.BOX_REGION_1 + box * size
        return self.BOX_REGION_2 + (box - half) * size

    def _unpack(self, start: int, capacity: int, slot_size: int, index: int):
        """Read one slot out of a packed list."""
        base = start + 1 + (capacity + 1)
        body = base + slot_size * index
        names = base + slot_size * capacity
        ot = names + self.string_length * index
        nick = names + self.string_length * capacity + self.string_length * index

        count = self.data[start]
        if index >= count:
            return None
        marker = self.data[start + 1 + index]
        buffer = bytearray(self.ENTITY.SIZE_PARTY + 2 * self.string_length)
        buffer[:slot_size] = self.data[body:body + slot_size]
        buffer[self.ENTITY.SIZE_PARTY:self.ENTITY.SIZE_PARTY + self.string_length] = \
            self.data[ot:ot + self.string_length]
        buffer[self.ENTITY.SIZE_PARTY + self.string_length:] = \
            self.data[nick:nick + self.string_length]
        entity = self.ENTITY(buffer, japanese=self.japanese,
                             is_egg=marker == self.ENTITY.SLOT_EGG)
        return entity if entity.species else None

    #: Marker for a slot that holds nothing.
    SLOT_EMPTY = 0xFF

    def _slot_regions(self, start: int, capacity: int, slot_size: int,
                      index: int) -> tuple[int, int, int]:
        """Byte offsets of one slot's body, trainer name, and nickname."""
        base = start + 1 + (capacity + 1)
        names = base + slot_size * capacity
        return (base + slot_size * index,
                names + self.string_length * index,
                names + self.string_length * capacity + self.string_length * index)

    def _pack(self, start: int, capacity: int, slot_size: int, index: int, entity) -> None:
        body, ot, nick = self._slot_regions(start, capacity, slot_size, index)

        if entity is None:
            self.data[body:body + slot_size] = bytes(slot_size)
            self.data[ot:ot + self.string_length] = bytes(self.string_length)
            self.data[nick:nick + self.string_length] = bytes(self.string_length)
            self.data[start + 1 + index] = self.SLOT_EMPTY
        else:
            raw = bytes(entity.data)
            self.data[body:body + slot_size] = raw[:slot_size].ljust(slot_size, b"\0")
            self.data[start + 1 + index] = (self.ENTITY.SLOT_EGG if entity.is_egg
                                            else entity.species_internal)
            offset = entity.SIZE_PARTY
            self.data[ot:ot + self.string_length] = raw[offset:offset + self.string_length]
            self.data[nick:nick + self.string_length] = raw[offset + self.string_length:]

        self._rebuild_list(start, capacity, slot_size)

    def _rebuild_list(self, start: int, capacity: int, slot_size: int) -> None:
        """Restore the list invariant the games and the format detector rely on.

        Occupied slots sit at the front, every marker after them reads 0xFF, and
        the leading byte is the occupied count. Detection reads the terminator
        at ``1 + count``, so a list left with a gap stops being recognized as a
        save at all.

        Slot bodies are only moved when a write actually left a gap. Real saves
        keep leftover data in unused slots, and rewriting those would change
        bytes the caller never touched.
        """
        markers = [self.data[start + 1 + i] for i in range(capacity)]
        present = [i for i, m in enumerate(markers) if m not in (0, self.SLOT_EMPTY)]

        if present and present != list(range(len(present))):
            # A gap would leave the entity unreachable, so close it up.
            moved = []
            for index in present:
                body, ot, nick = self._slot_regions(start, capacity, slot_size, index)
                moved.append((
                    markers[index],
                    bytes(self.data[body:body + slot_size]),
                    bytes(self.data[ot:ot + self.string_length]),
                    bytes(self.data[nick:nick + self.string_length]),
                ))
            for index, (marker, body_bytes, ot_bytes, nick_bytes) in enumerate(moved):
                body, ot, nick = self._slot_regions(start, capacity, slot_size, index)
                self.data[start + 1 + index] = marker
                self.data[body:body + slot_size] = body_bytes
                self.data[ot:ot + self.string_length] = ot_bytes
                self.data[nick:nick + self.string_length] = nick_bytes
            count = len(moved)
        else:
            count = len(present)

        # Detection reads the count byte and the terminator immediately after
        # the occupied markers. Markers past that point are left alone: real
        # saves use both 0x00 and 0xFF there, and rewriting them would change
        # bytes in a file the caller only read.
        self.data[start] = count
        self.data[start + 1 + count] = self.SLOT_EMPTY

    # --- storage -------------------------------------------------------------

    def box_offset(self, box: int) -> int:
        return self._box_list_offset(box)

    def party_offset(self, slot: int) -> int:
        return self.PARTY_OFFSET

    @property
    def party_count(self) -> int:
        return self.data[self.PARTY_OFFSET]

    def get_box_slot(self, box: int, slot: int):
        return self._unpack(self._box_list_offset(box), self.BOX_SLOT_COUNT,
                            self.SIZE_BOXSLOT, slot)

    def set_box_slot(self, box: int, slot: int, entity) -> None:
        self._pack(self._box_list_offset(box), self.BOX_SLOT_COUNT,
                   self.SIZE_BOXSLOT, slot, entity)

    def get_party_slot(self, slot: int):
        return self._unpack(self.PARTY_OFFSET, 6, self.SIZE_PARTY_SLOT, slot)

    def set_party_slot(self, slot: int, entity) -> None:
        self._pack(self.PARTY_OFFSET, 6, self.SIZE_PARTY_SLOT, slot, entity)

    # --- trainer -------------------------------------------------------------

    @property
    def trainer_name(self) -> str:
        return self.decode_string(
            bytes(self.data[self.OT_OFFSET:self.OT_OFFSET + self.MAX_STRING_LENGTH_TRAINER + 1]))

    @property
    def language(self) -> int:
        return 1 if self.japanese else 2


class SAV1(SAVGB):
    KEY = "rby"
    GAME = "Red/Blue/Yellow"
    GENERATION = 1
    STRING_GENERATION = 1
    ENTITY = PK1
    SIZE_BOXSLOT = 33          # SIZE_1STORED
    SIZE_PARTY_SLOT = 44       # SIZE_1PARTY
    MAX_STRING_LENGTH_TRAINER = 7
    OT_OFFSET = 0x2598
    BOX_COUNTS = (8, 12)
    BOX_COUNT = 12

    #: Offsets that differ between the Japanese and international releases.
    OFFSETS_INT: ClassVar[dict[str, int]] = {
        "money": 0x25F3, "tid": 0x2605, "current_box_index": 0x284C,
        "play_time": 0x2CED, "party": 0x2F2C, "current_box": 0x30C0,
        "checksum": 0x3523,
    }
    OFFSETS_JPN: ClassVar[dict[str, int]] = {
        "money": 0x25EE, "tid": 0x25FB, "current_box_index": 0x2842,
        "play_time": 0x2CA0, "party": 0x2ED5, "current_box": 0x302D,
        "checksum": 0x3594,
    }

    def __init__(self, data: bytes | bytearray, *, japanese: bool = False) -> None:
        super().__init__(data, japanese=japanese)
        self.offsets = self.OFFSETS_JPN if japanese else self.OFFSETS_INT
        self.PARTY_OFFSET = self.offsets["party"]

    @property
    def tid16(self) -> int:
        return read_u16_be(self.data, self.offsets["tid"])

    @property
    def money(self) -> int:
        """Gen1 stores money as three binary-coded-decimal bytes."""
        start = self.offsets["money"]
        return read_bcd(self.data[start:start + 3])

    @property
    def play_time(self) -> tuple[int, int, int]:
        base = self.offsets["play_time"]
        return self.data[base], self.data[base + 2], self.data[base + 3]

    @property
    def current_box(self) -> int:
        return self.data[self.offsets["current_box_index"]] & 0x7F

    def _checksum(self) -> int:
        total = 0
        for i in range(self.OT_OFFSET, self.offsets["checksum"]):
            total += self.data[i]
        return (~total) & 0xFF

    @property
    def checksums_valid(self) -> bool:
        return self.data[self.offsets["checksum"]] == self._checksum()

    def fix_checksums(self) -> None:
        self.data[self.offsets["checksum"]] = self._checksum()


class SAV2(SAVGB):
    KEY = "gsc"
    GAME = "Gold/Silver/Crystal"
    GENERATION = 2
    STRING_GENERATION = 2
    ENTITY = PK2
    SIZE_BOXSLOT = 32          # SIZE_2STORED
    SIZE_PARTY_SLOT = 48       # SIZE_2PARTY
    MAX_STRING_LENGTH_TRAINER = 7
    BOX_LIST_GAP = 2
    TRAINER_OFFSET = 0x2009
    BOX_COUNTS = (9, 14)
    BOX_COUNT = 14

    #: (money, current box index, party, current box, checksum end, checksum 1, checksum 2)
    VARIANTS: ClassVar[dict[tuple[str, bool], dict]] = {
        ("gs", False): dict(money=0x23DB, current_box_index=0x2724, party=0x288A,
                            current_box=0x2D6C, play_time=0x2053, gender=None,
                            checksum_end=0x2D68, checksum1=0x2D69, checksum2=0x7E6D),
        ("c", False): dict(money=0x23DC, current_box_index=0x2700, party=0x2865,
                           current_box=0x2D10, play_time=0x2052, gender=0x3E3D,
                           checksum_end=0x2B82, checksum1=0x2D0D, checksum2=0x1F0D),
        ("gs", True): dict(money=0x23BC, current_box_index=0x2705, party=0x283E,
                           current_box=0x2D10, play_time=0x2034, gender=None,
                           checksum_end=0x2C8B, checksum1=0x2D0D, checksum2=0x7F0D),
        ("c", True): dict(money=0x23BE, current_box_index=0x26E2, party=0x281A,
                          current_box=0x2D10, play_time=0x2034, gender=0x8000,
                          checksum_end=0x2AE2, checksum1=0x2D0D, checksum2=0x7F0D),
    }

    def __init__(self, data: bytes | bytearray, *, japanese: bool = False,
                 crystal: bool = False) -> None:
        super().__init__(data, japanese=japanese)
        self.crystal = crystal
        self.offsets = self.VARIANTS[("c" if crystal else "gs", japanese)]
        self.PARTY_OFFSET = self.offsets["party"]
        self.OT_OFFSET = self.TRAINER_OFFSET + 2
        self.GAME = "Crystal" if crystal else "Gold/Silver"
        # The second checksum covers the game's backup copy of the save, which
        # holds an older state and so has its own value. Only keep it in step
        # when the file is already using the two as true mirrors.
        self.mirror_in_sync = (
            read_u16(self.data, self.offsets["checksum2"]) == self._checksum()
        )

    @property
    def tid16(self) -> int:
        return read_u16_be(self.data, self.TRAINER_OFFSET)

    @property
    def money(self) -> int:
        start = self.offsets["money"]
        return read_bcd(self.data[start:start + 3])

    @property
    def trainer_gender(self) -> int:
        offset = self.offsets["gender"]
        return self.data[offset] if offset is not None else 0

    @property
    def play_time(self) -> tuple[int, int, int]:
        base = self.offsets["play_time"]
        return read_u16_be(self.data, base), self.data[base + 2], self.data[base + 3]

    @property
    def current_box(self) -> int:
        return self.data[self.offsets["current_box_index"]] & 0x7F

    def _checksum(self) -> int:
        total = 0
        for i in range(self.TRAINER_OFFSET, self.offsets["checksum_end"] + 1):
            total += self.data[i]
        return total & 0xFFFF

    @property
    def checksums_valid(self) -> bool:
        """Whether the primary save's checksum matches its data."""
        return read_u16(self.data, self.offsets["checksum1"]) == self._checksum()

    @property
    def backup_checksum_valid(self) -> bool:
        """Whether the backup copy's checksum matches the primary save."""
        return self.mirror_in_sync

    def fix_checksums(self) -> None:
        expected = self._checksum()
        write_u16(self.data, self.offsets["checksum1"], expected)
        if self.mirror_in_sync:
            write_u16(self.data, self.offsets["checksum2"], expected)
