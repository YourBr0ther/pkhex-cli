"""Shared save file behavior.

A save is a byte buffer with a known layout: a party area, a box area, and a
trainer block. Subclasses supply the offsets and the checksum rules; everything
above that - slot iteration, JSON, write-back - lives here.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, ClassVar
from collections.abc import Iterator

from ..pkm import serialize as entity_json
from ..binio import read_u16, read_u32
from ..strings import StringConverterOption, get_string, set_string

SCHEMA = "pkhexpy/save/1"

def fit(raw: bytes, size: int) -> bytes:
    """Pad or truncate to exactly ``size`` bytes.

    A stored-size entity written into a party-size slot is shorter than the
    slot; assigning it directly would shrink the buffer and shift everything
    after it.
    """
    if len(raw) == size:
        return raw
    if len(raw) > size:
        return raw[:size]
    return raw + bytes(size - len(raw))



@dataclass(frozen=True)
class ExtraSlot:
    """A place a game stores a Pokemon that is neither party nor box.

    The daycare is the universal one; the rest are per generation, and some
    hold Pokemon a player would otherwise lose track of entirely, such as the
    Zekrom fused into Kyurem or the two halves of a Surprise Trade in transit.
    """

    #: What the game calls this storage: "daycare", "battle_box", "fused", ...
    kind: str
    index: int = 0
    #: Whether the record is stored at party size rather than box size.
    party_format: bool = False

    @property
    def name(self) -> str:
        return f"{self.kind}/{self.index}"


@dataclass(frozen=True)
class ExtraRegion:
    """One run of extra slots: where it starts, how many, how far apart.

    Declaring the layout as data rather than as branching keeps the slot list
    and the offsets from drifting apart, since both come from this one table.
    """

    kind: str
    count: int
    stride: int
    start: int = 0
    party_format: bool = False
    #: Record size, when it differs from a box slot. Let's Go boxes are party
    #: sized but its daycare keeps a stored record.
    size: int | None = None
    #: How the generation finds the buffer: a block index, a block key, or None
    #: when ``start`` is already an offset into the save.
    source: int | None = None


class SaveFile:
    """One save file."""

    #: Short identifier, e.g. "sm", "swsh", "rs".
    KEY: str = ""
    #: Human-readable game name.
    GAME: str = ""
    GENERATION: int = 0
    #: Entity class stored in this save's boxes.
    ENTITY: type | None = None

    BOX_COUNT: int = 0
    BOX_SLOT_COUNT: int = 30
    #: Bytes per box slot; usually the entity's stored size.
    SIZE_BOXSLOT: int = 0
    SIZE_PARTY_SLOT: int = 0
    PARTY_SLOT_COUNT: int = 6

    #: Encoding used for trainer and box names.
    STRING_GENERATION: int = 0
    MAX_STRING_LENGTH_TRAINER: int = 12

    #: Trailing emulator real-time-clock bytes, preserved on write.
    rtc_footer: bytes = b""

    def __init__(self, data: bytes | bytearray) -> None:
        self.data = bytearray(data)

    # --- layout, supplied by subclasses -------------------------------------

    def box_offset(self, box: int) -> int:
        self._check_index("box", box, self.BOX_COUNT)
        return self._box_offset(box)

    def _box_offset(self, box: int) -> int:
        raise NotImplementedError

    def box_slot_offset(self, box: int, slot: int) -> int:
        self._check_index("box slot", slot, self.BOX_SLOT_COUNT)
        return self._box_slot_offset(box, slot)

    def _box_slot_offset(self, box: int, slot: int) -> int:
        return self.box_offset(box) + slot * self.SIZE_BOXSLOT

    @staticmethod
    def _check_index(what: str, index: int, count: int) -> None:
        """Reject an index outside the region before it becomes an offset.

        An out-of-range index would otherwise be turned into an offset anyway
        and read, or worse write, whatever else lives there.
        """
        if not 0 <= index < count:
            raise IndexError(
                f"{what} {index} is out of range; this save has {count}")

    def party_offset(self, slot: int) -> int:
        self._check_index("party slot", slot, self.PARTY_SLOT_COUNT)
        return self._party_offset(slot)

    def _party_offset(self, slot: int) -> int:
        raise NotImplementedError

    @property
    def party_count(self) -> int:
        raise NotImplementedError

    def region(self, name: str) -> tuple[bytearray, int]:
        """The buffer and base offset a named group of fields lives in.

        Trainer fields sit at fixed offsets from a base that each generation
        finds its own way: a save block, a checksummed chunk, or the start of
        the file. Naming the region lets the fields be declared once.
        """
        raise KeyError(f"{self.GAME} has no {name!r} region")

    # --- trainer info; subclasses override what they store -------------------

    @property
    def trainer_name(self) -> str:
        return ""

    @property
    def tid16(self) -> int:
        return 0

    @property
    def sid16(self) -> int:
        return 0

    @property
    def trainer_gender(self) -> int:
        return 0

    @property
    def language(self) -> int:
        return 0

    @property
    def money(self) -> int | None:
        return None

    @property
    def play_time(self) -> tuple[int, int, int] | None:
        return None

    @property
    def version(self) -> int | None:
        return None

    # --- string helpers ------------------------------------------------------

    #: GameCube-era saves store text big-endian.
    BIG_ENDIAN: bool = False

    #: Set by formats that know their language up front rather than reading it
    #: out of the save. Gen1 has no language byte to consult.
    _japanese: bool | None = None

    @property
    def japanese(self) -> bool:
        """Whether this save uses the Japanese glyph tables."""
        if self._japanese is not None:
            return self._japanese
        return self.language == 1

    def decode_string(self, raw: bytes) -> str:
        return get_string(raw, self.STRING_GENERATION or self.GENERATION,
                          jp=self.japanese, big_endian=self.BIG_ENDIAN,
                          language=self.language)

    def encode_string(self, buffer: bytearray, value: str, max_chars: int,
                      option: StringConverterOption | None = None) -> int:
        return set_string(buffer, value, max_chars,
                          self.STRING_GENERATION or self.GENERATION,
                          jp=self.japanese, big_endian=self.BIG_ENDIAN,
                          language=self.language, option=option)

    def encode_trainer_name(self, size: int, value: str) -> bytes:
        """Encode a trainer name, refusing one this save cannot represent.

        Generations 1 to 4 store text as indexes into a per-language glyph
        table, so a name the target language has no glyphs for would be stored
        truncated at the first one missing. Decoding what was just encoded is
        the only way to know it survived.
        """
        limit = self.MAX_STRING_LENGTH_TRAINER
        buffer = bytearray(size)
        self.encode_string(buffer, value, limit)
        wanted, got = value[:limit], self.decode_string(bytes(buffer))
        if got != wanted:
            raise ValueError(
                f"{wanted!r} cannot be written in this save's encoding "
                f"(generation {self.STRING_GENERATION or self.GENERATION}, "
                f"language {self.language}); it would be stored as {got!r}")
        return bytes(buffer)

    # --- storage outside the party and boxes ---------------------------------

    #: Where a save keeps Pokemon that are neither in the party nor in a box.
    EXTRA_REGIONS: ClassVar[tuple[ExtraRegion, ...]] = ()

    def extra_regions(self) -> tuple[ExtraRegion, ...]:
        """The regions this particular save has, which can depend on the game
        revision, so subclasses may narrow the class-level table."""
        return self.EXTRA_REGIONS

    def _extra_base(self, region: ExtraRegion) -> tuple[bytearray, int]:
        """The buffer a region lives in, and where the region starts in it."""
        return self.data, 0

    def extra_slots(self) -> tuple[ExtraSlot, ...]:
        return tuple(ExtraSlot(region.kind, index, region.party_format)
                     for region in self.extra_regions()
                     for index in range(region.count))

    def _find_region(self, kind: str, index: int) -> ExtraRegion:
        for region in self.extra_regions():
            if region.kind == kind and 0 <= index < region.count:
                return region
        raise KeyError(f"{self.GAME} has no {kind} slot {index}")

    def _extra_region(self, kind: str, index: int) -> tuple[bytearray, int, int]:
        """The buffer, offset and record size one extra slot occupies."""
        region = self._find_region(kind, index)
        buffer, base = self._extra_base(region)
        offset = base + region.start + index * region.stride
        return buffer, offset, region.size or self.SIZE_BOXSLOT

    def get_extra_slot(self, kind: str, index: int = 0):
        """The Pokemon in one extra slot, or None when it is empty."""
        buffer, offset, size = self._extra_region(kind, index)
        return self._read_extra(buffer, offset, size)

    def _read_extra(self, buffer, offset: int, size: int):
        """Read an extra slot, rejecting anything that fails its own checksum.

        Boxes are kept tidy by the games, but several of these regions are
        scratch space: the Grand Underground's encounter cache holds five real
        Pokemon and then whatever the game last had in that memory, which
        passes a presence check and decodes to a nonsense species.
        """
        entity = self.read_slot(buffer, offset, size)
        if entity is None:
            return None
        if not getattr(entity, "checksum_valid", True):
            return None
        return entity if entity.species_name is not None else None

    def set_extra_slot(self, kind: str, index: int, entity) -> None:
        buffer, offset, size = self._extra_region(kind, index)
        buffer[offset:offset + size] = self._slot_bytes(entity, size)

    def iter_extra(self) -> Iterator[tuple[ExtraSlot, Any]]:
        """Yield (slot, entity) for every occupied slot outside party and boxes."""
        for slot in self.extra_slots():
            try:
                buffer, offset, size = self._extra_region(slot.kind, slot.index)
            except (NotImplementedError, KeyError, IndexError):
                continue
            entity = self._read_extra(buffer, offset, size)
            if entity is not None:
                yield slot, entity

    # --- entity access -------------------------------------------------------

    def slot_present(self, raw: bytes) -> bool:
        """Whether a raw slot holds a Pokemon, judged before decryption.

        Port of ``PKHeX.Core.EntityDetection``. Testing the decrypted species
        is not enough: unused box slots can hold leftover bytes that decrypt to
        a nonsense species, and treating those as real inflates counts and
        rewrites slots the caller never touched.
        """
        if not any(raw):
            return False
        if self.GENERATION >= 4:
            # Empty slots have a zero PID; a genuine zero PID still leaves the
            # species field readable at offset 8.
            return read_u32(raw, 0) != 0 or read_u16(raw, 8) != 0
        if self.GENERATION <= 2:
            return raw[0] != 0
        # Gen3 marks an occupied slot with the has-species flag.
        return (raw[0x13] & 0xFB) == 2

    def read_slot(self, buffer, offset: int, size: int):
        """Decode one record out of any buffer, or None when the slot is empty.

        Every read of a Pokemon goes through here: party, box, and the storage
        outside both. The generations differ only in which buffer they hand it.
        """
        raw = bytes(buffer[offset:offset + size])
        if len(raw) < size or not self.slot_present(raw):
            return None
        entity = self.ENTITY(self.ENTITY.decrypt_buffer(raw))
        return entity if entity.species else None

    def get_box_slot(self, box: int, slot: int):
        """The entity in one box slot, or None when the slot is empty."""
        return self.read_slot(self.data, self.box_slot_offset(box, slot),
                              self.SIZE_BOXSLOT)

    def _check_entity(self, entity) -> None:
        """Reject an entity from another generation.

        Several formats share a stored size, so writing one into the other's
        slot succeeds and the bytes are simply reinterpreted under the wrong
        layout. The save still checksums, which makes it look fine.
        """
        if entity is None or isinstance(entity, self.ENTITY):
            return
        raise TypeError(
            f"{self.GAME} stores {self.ENTITY.__name__}, not "
            f"{type(entity).__name__}; convert it first")

    def _slot_bytes(self, entity, size: int) -> bytes:
        """The bytes to write into a slot: checked, encrypted, exactly sized.

        Every slot write goes through here so the type check and the fixed
        size cannot be skipped by a generation that overrides the accessor.
        """
        self._check_entity(entity)
        raw = entity.encrypted_bytes() if entity is not None else b""
        return fit(raw, size)

    def set_box_slot(self, box: int, slot: int, entity) -> None:
        offset = self.box_slot_offset(box, slot)
        self.data[offset:offset + self.SIZE_BOXSLOT] = self._slot_bytes(
            entity, self.SIZE_BOXSLOT)

    def get_party_slot(self, slot: int):
        return self.read_slot(self.data, self.party_offset(slot),
                              self.SIZE_PARTY_SLOT)

    def _write_party_slot(self, slot: int, entity) -> None:
        """Put an entity in a party slot without touching the party size."""
        offset = self.party_offset(slot)
        self.data[offset:offset + self.SIZE_PARTY_SLOT] = self._slot_bytes(
            entity, self.SIZE_PARTY_SLOT)

    def _set_party_count(self, count: int) -> None:
        raise NotImplementedError(
            f"{self.GAME} does not support changing the party size")

    def _require_resizable_party(self) -> None:
        """Fail before the first write, not halfway through the shuffle."""
        if type(self)._set_party_count is SaveFile._set_party_count:
            raise NotImplementedError(
                f"{self.GAME} does not support changing the party size")

    def set_party_slot(self, slot: int, entity) -> None:
        """Put an entity in a party slot, or remove one when entity is None.

        The party is a list, not an array of six independent slots: the games
        read a count and expect the occupants to sit at the front. Writing a
        seventh Pokemon into slot 4 of a party of two, or leaving a hole by
        clearing the lead, produces a party no game would have written.
        """
        if entity is None:
            self.remove_party_slot(slot)
            return
        self._check_index("party slot", slot, self.PARTY_SLOT_COUNT)
        count = self.party_count
        if slot > count:
            self._require_resizable_party()
            raise IndexError(
                f"party slot {slot} would leave a gap; this party holds "
                f"{count}, so the next free slot is {count}")
        if slot == count:
            self._require_resizable_party()
        self._write_party_slot(slot, entity)
        if slot == count:
            self._set_party_count(count + 1)

    def remove_party_slot(self, slot: int) -> None:
        """Take a Pokemon out of the party, closing the gap behind it."""
        self._check_index("party slot", slot, self.PARTY_SLOT_COUNT)
        count = self.party_count
        if slot >= count:
            return
        self._require_resizable_party()
        for index in range(slot, count - 1):
            self._write_party_slot(index, self.get_party_slot(index + 1))
        self._write_party_slot(count - 1, None)
        self._set_party_count(count - 1)

    def iter_boxes(self) -> Iterator[tuple[int, int, Any]]:
        """Yield (box, slot, entity) for every occupied box slot."""
        for box in range(self.BOX_COUNT):
            for slot in range(self.BOX_SLOT_COUNT):
                entity = self.get_box_slot(box, slot)
                if entity is not None:
                    yield box, slot, entity

    def iter_party(self) -> Iterator[tuple[int, Any]]:
        for slot in range(min(self.party_count, self.PARTY_SLOT_COUNT)):
            entity = self.get_party_slot(slot)
            if entity is not None:
                yield slot, entity

    def box_name(self, box: int) -> str | None:
        return None

    # --- integrity -----------------------------------------------------------

    @property
    def checksums_valid(self) -> bool:
        return True

    def fix_checksums(self) -> None:
        """Recompute every stored checksum. Subclasses override."""

    def to_bytes(self) -> bytes:
        """The save as the game would store it, checksums refreshed."""
        self.fix_checksums()
        return bytes(self.data) + self.rtc_footer

    # --- JSON ----------------------------------------------------------------

    def to_dict(self, *, include_raw: bool = False, include_boxes: bool = True,
                include_entity_raw: bool = True) -> dict[str, Any]:
        played = self.play_time
        document: dict[str, Any] = {
            "schema": SCHEMA,
            "save_format": self.KEY,
            "game": self.GAME,
            "generation": self.GENERATION,
            "size": len(self.data),
            "checksums_valid": self.checksums_valid,
            "trainer": {
                "Name": self.trainer_name,
                "TID16": self.tid16,
                "SID16": self.sid16,
                "Gender": self.trainer_gender,
                "Language": self.language,
            },
        }
        if self.money is not None:
            document["trainer"]["Money"] = self.money
        if played is not None:
            document["trainer"]["PlayTime"] = {
                "Hours": played[0], "Minutes": played[1], "Seconds": played[2],
            }
        if self.version is not None:
            document["trainer"]["Version"] = self.version

        document["extra"] = [
            {"kind": slot.kind, "index": slot.index,
             "entity": entity_json.to_dict(entity, include_raw=include_entity_raw)}
            for slot, entity in self.iter_extra()
        ]

        document["party"] = [
            {"slot": slot,
             "entity": entity_json.to_dict(entity, include_raw=include_entity_raw)}
            for slot, entity in self.iter_party()
        ]

        if include_boxes:
            boxes = []
            for box in range(self.BOX_COUNT):
                slots = []
                for slot in range(self.BOX_SLOT_COUNT):
                    entity = self.get_box_slot(box, slot)
                    if entity is None:
                        continue
                    slots.append({
                        "slot": slot,
                        "entity": entity_json.to_dict(entity,
                                                      include_raw=include_entity_raw),
                    })
                boxes.append({
                    "box": box,
                    "name": self.box_name(box),
                    "slots": slots,
                })
            document["boxes"] = boxes

        if include_raw:
            # to_bytes refreshes checksums. Snapshot first so exporting a save
            # never silently repairs the copy in raw_base64 while the document
            # above still reports it as invalid.
            snapshot = bytes(self.data)
            raw = self.to_bytes()
            self.data[:] = snapshot
            document["raw_base64"] = base64.b64encode(raw).decode("ascii")
        return document

    #: Trainer keys a document may carry, paired with the attribute each one
    #: writes. Anything else in the block is rejected rather than ignored.
    TRAINER_KEYS: ClassVar[dict[str, str]] = {
        "Name": "trainer_name", "TID16": "tid16", "SID16": "sid16",
        "Gender": "trainer_gender", "Money": "money", "Version": "version",
        "Language": "language",
    }

    def apply_trainer(self, trainer: dict[str, Any]) -> None:
        """Write the trainer block of a JSON document back into the save.

        Only keys whose value actually changed are written, so a document
        round tripped without edits touches nothing, and a field this save
        cannot write is reported instead of passing silently.
        """
        for key, value in trainer.items():
            if key == "PlayTime":
                played = (int(value["Hours"]), int(value["Minutes"]),
                          int(value["Seconds"]))
                if played != self.play_time:
                    self.play_time = played
                continue
            attribute = self.TRAINER_KEYS.get(key)
            if attribute is None:
                raise ValueError(f"unknown trainer field {key!r}")
            if value == getattr(self, attribute):
                continue
            try:
                setattr(self, attribute, value)
            except AttributeError as exc:
                raise NotImplementedError(
                    f"{self.GAME} cannot change {key}; it is read-only in this "
                    f"format") from exc

    def apply_dict(self, document: dict[str, Any]) -> None:
        """Write the entities in a JSON document back into their slots.

        Each slot's current occupant is the starting point, so a document that
        omits ``raw_base64`` still only changes the fields it names.
        """
        self.apply_trainer(document.get("trainer") or {})
        for record in document.get("party") or []:
            slot = int(record["slot"])
            entity = entity_json.from_dict(record["entity"], self.get_party_slot(slot))
            self.set_party_slot(slot, entity)
        for record in document.get("extra") or []:
            kind, index = record["kind"], int(record["index"])
            current = self.get_extra_slot(kind, index)
            self.set_extra_slot(kind, index,
                                entity_json.from_dict(record["entity"], current))
        for box_record in document.get("boxes") or []:
            box = int(box_record["box"])
            for record in box_record.get("slots") or []:
                slot = int(record["slot"])
                entity = entity_json.from_dict(record["entity"],
                                               self.get_box_slot(box, slot))
                self.set_box_slot(box, slot, entity)
        self.fix_checksums()

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.GAME} {len(self.data)} bytes>"
