"""Shared save file behavior.

A save is a byte buffer with a known layout: a party area, a box area, and a
trainer block. Subclasses supply the offsets and the checksum rules; everything
above that - slot iteration, JSON, write-back - lives here.
"""

from __future__ import annotations

import base64
from typing import Any, Iterator

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
        raise NotImplementedError

    def box_slot_offset(self, box: int, slot: int) -> int:
        return self.box_offset(box) + slot * self.SIZE_BOXSLOT

    def party_offset(self, slot: int) -> int:
        raise NotImplementedError

    @property
    def party_count(self) -> int:
        raise NotImplementedError

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

    def _read_entity(self, offset: int, size: int):
        raw = bytes(self.data[offset:offset + size])
        if not self.slot_present(raw):
            return None
        entity = self.ENTITY(self.ENTITY.decrypt_buffer(raw))
        return entity if entity.species else None

    def get_box_slot(self, box: int, slot: int):
        """The entity in one box slot, or None when the slot is empty."""
        return self._read_entity(self.box_slot_offset(box, slot), self.SIZE_BOXSLOT)

    def set_box_slot(self, box: int, slot: int, entity) -> None:
        offset = self.box_slot_offset(box, slot)
        raw = entity.encrypted_bytes() if entity is not None else b""
        self.data[offset:offset + self.SIZE_BOXSLOT] = fit(raw, self.SIZE_BOXSLOT)

    def get_party_slot(self, slot: int):
        return self._read_entity(self.party_offset(slot), self.SIZE_PARTY_SLOT)

    def set_party_slot(self, slot: int, entity) -> None:
        offset = self.party_offset(slot)
        raw = entity.encrypted_bytes() if entity is not None else b""
        self.data[offset:offset + self.SIZE_PARTY_SLOT] = fit(raw, self.SIZE_PARTY_SLOT)

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

    def apply_dict(self, document: dict[str, Any]) -> None:
        """Write the entities in a JSON document back into their slots.

        Each slot's current occupant is the starting point, so a document that
        omits ``raw_base64`` still only changes the fields it names.
        """
        for record in document.get("party") or []:
            slot = int(record["slot"])
            entity = entity_json.from_dict(record["entity"], self.get_party_slot(slot))
            self.set_party_slot(slot, entity)
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
