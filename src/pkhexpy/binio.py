"""Little/big-endian primitives over ``bytearray`` buffers.

PKHeX's C# reads and writes through ``BinaryPrimitives`` on a ``Span<byte>``;
these are the direct equivalents, kept free-standing so field descriptors can
reference them as plain functions.
"""

from __future__ import annotations

import struct

Buffer = bytearray


def _u(data: bytes, offset: int, size: int, big: bool = False) -> int:
    return int.from_bytes(data[offset:offset + size], "big" if big else "little")


def _w(data: Buffer, offset: int, size: int, value: int, big: bool = False) -> None:
    data[offset:offset + size] = (value & ((1 << (size * 8)) - 1)).to_bytes(
        size, "big" if big else "little"
    )


def read_u8(data: bytes, offset: int) -> int:
    return data[offset]


def write_u8(data: Buffer, offset: int, value: int) -> None:
    data[offset] = value & 0xFF


def read_i8(data: bytes, offset: int) -> int:
    value = data[offset]
    return value - 0x100 if value >= 0x80 else value


def write_i8(data: Buffer, offset: int, value: int) -> None:
    data[offset] = value & 0xFF


def read_u16(data: bytes, offset: int) -> int:
    return _u(data, offset, 2)


def write_u16(data: Buffer, offset: int, value: int) -> None:
    _w(data, offset, 2, value)


def read_i16(data: bytes, offset: int) -> int:
    value = _u(data, offset, 2)
    return value - 0x10000 if value >= 0x8000 else value


def write_i16(data: Buffer, offset: int, value: int) -> None:
    _w(data, offset, 2, value)


def read_u32(data: bytes, offset: int) -> int:
    return _u(data, offset, 4)


def write_u32(data: Buffer, offset: int, value: int) -> None:
    _w(data, offset, 4, value)


def read_i32(data: bytes, offset: int) -> int:
    value = _u(data, offset, 4)
    return value - 0x100000000 if value >= 0x80000000 else value


def write_i32(data: Buffer, offset: int, value: int) -> None:
    _w(data, offset, 4, value)


def read_u64(data: bytes, offset: int) -> int:
    return _u(data, offset, 8)


def write_u64(data: Buffer, offset: int, value: int) -> None:
    _w(data, offset, 8, value)


def read_u16_be(data: bytes, offset: int) -> int:
    return _u(data, offset, 2, big=True)


def write_u16_be(data: Buffer, offset: int, value: int) -> None:
    _w(data, offset, 2, value, big=True)


def read_u32_be(data: bytes, offset: int) -> int:
    return _u(data, offset, 4, big=True)


def write_u32_be(data: Buffer, offset: int, value: int) -> None:
    _w(data, offset, 4, value, big=True)


def read_f32(data: bytes, offset: int) -> float:
    return struct.unpack_from("<f", data, offset)[0]


def write_f32(data: Buffer, offset: int, value: float) -> None:
    struct.pack_into("<f", data, offset, value)


def get_bits(data: bytes, offset: int, shift: int, mask: int) -> int:
    return (data[offset] >> shift) & mask


def set_bits(data: Buffer, offset: int, shift: int, mask: int, value: int) -> None:
    cleared = data[offset] & ~(mask << shift) & 0xFF
    data[offset] = cleared | ((value & mask) << shift)


def get_flag(data: bytes, offset: int, bit: int) -> bool:
    return (data[offset] >> bit) & 1 == 1


def set_flag(data: Buffer, offset: int, bit: int, value: bool) -> None:
    if value:
        data[offset] |= 1 << bit
    else:
        data[offset] &= ~(1 << bit) & 0xFF
