"""Byte-backed field descriptors.

Each descriptor owns one slice of an entity's buffer. Reading an attribute
decodes those bytes; assigning re-encodes them in place. Descriptors also carry
their PKHeX property name so JSON output stays recognizable to anyone who knows
the C# side.
"""

from __future__ import annotations

from typing import Any

from .. import binio


class Field:
    """Base descriptor. Subclasses implement ``decode``/``encode``."""

    kind = "field"

    def __init__(
        self,
        offset: int,
        *,
        pkhex_name: str = "",
        readonly: bool = False,
        enum: str | None = None,
        max_value: int | None = None,
    ) -> None:
        self.offset = offset
        self.pkhex_name = pkhex_name
        self.readonly = readonly
        self.enum = enum
        #: Upper bound applied on read, where the C# clamps a wider stored value.
        self.max_value = max_value
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name
        if not self.pkhex_name:
            self.pkhex_name = name

    def fits(self, obj: Any) -> bool:
        """Whether this field lies inside the record's buffer.

        A box slot is often stored-size, which leaves out the party-only stat
        block at the end. Asking for a field that is not there is a reasonable
        question with a reasonable answer, not a crash.
        """
        return self.offset + getattr(self, "size", 1) <= len(obj.data)

    def _absent(self, obj: Any) -> AttributeError:
        return AttributeError(
            f"{type(obj).__name__} has no {self.name}: the field sits at "
            f"0x{self.offset:X} but this record is only {len(obj.data)} bytes "
            "(a stored-size record has no party stat block)"
        )

    def __get__(self, obj: Any, owner: type | None = None) -> Any:
        if obj is None:
            return self
        if not self.fits(obj):
            raise self._absent(obj)
        return self.decode(obj)

    def __set__(self, obj: Any, value: Any) -> None:
        if self.readonly:
            raise AttributeError(f"{self.name} is derived and cannot be assigned")
        if not self.fits(obj):
            raise self._absent(obj)
        self.encode(obj, value)

    def decode(self, obj: Any) -> Any:
        raise NotImplementedError

    def encode(self, obj: Any, value: Any) -> None:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name} @0x{self.offset:X}>"


def _scalar(kind: str, reader, writer, size: int) -> type[Field]:
    class _Scalar(Field):
        pass

    _Scalar.kind = kind
    _Scalar.size = size
    def _decode(self, obj):
        value = reader(obj.data, self.offset)
        return value if self.max_value is None else min(value, self.max_value)

    _Scalar.decode = _decode
    _Scalar.encode = lambda self, obj, value: writer(obj.data, self.offset, int(value))
    _Scalar.__name__ = kind.upper()
    _Scalar.__qualname__ = _Scalar.__name__
    return _Scalar


U8 = _scalar("u8", binio.read_u8, binio.write_u8, 1)
I8 = _scalar("i8", binio.read_i8, binio.write_i8, 1)
U16 = _scalar("u16", binio.read_u16, binio.write_u16, 2)
I16 = _scalar("i16", binio.read_i16, binio.write_i16, 2)
U32 = _scalar("u32", binio.read_u32, binio.write_u32, 4)
I32 = _scalar("i32", binio.read_i32, binio.write_i32, 4)
U64 = _scalar("u64", binio.read_u64, binio.write_u64, 8)
U16BE = _scalar("u16be", binio.read_u16_be, binio.write_u16_be, 2)
U32BE = _scalar("u32be", binio.read_u32_be, binio.write_u32_be, 4)


class F32(Field):
    kind = "f32"
    size = 4

    def decode(self, obj: Any) -> float:
        return binio.read_f32(obj.data, self.offset)

    def encode(self, obj: Any, value: Any) -> None:
        binio.write_f32(obj.data, self.offset, float(value))


class Flag(Field):
    """A single bit within one byte."""

    kind = "flag"
    size = 1

    def __init__(self, offset: int, bit: int, **kwargs: Any) -> None:
        super().__init__(offset, **kwargs)
        self.bit = bit

    def decode(self, obj: Any) -> bool:
        return binio.get_flag(obj.data, self.offset, self.bit)

    def encode(self, obj: Any, value: Any) -> None:
        binio.set_flag(obj.data, self.offset, self.bit, bool(value))


