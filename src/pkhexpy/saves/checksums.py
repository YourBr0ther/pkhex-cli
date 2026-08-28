"""Checksum algorithms the games use over save data.

Port of ``PKHeX.Core.Checksums``. Which one applies depends on the generation:
Gen3 sums 32-bit words, Gen4/5 and the 3DS games use CRC-16 variants, and the
GameCube titles use big-endian sums.
"""

from __future__ import annotations

def crc16_ccitt(data: bytes) -> int:
    """Bitwise CRC-16-CCITT, as Gen4/5 and Gen6 blocks use."""
    top = 0xFF
    bot = 0xFF
    for byte in data:
        x = byte ^ top
        x ^= x >> 4
        top = (bot ^ (x >> 3) ^ (x << 4)) & 0xFF
        bot = (x ^ (x << 5)) & 0xFF
    return ((top << 8) | bot) & 0xFFFF


def _build_crc16_table() -> tuple[int, ...]:
    """The reflected CRC-16/ARC table PKHeX ships as a literal."""
    table = []
    for i in range(256):
        value = i
        for _ in range(8):
            value = (value >> 1) ^ (0xA001 if value & 1 else 0)
        table.append(value)
    return tuple(table)


CRC16_TABLE = _build_crc16_table()


def _crc16(data: bytes, initial: int) -> int:
    checksum = initial
    for byte in data:
        checksum = CRC16_TABLE[(byte ^ checksum) & 0xFF] ^ (checksum >> 8)
    return checksum & 0xFFFF


def crc16_invert(data: bytes) -> int:
    """Gen7 block checksum."""
    return (~_crc16(data, 0xFFFF)) & 0xFFFF


def crc16_noinvert(data: bytes) -> int:
    """Let's Go block checksum."""
    return _crc16(data, 0)


def checksum32(data: bytes, initial: int = 0) -> int:
    """Sum of 32-bit little-endian words, folded to 16 bits (Gen3 sectors)."""
    checksum = initial
    for i in range(0, len(data) - 3, 4):
        checksum = (checksum + int.from_bytes(data[i:i + 4], "little")) & 0xFFFFFFFF
    return (checksum + (checksum >> 16)) & 0xFFFF


def add16(data: bytes) -> int:
    """Sum of 16-bit little-endian words."""
    return sum(int.from_bytes(data[i:i + 2], "little")
               for i in range(0, len(data) - 1, 2)) & 0xFFFF


ALGORITHMS = {
    "crc16_ccitt": crc16_ccitt,
    "crc16_invert": crc16_invert,
    "crc16_noinvert": crc16_noinvert,
}
