"""GameCube-era string encoding (Colosseum, XD, Battle Revolution).

These titles are big-endian. Gen3 GC stores plain UTF-16BE with a null
terminator; Gen4 GC (Battle Revolution) keeps the DS index table but reads it
big-endian.
"""

from __future__ import annotations

from ..binio import read_u16_be, write_u16_be
from .gen345 import (
    G4_TERMINATOR,
    convert_char_to_value_g4,
    convert_value_to_char_g4,
    is_full_width_string,
    normalize_gender_symbol,
    unnormalize_gender_symbol,
)
from .options import StringConverterOption


def get_string3(data: bytes) -> str:
    result: list[str] = []
    for i in range(0, len(data) - 1, 2):
        value = read_u16_be(data, i)
        if value == 0:
            break
        result.append(chr(value))
    return "".join(result)


def set_string3(
    buffer: bytearray,
    value: str,
    max_length: int,
    option: StringConverterOption = StringConverterOption.CLEAR_ZERO,
) -> int:
    value = value[:max_length]
    if option is StringConverterOption.CLEAR_ZERO:
        buffer[:] = bytes(len(buffer))
    for i, char in enumerate(value):
        write_u16_be(buffer, i * 2, ord(char))
    count = len(value) * 2
    if count == len(buffer):
        return count
    write_u16_be(buffer, count, 0)
    return count + 2


def get_string4(data: bytes) -> str:
    result: list[str] = []
    for i in range(0, len(data) - 1, 2):
        value = read_u16_be(data, i)
        if value == G4_TERMINATOR:
            break
        result.append(normalize_gender_symbol(chr(convert_value_to_char_g4(value))))
    return "".join(result)


def set_string4(
    buffer: bytearray,
    value: str,
    max_length: int,
    language: int,
    option: StringConverterOption = StringConverterOption.CLEAR_ZERO,
) -> int:
    value = value[:max_length]
    if option is StringConverterOption.CLEAR_ZERO:
        buffer[:] = bytes(len(buffer))
    half_width = language == 8 or not is_full_width_string(value)  # Korean
    for i, char in enumerate(value):
        if half_width:
            char = unnormalize_gender_symbol(char)
        write_u16_be(buffer, i * 2, convert_char_to_value_g4(char))
    count = len(value) * 2
    if count == len(buffer):
        return count
    write_u16_be(buffer, count, G4_TERMINATOR)
    return count + 2


def get_string4_unicode(data: bytes) -> str:
    """Pokemon Ranch save strings are plain UTF-16BE, not index-table encoded."""
    return get_string3(data)


def set_string4_unicode(
    buffer: bytearray,
    value: str,
    max_length: int,
    option: StringConverterOption = StringConverterOption.CLEAR_ZERO,
) -> int:
    return set_string3(buffer, value, max_length, option)
