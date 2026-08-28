"""Entity encryption: block shuffling and the LCRNG stream cipher.

Port of ``PKHeX.Core.PokeCrypto``. Every generation from 3 onward stores an
entity as a header plus four data blocks; the blocks are permuted by a value
derived from the PID and the payload is XORed with an LCRNG stream.
"""

from __future__ import annotations

from .binio import read_u16, read_u32, read_u32_be, write_u16

SIZE_1STORED = 33
SIZE_1PARTY = 44
SIZE_1JLIST = 59
SIZE_1ULIST = 69

SIZE_2STORED = 32
SIZE_2PARTY = 48
SIZE_2STADIUM = 60
SIZE_2JLIST = 63
SIZE_2ULIST = 73

SIZE_3STORED = 80
SIZE_3PARTY = 100
SIZE_3XSTORED = 196
SIZE_3CSTORED = 312
SIZE_3HEADER = 32
SIZE_3BLOCK = 12

SIZE_4STORED = 136
SIZE_4PARTY = 236
SIZE_4RSTORED = 164
SIZE_4BPARTY = 220
SIZE_4BLOCK = 32

SIZE_5STORED = 136
SIZE_5PARTY = 220

SIZE_6STORED = 0xE8
SIZE_6PARTY = 0x104
SIZE_6BLOCK = 56

BLOCK_COUNT = 4
SIZE_8BLOCK = 80
SIZE_8STORED = 8 + BLOCK_COUNT * SIZE_8BLOCK   # 0x148
SIZE_8PARTY = SIZE_8STORED + 0x10              # 0x158

SIZE_8ABLOCK = 88
SIZE_8ASTORED = 8 + BLOCK_COUNT * SIZE_8ABLOCK  # 0x168
SIZE_8APARTY = SIZE_8ASTORED + 0x10             # 0x178

# Permutation applied for each of the 24 shuffle values, plus a repeat of the
# first eight so a 5-bit shuffle value never needs a modulus.
BLOCK_POSITION = bytes((
    0, 1, 2, 3,  0, 1, 3, 2,  0, 2, 1, 3,  0, 3, 1, 2,
    0, 2, 3, 1,  0, 3, 2, 1,  1, 0, 2, 3,  1, 0, 3, 2,
    2, 0, 1, 3,  3, 0, 1, 2,  2, 0, 3, 1,  3, 0, 2, 1,
    1, 2, 0, 3,  1, 3, 0, 2,  2, 1, 0, 3,  3, 1, 0, 2,
    2, 3, 0, 1,  3, 2, 0, 1,  1, 2, 3, 0,  1, 3, 2, 0,
    2, 1, 3, 0,  3, 1, 2, 0,  2, 3, 1, 0,  3, 2, 1, 0,
    0, 1, 2, 3,  0, 1, 3, 2,  0, 2, 1, 3,  0, 3, 1, 2,
    0, 2, 3, 1,  0, 3, 2, 1,  1, 0, 2, 3,  1, 0, 3, 2,
))

BLOCK_POSITION_INVERT = bytes((
    0, 1, 2, 4,
    3, 5, 6, 7,
    12, 18, 13, 19,
    8, 10, 14, 20,
    16, 22, 9, 11,
    15, 21, 17, 23,
    0, 1, 2, 4,
    3, 5, 6, 7,
))


def crypt_array(data: bytearray, offset: int, length: int, seed: int) -> None:
    """XOR ``length`` bytes with the Gen4+ LCRNG keystream (2 bytes per step)."""
    seed &= 0xFFFFFFFF
    for i in range(offset, offset + length, 2):
        seed = (0x41C64E6D * seed + 0x00006073) & 0xFFFFFFFF
        write_u16(data, i, read_u16(data, i) ^ (seed >> 16))


def crypt_array3(data: bytearray, offset: int, length: int, seed: int) -> None:
    """XOR ``length`` bytes with a constant 32-bit key (Gen3 has no LCRNG step)."""
    key = (seed & 0xFFFFFFFF).to_bytes(4, "little")
    for i in range(length):
        data[offset + i] ^= key[i & 3]


def _shuffle(data: bytearray, offset: int, sv: int, block_size: int) -> None:
    """Reorder the four blocks starting at ``offset`` per shuffle value ``sv``."""
    if sv == 0:
        return
    order = BLOCK_POSITION[sv * BLOCK_COUNT: sv * BLOCK_COUNT + BLOCK_COUNT]
    blocks = [
        data[offset + i * block_size: offset + (i + 1) * block_size]
        for i in range(BLOCK_COUNT)
    ]
    for i, source in enumerate(order):
        start = offset + i * block_size
        data[start:start + block_size] = blocks[source]


def decrypt3(data: bytearray) -> None:
    pid = read_u32(data, 0)
    oid = read_u32(data, 4)
    crypt_array3(data, SIZE_3HEADER, SIZE_3STORED - SIZE_3HEADER, pid ^ oid)
    _shuffle(data, SIZE_3HEADER, pid % 24, SIZE_3BLOCK)


def encrypt3(data: bytearray) -> None:
    pid = read_u32(data, 0)
    oid = read_u32(data, 4)
    _shuffle(data, SIZE_3HEADER, BLOCK_POSITION_INVERT[pid % 24], SIZE_3BLOCK)
    crypt_array3(data, SIZE_3HEADER, SIZE_3STORED - SIZE_3HEADER, pid ^ oid)


def decrypt45(data: bytearray) -> None:
    pv = read_u32(data, 0)
    chk = read_u16(data, 6)
    crypt_array(data, 8, SIZE_4STORED - 8, chk)
    if len(data) > SIZE_4STORED:
        crypt_array(data, SIZE_4STORED, len(data) - SIZE_4STORED, pv)
    _shuffle(data, 8, (pv >> 13) & 31, SIZE_4BLOCK)


