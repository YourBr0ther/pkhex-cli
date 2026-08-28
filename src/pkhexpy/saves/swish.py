"""Block storage for the Switch-era saves (Sword/Shield onward).

Instead of fixed offsets, these saves are a flat list of key-addressed blocks.
Each block is XORed with a keystream derived from its own key, and the whole
file is then XORed with a fixed 0x7F-byte pad and signed with SHA-256 over a
salted payload.

Port of ``PKHeX.Core.SwishCrypto``, ``SCBlock``, and ``SCXorShift32``.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from enum import IntEnum

from ..binio import read_i32, read_u32, write_i32, write_u32

SIZE_HASH = 32

INTRO_HASH = bytes((
    0x9E, 0xC9, 0x9C, 0xD7, 0x0E, 0xD3, 0x3C, 0x44, 0xFB, 0x93, 0x03, 0xDC, 0xEB, 0x39, 0xB4, 0x2A,
    0x19, 0x47, 0xE9, 0x63, 0x4B, 0xA2, 0x33, 0x44, 0x16, 0xBF, 0x82, 0xA2, 0xBA, 0x63, 0x55, 0xB6,
    0x3D, 0x9D, 0xF2, 0x4B, 0x5F, 0x7B, 0x6A, 0xB2, 0x62, 0x1D, 0xC2, 0x1B, 0x68, 0xE5, 0xC8, 0xB5,
    0x3A, 0x05, 0x90, 0x00, 0xE8, 0xA8, 0x10, 0x3D, 0xE2, 0xEC, 0xF0, 0x0C, 0xB2, 0xED, 0x4F, 0x6D,
))

OUTRO_HASH = bytes((
    0xD6, 0xC0, 0x1C, 0x59, 0x8B, 0xC8, 0xB8, 0xCB, 0x46, 0xE1, 0x53, 0xFC, 0x82, 0x8C, 0x75, 0x75,
    0x13, 0xE0, 0x45, 0xDF, 0x32, 0x69, 0x3C, 0x75, 0xF0, 0x59, 0xF8, 0xD9, 0xA2, 0x5F, 0xB2, 0x17,
    0xE0, 0x80, 0x52, 0xDB, 0xEA, 0x89, 0x73, 0x99, 0x75, 0x79, 0xAF, 0xCB, 0x2E, 0x80, 0x07, 0xE6,
    0xF1, 0x26, 0xE0, 0x03, 0x0A, 0xE6, 0x6F, 0xF6, 0x41, 0xBF, 0x7E, 0x59, 0xC2, 0xAE, 0x55, 0xFD,
))

# The pad is 0x7F bytes; PKHeX stores it padded to 0x80 for vectorization.
STATIC_XORPAD = bytes((
    0xA0, 0x92, 0xD1, 0x06, 0x07, 0xDB, 0x32, 0xA1, 0xAE, 0x01, 0xF5, 0xC5, 0x1E, 0x84, 0x4F, 0xE3,
    0x53, 0xCA, 0x37, 0xF4, 0xA7, 0xB0, 0x4D, 0xA0, 0x18, 0xB7, 0xC2, 0x97, 0xDA, 0x5F, 0x53, 0x2B,
    0x75, 0xFA, 0x48, 0x16, 0xF8, 0xD4, 0x8A, 0x6F, 0x61, 0x05, 0xF4, 0xE2, 0xFD, 0x04, 0xB5, 0xA3,
    0x0F, 0xFC, 0x44, 0x92, 0xCB, 0x32, 0xE6, 0x1B, 0xB9, 0xB1, 0x2E, 0x01, 0xB0, 0x56, 0x53, 0x36,
    0xD2, 0xD1, 0x50, 0x3D, 0xDE, 0x5B, 0x2E, 0x0E, 0x52, 0xFD, 0xDF, 0x2F, 0x7B, 0xCA, 0x63, 0x50,
    0xA4, 0x67, 0x5D, 0x23, 0x17, 0xC0, 0x52, 0xE1, 0xA6, 0x30, 0x7C, 0x2B, 0xB6, 0x70, 0x36, 0x5B,
    0x2A, 0x27, 0x69, 0x33, 0xF5, 0x63, 0x7B, 0x36, 0x3F, 0x26, 0x9B, 0xA3, 0xED, 0x7A, 0x53, 0x00,
    0xA4, 0x48, 0xB3, 0x50, 0x9E, 0x14, 0xA0, 0x52, 0xDE, 0x7E, 0x10, 0x2B, 0x1B, 0x77, 0x6E,
))

assert len(STATIC_XORPAD) == 0x7F


class SCTypeCode(IntEnum):
    NONE = 0
    BOOL1 = 1      # stored false
    BOOL2 = 2      # stored true
    BOOL3 = 3      # array element boolean
    OBJECT = 4
    ARRAY = 5
    BYTE = 8
    UINT16 = 9
    UINT32 = 10
    UINT64 = 11
    SBYTE = 12
    INT16 = 13
    INT32 = 14
    INT64 = 15
    SINGLE = 16
    DOUBLE = 17

    @property
    def is_boolean(self) -> bool:
        return self in (SCTypeCode.BOOL1, SCTypeCode.BOOL2, SCTypeCode.BOOL3)

    @property
    def size(self) -> int:
        return _TYPE_SIZES[self]


_TYPE_SIZES = {
    SCTypeCode.BOOL3: 1,
    SCTypeCode.BYTE: 1, SCTypeCode.SBYTE: 1,
    SCTypeCode.UINT16: 2, SCTypeCode.INT16: 2,
    SCTypeCode.UINT32: 4, SCTypeCode.INT32: 4, SCTypeCode.SINGLE: 4,
    SCTypeCode.UINT64: 8, SCTypeCode.INT64: 8, SCTypeCode.DOUBLE: 8,
}

_STRUCT_FORMATS = {
    SCTypeCode.BYTE: "<B", SCTypeCode.SBYTE: "<b",
    SCTypeCode.UINT16: "<H", SCTypeCode.INT16: "<h",
    SCTypeCode.UINT32: "<I", SCTypeCode.INT32: "<i",
    SCTypeCode.UINT64: "<Q", SCTypeCode.INT64: "<q",
    SCTypeCode.SINGLE: "<f", SCTypeCode.DOUBLE: "<d",
}


class SCXorShift32:
    """Keystream generator seeded from a block key, yielding one byte at a time."""

    __slots__ = ("_state", "_counter")

    def __init__(self, seed: int) -> None:
        state = seed & 0xFFFFFFFF
        for _ in range(bin(state).count("1")):
            state = self._advance(state)
        self._state = state
        self._counter = 0

    @staticmethod
    def _advance(state: int) -> int:
        state ^= (state << 2) & 0xFFFFFFFF
        state ^= state >> 15
        state ^= (state << 13) & 0xFFFFFFFF
        return state & 0xFFFFFFFF

    def next(self) -> int:
        result = (self._state >> (self._counter << 3)) & 0xFF
        if self._counter == 3:
            self._state = self._advance(self._state)
            self._counter = 0
        else:
            self._counter += 1
        return result

    def next32(self) -> int:
        return self.next() | (self.next() << 8) | (self.next() << 16) | (self.next() << 24)

    def keystream(self, length: int) -> bytes:
        """Take ``length`` bytes of keystream.

        The generator yields four bytes per state advance, so whole words come
        out in one step once the current partial word is drained.
        """
        out = bytearray()
        while self._counter and len(out) < length:
            out.append(self.next())
        remaining = length - len(out)
        for _ in range(remaining // 4):
            out += self._state.to_bytes(4, "little")
            self._state = self._advance(self._state)
        while len(out) < length:
            out.append(self.next())
        return bytes(out)

    def crypt(self, data: bytearray) -> None:
        """XOR a buffer with the keystream, in place."""
        length = len(data)
        if not length:
            return
        # One big-integer XOR beats a per-byte Python loop by a wide margin.
        mixed = int.from_bytes(data, "little") ^ int.from_bytes(
            self.keystream(length), "little")
        data[:] = mixed.to_bytes(length, "little")


@dataclass
class SCBlock:
    """One key-addressed block of save data."""

    key: int
    type: SCTypeCode
    data: bytearray = field(default_factory=bytearray)
    sub_type: SCTypeCode = SCTypeCode.NONE

    @property
    def has_value(self) -> bool:
        """True when the block holds a single primitive rather than bytes."""
        return self.type > SCTypeCode.ARRAY

    def get_value(self):
        if self.type.is_boolean:
            return self.type == SCTypeCode.BOOL2
        if not self.has_value:
            raise TypeError(f"block {self.key:08X} of type {self.type.name} has no scalar value")
        return struct.unpack_from(_STRUCT_FORMATS[self.type], self.data, 0)[0]

    def set_value(self, value) -> None:
        if self.type.is_boolean:
            self.type = SCTypeCode.BOOL2 if value else SCTypeCode.BOOL1
            return
        if not self.has_value:
            raise TypeError(f"block {self.key:08X} of type {self.type.name} has no scalar value")
        struct.pack_into(_STRUCT_FORMATS[self.type], self.data, 0, value)

    def serialized_length(self) -> int:
        length = 1 + 4                      # key and type byte
        if self.type == SCTypeCode.OBJECT:
            length += 4                     # byte-count prefix
        elif self.type == SCTypeCode.ARRAY:
            length += 5                     # entry-count prefix and subtype byte
        return length + len(self.data)


def crypt_static_xorpad(data: bytearray) -> None:
    """XOR the payload with the repeating 0x7F-byte pad, in place."""
    length = len(data)
    if not length:
        return
    repeats = -(-length // len(STATIC_XORPAD))
    pad = (STATIC_XORPAD * repeats)[:length]
    mixed = int.from_bytes(data, "little") ^ int.from_bytes(pad, "little")
    data[:] = mixed.to_bytes(length, "little")


def compute_hash(payload: bytes) -> bytes:
    digest = hashlib.sha256()
    digest.update(INTRO_HASH)
    digest.update(payload)
    digest.update(OUTRO_HASH)
    return digest.digest()


def is_hash_valid(data: bytes) -> bool:
    """Whether the trailing SHA-256 matches the salted payload."""
    if len(data) <= SIZE_HASH:
        return False
    return compute_hash(bytes(data[:-SIZE_HASH])) == bytes(data[-SIZE_HASH:])


def read_block(data: bytes, offset: int) -> tuple[SCBlock, int]:
    key = read_u32(data, offset)
    offset += 4
    xk = SCXorShift32(key)
    type_code = SCTypeCode(data[offset] ^ xk.next())
    offset += 1

    if type_code.is_boolean:
        return SCBlock(key, type_code), offset

    if type_code == SCTypeCode.OBJECT:
        count = (read_i32(data, offset) ^ xk.next32()) & 0xFFFFFFFF
        offset += 4
        raw = bytearray(data[offset:offset + count])
        offset += count
        xk.crypt(raw)
        return SCBlock(key, type_code, raw), offset

    if type_code == SCTypeCode.ARRAY:
        entries = (read_i32(data, offset) ^ xk.next32()) & 0xFFFFFFFF
        offset += 4
        sub = SCTypeCode(data[offset] ^ xk.next())
        offset += 1
        count = entries * sub.size
        raw = bytearray(data[offset:offset + count])
        offset += count
        xk.crypt(raw)
        return SCBlock(key, type_code, raw, sub), offset

    count = type_code.size
    raw = bytearray(data[offset:offset + count])
    offset += count
    xk.crypt(raw)
    return SCBlock(key, type_code, raw), offset


def write_block(block: SCBlock, out: bytearray) -> None:
    xk = SCXorShift32(block.key)
    start = len(out)
    out.extend(bytes(4))
    write_u32(out, start, block.key)
    out.append(int(block.type) ^ xk.next())

    if block.type == SCTypeCode.OBJECT:
        at = len(out)
        out.extend(bytes(4))
        write_i32(out, at, len(block.data) ^ xk.next32())
    elif block.type == SCTypeCode.ARRAY:
        at = len(out)
        out.extend(bytes(4))
        write_i32(out, at, (len(block.data) // block.sub_type.size) ^ xk.next32())
        out.append(int(block.sub_type) ^ xk.next())

    if block.data:
        payload = bytearray(block.data)
        xk.crypt(payload)
        out += payload


def decrypt(data: bytes) -> list[SCBlock]:
    """Unpack an encrypted Switch-era save into its blocks."""
    payload = bytearray(data[:-SIZE_HASH])
    crypt_static_xorpad(payload)
    payload = bytes(payload)

    blocks: list[SCBlock] = []
    offset = 0
    length = len(payload)
    while offset < length:
        block, offset = read_block(payload, offset)
        blocks.append(block)
    return blocks


def encrypt(blocks: list[SCBlock]) -> bytes:
    """Pack blocks back into an encrypted, signed save file."""
    out = bytearray()
    for block in blocks:
        write_block(block, out)
    crypt_static_xorpad(out)
    return bytes(out) + compute_hash(bytes(out))


FNV_PRIME_64 = 0x00000100000001B3
FNV_OFFSET_64 = 0xCBF29CE484222645


def fnv1a_64(text: str | bytes) -> int:
    """FNV-1a over a name's UTF-16 code units, or over raw bytes."""
    values = [ord(c) for c in text] if isinstance(text, str) else text
    hash_value = FNV_OFFSET_64
    for value in values:
        hash_value = ((hash_value ^ value) * FNV_PRIME_64) & 0xFFFFFFFFFFFFFFFF
    return hash_value


def block_key(name: str) -> int:
    """The key a block is stored under, derived from its name in the game.

    The hardcoded keys elsewhere in this package all come from this, so it is
    how you look up a block the port does not already name.
    """
    return fnv1a_64(name) & 0xFFFFFFFF
