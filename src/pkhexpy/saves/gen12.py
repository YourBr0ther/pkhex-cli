"""Game Boy saves: Red/Blue/Yellow and Gold/Silver/Crystal.

Boxes are stored as packed lists - a count byte, a species list, then the record
bodies, then the trainer names and nicknames in parallel arrays. Reading a box
means unpacking that list; writing means packing it back.
"""

from __future__ import annotations

from typing import ClassVar

from ..binio import read_u16, read_u16_be, write_u16, write_u16_be
from ..pkm.formats import (
    PK1, PK2, STRING_LENGTH_INTERNATIONAL, STRING_LENGTH_JAPANESE,
)
from .base import ExtraRegion, SaveFile

SIZE_G1RAW = 0x8000
SIZE_G2RAW_U = 0x8000
SIZE_G2RAW_J = 0x10000


def write_bcd(size: int, value: int) -> bytes:
    """Encode a value as big-endian binary-coded decimal, as the games store it."""
    limit = 10 ** (size * 2)
    if not 0 <= value < limit:
        raise ValueError(f"{value} does not fit in {size} BCD bytes (max {limit - 1})")
    digits = str(value).rjust(size * 2, "0")
    return bytes(int(digits[i * 2]) << 4 | int(digits[i * 2 + 1]) for i in range(size))


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
        self._check_index("slot", index, capacity)
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
        """Byte offsets of one slot's body, trainer name, and nickname.

        Gen1/2 pack the list themselves rather than going through
        ``box_slot_offset``, so the range check belongs here.
        """
        self._check_index("slot", index, capacity)
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

    def _box_offset(self, box: int) -> int:
        return self._box_list_offset(box)

    def _party_offset(self, slot: int) -> int:
        return self.PARTY_OFFSET

    @property
    def party_count(self) -> int:
        return self.data[self.PARTY_OFFSET]

    def get_box_slot(self, box: int, slot: int):
        return self._unpack(self.box_offset(box), self.BOX_SLOT_COUNT,
                            self.SIZE_BOXSLOT, slot)

    def set_box_slot(self, box: int, slot: int, entity) -> None:
        self._check_entity(entity)
        self._pack(self.box_offset(box), self.BOX_SLOT_COUNT,
                   self.SIZE_BOXSLOT, slot, entity)

    def get_party_slot(self, slot: int):
        return self._unpack(self.PARTY_OFFSET, self.PARTY_SLOT_COUNT,
                            self.SIZE_PARTY_SLOT, slot)

    def set_party_slot(self, slot: int, entity) -> None:
        self._check_entity(entity)
        self._pack(self.PARTY_OFFSET, self.PARTY_SLOT_COUNT,
                   self.SIZE_PARTY_SLOT, slot, entity)

    def remove_party_slot(self, slot: int) -> None:
        """Clear a party slot. ``_rebuild_list`` closes the gap and recounts.

        The generic version shuffles the slots itself and then writes a count
        byte, which a packed list does not have in the same place. Packing one
        slot as empty does the whole job here.
        """
        self.set_party_slot(slot, None)

    def _set_party_count(self, count: int) -> None:
        # The count is the first byte of the list, and _rebuild_list is the only
        # thing that should set it: it has just worked out which slots are
        # occupied. Declaring the method keeps _require_resizable_party from
        # deciding this format cannot resize its party, which it plainly can.
        self.data[self.PARTY_OFFSET] = count

    # --- daycare -------------------------------------------------------------

    #: Offset of the daycare region, or None when this variant is unmapped.
    DAYCARE_OFFSET: int | None = None
    #: Records in it, counting the Gen2 egg slot.
    DAYCARE_SLOT_COUNT = 1

    def extra_regions(self) -> tuple[ExtraRegion, ...]:
        if self.DAYCARE_OFFSET is None:
            return ()
        return (ExtraRegion("daycare", self.DAYCARE_SLOT_COUNT, 0),)

    def _daycare_slot_offset(self, index: int) -> int:
        raise NotImplementedError

    def _daycare_occupied(self, index: int) -> bool:
        raise NotImplementedError

    def _read_nob(self, offset: int, *, is_egg: bool = False):
        """Read a record the games store as nickname, then OT, then body.

        Boxes and the party pack their names into runs shared by every slot,
        but a daycare holds one Pokemon, so the games write its two names
        immediately in front of it instead.
        """
        length = self.string_length
        size = self.SIZE_BOXSLOT
        nick = self.data[offset:offset + length]
        trainer = self.data[offset + length:offset + 2 * length]
        body = bytes(self.data[offset + 2 * length:offset + 2 * length + size])
        if len(body) < size or not self.slot_present(body):
            return None
        buffer = bytearray(self.ENTITY.SIZE_PARTY + 2 * length)
        buffer[:size] = body
        buffer[self.ENTITY.SIZE_PARTY:self.ENTITY.SIZE_PARTY + length] = trainer
        buffer[self.ENTITY.SIZE_PARTY + length:] = nick
        entity = self.ENTITY(buffer, japanese=self.japanese, is_egg=is_egg)
        return entity if entity.species else None

    def _write_nob(self, offset: int, entity) -> None:
        length = self.string_length
        size = self.SIZE_BOXSLOT
        raw = bytes(entity.data)
        names = entity.SIZE_PARTY
        self.data[offset:offset + length] = raw[names + length:names + 2 * length]
        self.data[offset + length:offset + 2 * length] = raw[names:names + length]
        self.data[offset + 2 * length:offset + 2 * length + size] = \
            raw[:size].ljust(size, b"\0")

    def get_extra_slot(self, kind: str, index: int = 0):
        self._find_region(kind, index)
        if not self._daycare_occupied(index):
            return None
        entity = self._read_nob(self._daycare_slot_offset(index),
                                is_egg=index == self.DAYCARE_SLOT_COUNT - 1
                                and self.GENERATION == 2)
        if entity is None or entity.species_name is None:
            return None
        return entity

    def set_extra_slot(self, kind: str, index: int, entity) -> None:
        self._find_region(kind, index)
        self._check_entity(entity)
        if entity is None:
            raise NotImplementedError(
                f"{self.GAME} needs its daycare flags cleared as well; "
                "removing a Pokemon from the daycare is not supported")
        self._write_nob(self._daycare_slot_offset(index), entity)

    # --- trainer -------------------------------------------------------------

    @property
    def trainer_name(self) -> str:
        return self.decode_string(
            bytes(self.data[self.OT_OFFSET:self.OT_OFFSET + self.MAX_STRING_LENGTH_TRAINER + 1]))

    @trainer_name.setter
    def trainer_name(self, value: str) -> None:
        size = self.MAX_STRING_LENGTH_TRAINER + 1
        self.data[self.OT_OFFSET:self.OT_OFFSET + size] = self.encode_trainer_name(
            size, value)

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
        "checksum": 0x3523, "daycare": 0x2CF4,
    }
    OFFSETS_JPN: ClassVar[dict[str, int]] = {
        "money": 0x25EE, "tid": 0x25FB, "current_box_index": 0x2842,
        "play_time": 0x2CA0, "party": 0x2ED5, "current_box": 0x302D,
        "checksum": 0x3594, "daycare": 0x2CA7,
    }

    @property
    def DAYCARE_OFFSET(self) -> int:
        return self.offsets["daycare"]

    def _daycare_slot_offset(self, index: int) -> int:
        # A status byte, then the single record.
        return self.offsets["daycare"] + 1

    def _daycare_occupied(self, index: int) -> bool:
        return self.data[self.offsets["daycare"]] == 1

    def __init__(self, data: bytes | bytearray, *, japanese: bool = False) -> None:
        super().__init__(data, japanese=japanese)
        self.offsets = self.OFFSETS_JPN if japanese else self.OFFSETS_INT
        self.PARTY_OFFSET = self.offsets["party"]

    @property
    def tid16(self) -> int:
        return read_u16_be(self.data, self.offsets["tid"])

    @tid16.setter
    def tid16(self, value: int) -> None:
        write_u16_be(self.data, self.offsets["tid"], value)

    @property
    def money(self) -> int:
        """Gen1 stores money as three binary-coded-decimal bytes."""
        start = self.offsets["money"]
        return read_bcd(self.data[start:start + 3])

    @money.setter
    def money(self, value: int) -> None:
        start = self.offsets["money"]
        self.data[start:start + 3] = write_bcd(3, value)

    @property
    def play_time(self) -> tuple[int, int, int]:
        base = self.offsets["play_time"]
        return self.data[base], self.data[base + 2], self.data[base + 3]

    @play_time.setter
    def play_time(self, value: tuple[int, int, int]) -> None:
        base = self.offsets["play_time"]
        hours, minutes, seconds = value
        self.data[base] = hours
        self.data[base + 2] = minutes
        self.data[base + 3] = seconds

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

    #: (money, current box index, party, current box, checksum end, checksum 1,
    #: checksum 2, daycare). The daycare sits a fixed 0x3C past the start of the
    #: Pokedex-seen flags, which is where PKHeX derives it from too.
    VARIANTS: ClassVar[dict[tuple[str, bool], dict]] = {
        ("gs", False): dict(money=0x23DB, current_box_index=0x2724, party=0x288A,
                            current_box=0x2D6C, play_time=0x2053, gender=None,
                            checksum_end=0x2D68, checksum1=0x2D69, checksum2=0x7E6D,
                            daycare=0x2A6C + 0x3C),
        ("c", False): dict(money=0x23DC, current_box_index=0x2700, party=0x2865,
                           current_box=0x2D10, play_time=0x2052, gender=0x3E3D,
                           checksum_end=0x2B82, checksum1=0x2D0D, checksum2=0x1F0D,
                           daycare=0x2A47 + 0x3C),
        ("gs", True): dict(money=0x23BC, current_box_index=0x2705, party=0x283E,
                           current_box=0x2D10, play_time=0x2034, gender=None,
                           checksum_end=0x2C8B, checksum1=0x2D0D, checksum2=0x7F0D,
                           daycare=0x29EE + 0x3C),
        ("c", True): dict(money=0x23BE, current_box_index=0x26E2, party=0x281A,
                          current_box=0x2D10, play_time=0x2034, gender=0x8000,
                          checksum_end=0x2AE2, checksum1=0x2D0D, checksum2=0x7F0D,
                          daycare=0x29CA + 0x3C),
    }

    #: Two parents and the egg they produced.
    DAYCARE_SLOT_COUNT = 3

    @property
    def DAYCARE_OFFSET(self) -> int:
        return self.offsets["daycare"]

    def _daycare_record_size(self) -> int:
        return 2 * self.string_length + self.SIZE_BOXSLOT

    def _daycare_slot_offset(self, index: int) -> int:
        # A status byte, then the first record. The second is preceded by three
        # more bytes of breeding state, and the egg follows it immediately.
        offset = self.offsets["daycare"] + 1
        if index >= 1:
            offset += self._daycare_record_size() + 3
        if index >= 2:
            offset += self._daycare_record_size()
        return offset

    #: Bit of the daycare status byte that means a Pokemon is in the slot.
    #: PKHeX tests bit 0 instead, which answers a different question: across
    #: the corpus bit 0 is set in only some occupied daycares, while bit 7 is
    #: set in every one and in none of the empty ones. The eggs settle it, a
    #: Hitmontop and Ditto pair sitting behind a Tyrogue and a Sandshrew and
    #: Swinub pair behind a Swinub, so those parents are really there.
    DAYCARE_OCCUPIED_BIT = 0x80

    def _daycare_occupied(self, index: int) -> bool:
        if index == 2:
            # The egg has no status byte; it is there when a record is.
            return True
        flag = self.offsets["daycare"]
        if index == 1:
            flag += self._daycare_record_size() + 1
        return bool(self.data[flag] & self.DAYCARE_OCCUPIED_BIT)

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

    @tid16.setter
    def tid16(self, value: int) -> None:
        write_u16_be(self.data, self.TRAINER_OFFSET, value)

    @property
    def money(self) -> int:
        start = self.offsets["money"]
        return read_bcd(self.data[start:start + 3])

    @money.setter
    def money(self, value: int) -> None:
        start = self.offsets["money"]
        self.data[start:start + 3] = write_bcd(3, value)

    @property
    def trainer_gender(self) -> int:
        offset = self.offsets["gender"]
        return self.data[offset] if offset is not None else 0

    @trainer_gender.setter
    def trainer_gender(self, value: int) -> None:
        offset = self.offsets["gender"]
        if offset is None:
            raise NotImplementedError(f"{self.GAME} stores no trainer gender")
        self.data[offset] = value

    @property
    def play_time(self) -> tuple[int, int, int]:
        base = self.offsets["play_time"]
        return read_u16_be(self.data, base), self.data[base + 2], self.data[base + 3]

    @play_time.setter
    def play_time(self, value: tuple[int, int, int]) -> None:
        base = self.offsets["play_time"]
        hours, minutes, seconds = value
        write_u16_be(self.data, base, hours)
        self.data[base + 2] = minutes
        self.data[base + 3] = seconds

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