def encrypt45(data: bytearray) -> None:
    pv = read_u32(data, 0)
    chk = read_u16(data, 6)
    _shuffle(data, 8, BLOCK_POSITION_INVERT[(pv >> 13) & 31], SIZE_4BLOCK)
    crypt_array(data, 8, SIZE_4STORED - 8, chk)
    if len(data) > SIZE_4STORED:
        crypt_array(data, SIZE_4STORED, len(data) - SIZE_4STORED, pv)


def decrypt4be(data: bytearray) -> None:
    """Battle Revolution is big-endian and unencrypted at rest, but still shuffled."""
    _shuffle(data, 8, (read_u32_be(data, 0) >> 13) & 31, SIZE_4BLOCK)


def encrypt4be(data: bytearray) -> None:
    _shuffle(data, 8, BLOCK_POSITION_INVERT[(read_u32_be(data, 0) >> 13) & 31], SIZE_4BLOCK)


def decrypt67(data: bytearray) -> None:
    pv = read_u32(data, 0)
    crypt_array(data, 8, SIZE_6STORED - 8, pv)
    if len(data) > SIZE_6STORED:
        crypt_array(data, SIZE_6STORED, len(data) - SIZE_6STORED, pv)
    _shuffle(data, 8, (pv >> 13) & 31, SIZE_6BLOCK)


def encrypt67(data: bytearray) -> None:
    pv = read_u32(data, 0)
    _shuffle(data, 8, BLOCK_POSITION_INVERT[(pv >> 13) & 31], SIZE_6BLOCK)
    crypt_array(data, 8, SIZE_6STORED - 8, pv)
    if len(data) > SIZE_6STORED:
        crypt_array(data, SIZE_6STORED, len(data) - SIZE_6STORED, pv)


def decrypt8(data: bytearray) -> None:
    pv = read_u32(data, 0)
    crypt_array(data, 8, SIZE_8STORED - 8, pv)
    if len(data) > SIZE_8STORED:
        crypt_array(data, SIZE_8STORED, len(data) - SIZE_8STORED, pv)
    _shuffle(data, 8, (pv >> 13) & 31, SIZE_8BLOCK)


def encrypt8(data: bytearray) -> None:
    pv = read_u32(data, 0)
    _shuffle(data, 8, BLOCK_POSITION_INVERT[(pv >> 13) & 31], SIZE_8BLOCK)
    crypt_array(data, 8, SIZE_8STORED - 8, pv)
    if len(data) > SIZE_8STORED:
        crypt_array(data, SIZE_8STORED, len(data) - SIZE_8STORED, pv)


def decrypt8a(data: bytearray) -> None:
    pv = read_u32(data, 0)
    crypt_array(data, 8, SIZE_8ASTORED - 8, pv)
    if len(data) > SIZE_8ASTORED:
        crypt_array(data, SIZE_8ASTORED, len(data) - SIZE_8ASTORED, pv)
    _shuffle(data, 8, (pv >> 13) & 31, SIZE_8ABLOCK)


def encrypt8a(data: bytearray) -> None:
    pv = read_u32(data, 0)
    _shuffle(data, 8, BLOCK_POSITION_INVERT[(pv >> 13) & 31], SIZE_8ABLOCK)
    crypt_array(data, 8, SIZE_8ASTORED - 8, pv)
    if len(data) > SIZE_8ASTORED:
        crypt_array(data, SIZE_8ASTORED, len(data) - SIZE_8ASTORED, pv)


def add16(data: bytes, start: int = 0, end: int | None = None) -> int:
    """Sum of 16-bit little-endian words, truncated to 16 bits."""
    if end is None:
        end = len(data)
    return sum(read_u16(data, i) for i in range(start, end, 2)) & 0xFFFF


def is_encrypted3(data: bytes) -> bool:
    return add16(data, SIZE_3HEADER, SIZE_3STORED) != read_u16(data, 0x1C)


def is_encrypted45(data: bytes) -> bool:
    """Gen4/5 leaves the unused ribbon bits at 0x64 zeroed when decrypted."""
    return read_u32(data, 0x64) != 0


def is_encrypted67(data: bytes) -> bool:
    """Nickname and OT string terminators read zero when decrypted."""
    return read_u16(data, 0xC8) != 0 or read_u16(data, 0x58) != 0


def is_encrypted8(data: bytes) -> bool:
    return read_u16(data, 0x70) != 0 or read_u16(data, 0x110) != 0


def is_encrypted8a(data: bytes) -> bool:
    return read_u16(data, 0x78) != 0 or read_u16(data, 0x128) != 0


def decrypt_if_encrypted3(data: bytearray) -> None:
    if is_encrypted3(data):
        decrypt3(data)


def decrypt_if_encrypted45(data: bytearray) -> None:
    if is_encrypted45(data):
        decrypt45(data)


def decrypt_if_encrypted67(data: bytearray) -> None:
    if is_encrypted67(data):
        decrypt67(data)


def decrypt_if_encrypted8(data: bytearray) -> None:
    if is_encrypted8(data):
        decrypt8(data)


def decrypt_if_encrypted8a(data: bytearray) -> None:
    if is_encrypted8a(data):
        decrypt8a(data)


def decrypt_buffer45(data: bytes) -> bytearray:
    buffer = bytearray(data)
    decrypt_if_encrypted45(buffer)
    return buffer


def decrypt_buffer67(data: bytes) -> bytearray:
    buffer = bytearray(data)
    decrypt_if_encrypted67(buffer)
    return buffer


def decrypt_buffer8(data: bytes) -> bytearray:
    buffer = bytearray(data)
    decrypt_if_encrypted8(buffer)
    return buffer
