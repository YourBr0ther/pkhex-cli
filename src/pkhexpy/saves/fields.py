"""Descriptors for the trainer record a save keeps about its player.

The entity side solves this in ``pkm/fields.py``: a descriptor owns one slice
of a buffer, reading decodes it, assigning re-encodes it. Saves needed the same
thing. Written as property pairs it came to nearly three hundred lines of
getters and setters that differed only in an offset, and it was possible, and
for a while true, for a field to have a getter and no setter, so an edit made
through the JSON was accepted and then dropped.

Where the bytes live differs by generation, so a descriptor names a *region*
rather than an absolute offset, and each save class resolves that name to a
buffer and a base through :meth:`SaveFile.region`. A field whose value is not a
plain integer at a fixed place, Gen3 money XOR-ed with the security key, the
binary-coded decimal of Gen1 and Gen2, the inverted gender flag in BDSP, stays
hand-written; forcing those through a descriptor would hide the very thing that
makes them worth a comment.
"""

from __future__ import annotations

from typing import Any

from .. import binio


class SaveField:
    """One value at a fixed offset inside a named region of a save."""

    def __init__(self, region: str, offset: int | str, delta: int = 0) -> None:
        #: An int is a literal offset. A string names a class attribute holding
        #: one, for the generations whose games share a layout but move a field.
        self.region = region
        self.offset = offset
        self.delta = delta
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def locate(self, obj: Any) -> tuple[Any, int]:
        buffer, base = obj.region(self.region)
        offset = getattr(obj, self.offset) if isinstance(self.offset, str) \
            else self.offset
        return buffer, base + offset + self.delta

    def __get__(self, obj: Any, owner: type | None = None) -> Any:
        if obj is None:
            return self
        return self.decode(obj)

    def __set__(self, obj: Any, value: Any) -> None:
        self.encode(obj, value)

    def decode(self, obj: Any) -> Any:
        raise NotImplementedError

    def encode(self, obj: Any, value: Any) -> None:
        raise NotImplementedError


class _Int(SaveField):
    size = 1
    big_endian = False

    def decode(self, obj: Any) -> int:
        buffer, offset = self.locate(obj)
        return binio.read_int(buffer, offset, self.size, self.big_endian)

    def encode(self, obj: Any, value: Any) -> None:
        buffer, offset = self.locate(obj)
        binio.write_int(buffer, offset, self.size, int(value),
                        big=self.big_endian)


class U8(_Int):
    size = 1


class U16(_Int):
    size = 2


class U32(_Int):
    size = 4


class U16BE(_Int):
    size = 2
    big_endian = True


class Text(SaveField):
    """A trainer name, encoded the way this save's generation writes text."""

    def __init__(self, region: str, offset: int | str, length: int,
                 delta: int = 0) -> None:
        super().__init__(region, offset, delta)
        self.length = length

    def decode(self, obj: Any) -> str:
        buffer, offset = self.locate(obj)
        return obj.decode_string(bytes(buffer[offset:offset + self.length]))

    def encode(self, obj: Any, value: Any) -> None:
        buffer, offset = self.locate(obj)
        buffer[offset:offset + self.length] = obj.encode_trainer_name(
            self.length, str(value))
