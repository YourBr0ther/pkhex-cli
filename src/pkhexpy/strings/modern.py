"""Generation 6 through 9 string encoding.

These store UTF-16LE directly with a null terminator. Gen6/7 keep the gender
symbols in a private-use range so the 3DS font renders them half-width; Gen8/9
dropped that and use the real ♂/♀ codepoints, so no remapping happens there.
"""

from __future__ import annotations

from ..binio import read_u16, write_u16
from .gen345 import is_full_width_string
from .options import StringConverterOption

TERMINATOR = 0

# Private-use gender glyphs, as stored by the 3DS games.
HGM = "\uE08E"  # rendered as ♂
HGF = "\uE08F"  # rendered as ♀
FGM = "♂"
FGF = "♀"

# 3DS private-use glyphs and what they become when a Gen6/7 string moves to
# Gen8+ (HOME transfer). Index 0 is U+E081.
GLYPHS_78_START = 0xE081
GLYPHS_78 = (
    # 0xE081-0xE087 -> ideographic space
    "\u3000", "\u3000", "\u3000", "\u3000", "\u3000", "\u3000", "\u3000",
    # 0xE088-0xE08C have no Gen8 equivalent and stay as they are
    "\uE088", "\uE089", "\uE08A", "\uE08B", "\uE08C",
    "\u2026", "\u2642", "\u2640", "\u2660", "\u2663", "\u2665", "\u2666",
    "\u2605", "\u25CE", "\u25CB", "\u25A1", "\u25B3", "\u25C7", "\u266A",
    "\u2600", "\u2601", "\u2602", "\u2603",
    # 0xE09F-0xE0A5 -> plain space
    " ", " ", " ", " ", " ", " ", " ",
)


def normalize_gender_symbol(char: str) -> str:
    if char == HGM:
        return FGM
    if char == HGF:
        return FGF
    return char


def unnormalize_gender_symbol(char: str, full_width: bool = False) -> str:
    if full_width:
        return char
    if char == FGM:
        return HGM
    if char == FGF:
        return HGF
    return char


def _read_utf16(data: bytes) -> list[int]:
    values: list[int] = []
    for i in range(0, len(data) - 1, 2):
        value = read_u16(data, i)
        if value == TERMINATOR:
            break
        values.append(value)
    return values


def get_string6(data: bytes) -> str:
    return "".join(normalize_gender_symbol(chr(v)) for v in _read_utf16(data))


# Gen7 uses the same encoding as Gen6.
get_string7 = get_string6


def get_string8(data: bytes) -> str:
    """Gen8/9 store the real gender codepoints, so no glyph remapping."""
    return "".join(chr(v) for v in _read_utf16(data))


def _write_utf16(buffer: bytearray, value: str) -> int:
    for i, char in enumerate(value):
        write_u16(buffer, i * 2, ord(char))
    count = len(value) * 2
    if count == len(buffer):
        return count
    write_u16(buffer, count, TERMINATOR)
    return count + 2


def set_string6(
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
    if half_width:
        value = "".join(unnormalize_gender_symbol(c) for c in value)
    return _write_utf16(buffer, value)


set_string7 = set_string6


def set_string8(
    buffer: bytearray,
    value: str,
    max_length: int,
    option: StringConverterOption = StringConverterOption.CLEAR_ZERO,
) -> int:
    value = value[:max_length]
    if option is StringConverterOption.CLEAR_ZERO:
        buffer[:] = bytes(len(buffer))
    return _write_utf16(buffer, value)


def transfer_glyphs_78(value: str) -> str:
    """Remap 3DS private-use glyphs when a string moves to the Switch games."""
    out: list[str] = []
    modified = False
    for char in value:
        index = ord(char) - GLYPHS_78_START
        if 0 <= index < len(GLYPHS_78):
            replacement = GLYPHS_78[index]
            modified = modified or replacement != char
            out.append(replacement)
        else:
            out.append(char)
    result = "".join(out)
    # A replacement trims surrounding half-width spaces, so a name made only of
    # full-width spaces survives while a padded one does not gain leading blanks.
    return result.strip(" ") if modified else result