class Bits(Field):
    """A masked, shifted run of bits within one byte."""

    kind = "bits"
    size = 1

    def __init__(self, offset: int, shift: int, mask: int, **kwargs: Any) -> None:
        super().__init__(offset, **kwargs)
        self.shift = shift
        self.mask = mask

    def decode(self, obj: Any) -> int:
        return binio.get_bits(obj.data, self.offset, self.shift, self.mask)

    def encode(self, obj: Any, value: Any) -> None:
        binio.set_bits(obj.data, self.offset, self.shift, self.mask, int(value))


class BoolByte(Field):
    """A whole byte used as a boolean, as the GameCube formats do."""

    kind = "boolbyte"
    size = 1

    def decode(self, obj: Any) -> bool:
        return obj.data[self.offset] != 0

    def encode(self, obj: Any, value: Any) -> None:
        obj.data[self.offset] = 1 if value else 0


class Span(Field):
    """A raw byte range, exposed as ``bytes`` and assignable from any buffer."""

    kind = "span"

    def __init__(self, offset: int, length: int, **kwargs: Any) -> None:
        super().__init__(offset, **kwargs)
        self.length = length

    @property
    def size(self) -> int:
        return self.length

    def decode(self, obj: Any) -> bytes:
        return bytes(obj.data[self.offset:self.offset + self.length])

    def encode(self, obj: Any, value: Any) -> None:
        raw = bytes(value)
        if len(raw) > self.length:
            raise ValueError(f"{self.name}: {len(raw)} bytes exceeds {self.length}")
        obj.data[self.offset:self.offset + len(raw)] = raw


class Str(Field):
    """Text stored in the entity's own encoding.

    The generation, language, and endianness come from the owning entity, so the
    same descriptor works for a Gen1 nickname and a Gen9 one.
    """

    kind = "string"

    def __init__(self, offset: int, length: int, *, max_chars: int | None = None,
                 **kwargs: Any) -> None:
        super().__init__(offset, **kwargs)
        self.length = length
        self.max_chars = max_chars

    @property
    def size(self) -> int:
        return self.length

    def decode(self, obj: Any) -> str:
        raw = bytes(obj.data[self.offset:self.offset + self.length])
        return obj.decode_string(raw)

    def encode(self, obj: Any, value: Any) -> None:
        view = bytearray(self.length)
        limit = self.max_chars
        if limit is None:
            # Leave room for the terminator, and account for encodings that
            # spend two bytes per character.
            width = obj.bytes_per_char
            limit = max(0, (self.length // width) - 1)
        obj.encode_string(view, str(value), limit)
        obj.data[self.offset:self.offset + self.length] = view


_PACKED_READERS = {1: binio.read_u8, 2: binio.read_u16, 4: binio.read_u32, 8: binio.read_u64}
_PACKED_WRITERS = {1: binio.write_u8, 2: binio.write_u16, 4: binio.write_u32, 8: binio.write_u64}


class PackedBits(Field):
    """Bits packed into a wider word, such as the six IVs inside one uint32."""

    kind = "packed_bits"

    def __init__(self, offset: int, shift: int, mask: int, base_size: int,
                 **kwargs: Any) -> None:
        super().__init__(offset, **kwargs)
        self.shift = shift
        self.mask = mask
        self.base_size = base_size

    @property
    def size(self) -> int:
        return self.base_size

    def _word(self, obj: Any) -> int:
        return _PACKED_READERS[self.base_size](obj.data, self.offset)

    def decode(self, obj: Any) -> int:
        return (self._word(obj) >> self.shift) & self.mask

    def encode(self, obj: Any, value: Any) -> None:
        word = self._word(obj)
        word &= ~(self.mask << self.shift)
        word |= (int(value) & self.mask) << self.shift
        _PACKED_WRITERS[self.base_size](obj.data, self.offset, word)


class PackedFlag(PackedBits):
    """A single bit inside a wider word."""

    kind = "packed_flag"

    def __init__(self, offset: int, shift: int, base_size: int, **kwargs: Any) -> None:
        super().__init__(offset, shift, 1, base_size, **kwargs)

    def decode(self, obj: Any) -> bool:
        return super().decode(obj) == 1

    def encode(self, obj: Any, value: Any) -> None:
        super().encode(obj, 1 if value else 0)
