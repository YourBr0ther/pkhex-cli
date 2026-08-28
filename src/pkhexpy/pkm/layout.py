"""Runtime base for byte-backed entity classes.

``LayoutBase`` owns the buffer and the field registry. The generated layout
classes in ``_layouts.py`` subclass it and declare descriptors; the hand-written
classes in ``formats.py`` subclass those and add derived behavior.
"""

from __future__ import annotations

from typing import Any
from collections.abc import Iterator

from ..strings import StringConverterOption, get_string, set_string


class LayoutBase:
    """A fixed-size record with named, offset-addressed fields."""

    #: Entity format number, 1-9. Drives which string encoding applies.
    FORMAT: int = 0
    #: Generation whose string encoding this format uses; usually FORMAT.
    STRING_GENERATION: int | None = None
    #: Stored (box) and party sizes in bytes.
    SIZE_STORED: int = 0
    SIZE_PARTY: int = 0
    #: File extension PKHeX writes for this format.
    EXTENSION: str = "pkm"
    #: GameCube-era formats store multi-byte values big-endian.
    BIG_ENDIAN: bool = False

    _fields: dict[str, Any]

    #: Attributes that live on the instance rather than in the buffer.
    _INSTANCE_ATTRS = frozenset({"data", "japanese"})

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Descriptors are bound by __set_name__ before this runs, so collect them
        # from the MRO rather than having each one register itself.
        from .fields import Field

        registry: dict[str, Any] = {}
        for base in reversed(cls.__mro__):
            for name, value in vars(base).items():
                if isinstance(value, Field):
                    registry[name] = value
        cls._fields = registry

    def __init__(self, data: bytes | bytearray | None = None, *,
                 japanese: bool = False) -> None:
        # A stored-size file stays stored-size: growing it to party size would
        # change the bytes written back out.
        if data is None:
            buffer = bytearray(self.SIZE_PARTY or self.SIZE_STORED)
        else:
            buffer = bytearray(data)
            minimum = self.SIZE_STORED or len(buffer)
            if len(buffer) < minimum:
                buffer.extend(bytes(minimum - len(buffer)))
        self.data = buffer
        self.japanese = japanese

    @property
    def is_party_size(self) -> bool:
        """True when the buffer carries the party-only stat block."""
        return self.SIZE_PARTY > self.SIZE_STORED and len(self.data) >= self.SIZE_PARTY

    # --- field access -------------------------------------------------------

    @classmethod
    def fields(cls) -> dict[str, Any]:
        return dict(cls._fields)

    @classmethod
    def field_names(cls) -> Iterator[str]:
        return iter(cls._fields)

    def __setattr__(self, name: str, value: Any) -> None:
        # A typo, or a field this port has not covered yet, would otherwise
        # become a silent instance attribute that never reaches the buffer.
        if (name not in self._INSTANCE_ATTRS
                and name not in self._fields
                and not hasattr(type(self), name)):
            raise AttributeError(
                f"{type(self).__name__} has no field {name!r}; "
                "assigning it would not change the underlying bytes"
            )
        object.__setattr__(self, name, value)

    def get(self, name: str) -> Any:
        return getattr(self, name)

    def set(self, name: str, value: Any) -> None:
        setattr(self, name, value)

    # --- string plumbing ----------------------------------------------------

    @property
    def string_generation(self) -> int:
        return self.STRING_GENERATION or self.FORMAT

    @property
    def bytes_per_char(self) -> int:
        """Width of one character in this format's text encoding."""
        if self.BIG_ENDIAN:
            return 2                    # the GameCube formats are UTF-16BE
        return 1 if self.string_generation <= 3 else 2

    @property
    def string_language(self) -> int:
        """Language id used to pick a per-language glyph table.

        Gen1/2 do not store a language in the record, so a Japanese buffer is
        the only signal that the Japanese glyph table applies.
        """
        stored = int(getattr(self, "language", 0) or 0)
        if stored:
            return stored
        return 1 if self.japanese else 0

    def decode_string(self, raw: bytes) -> str:
        return get_string(
            raw,
            self.string_generation,
            jp=self.japanese,
            big_endian=self.BIG_ENDIAN,
            language=self.string_language,
        )

    def encode_string(self, buffer: bytearray, value: str, max_chars: int,
                      option: StringConverterOption | None = None) -> int:
        return set_string(
            buffer,
            value,
            max_chars,
            self.string_generation,
            jp=self.japanese,
            big_endian=self.BIG_ENDIAN,
            language=self.string_language,
            option=option,
        )

    # --- buffer helpers -----------------------------------------------------

    def to_bytes(self) -> bytes:
        return bytes(self.data)

    def clone(self):
        return type(self)(bytes(self.data), japanese=self.japanese)

    def __len__(self) -> int:
        return len(self.data)

    def __eq__(self, other: object) -> bool:
        """Same format, same bytes, same out-of-buffer state.

        Comparing buffers alone made PK8, PK9 and PA9 interchangeable, since
        all three are 0x158 bytes; a zeroed one of each compared equal. That is
        the confusion ``SaveFile._check_entity`` exists to stop on the write
        path. Gen1/2 also keep the egg flag and the language outside the
        record, so two identical buffers can still be different Pokemon.
        """
        if type(self) is not type(other):
            return NotImplemented
        return (self.data == other.data
                and self.japanese == other.japanese
                and getattr(self, "is_egg", None) == getattr(other, "is_egg", None))

    #: Deliberately unhashable. Equality reads the buffer, and the buffer is
    #: what every setter writes to, so a hash taken now would be stale after
    #: the next assignment and the entity would be lost inside its own set.
    #: Key on ``to_bytes()`` when you need one.
    __hash__ = None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {len(self.data)} bytes>"
