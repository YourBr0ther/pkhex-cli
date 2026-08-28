"""Generation 6 through 9 string encoding.

These store UTF-16LE directly with a null terminator. Gen6/7 keep the gender
symbols in a private-use range so the 3DS font renders them half-width; Gen8/9
dropped that and use the real ♂/♀ codepoints, so no remapping happens there.
"""

from __future__ import annotations

from ..binio import read_u16, write_u16
from . import tables
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


# Gen7 mapped un-nicknamed Chinese species names into a private-use block so one
# font could serve both Traditional and Simplified. The ranges below carve that
# block up; later games use separate fonts and dropped the scheme.
ZH_START = 0xE800
ZH_SIMPLIFIED = (0xE800, 0xEB0E)
ZH_TRADITIONAL = (0xEB0F, 0xEE1D)
ZH_SIMPLIFIED_USUM = (0xEE1E, 0xEE21)
ZH_TRADITIONAL_USUM = (0xEE22, 0xEE26)
ZH_END = ZH_TRADITIONAL_USUM[1]


def is_zh_private(value: int) -> bool:
    return ZH_START <= value <= ZH_END


def zh_to_unicode(value: int) -> str:
    """Map a Gen7 private-use codepoint back to the character it displays."""
    return tables.G7_ZH[value - ZH_START]


def _zh_span(start: int, end: int) -> tuple[int, ...]:
    return tuple(range(start - ZH_START, end - ZH_START + 1))


def unicode_to_zh(char: str, traditional: bool) -> str:
    """Map a character into Gen7's private-use block, if it lives there."""
    if traditional:
        order = (ZH_TRADITIONAL, ZH_TRADITIONAL_USUM)
    else:
        order = (ZH_SIMPLIFIED, ZH_SIMPLIFIED_USUM)
    for start, end in order:
        for index in _zh_span(start, end):
            if tables.G7_ZH[index] == char:
                return chr(ZH_START + index)
    return char


def get_string7(data: bytes) -> str:
    """Gen7 text, with the private-use Chinese block mapped back to Unicode."""
    out = []
    for value in _read_utf16(data):
        if is_zh_private(value):
            out.append(zh_to_unicode(value))
        else:
            out.append(normalize_gender_symbol(chr(value)))
    return "".join(out)


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


#: LanguageID values for Simplified and Traditional Chinese.
CHINESE_SIMPLIFIED = 9
CHINESE_TRADITIONAL = 10


def set_string7(
    buffer: bytearray,
    value: str,
    max_length: int,
    language: int,
    option: StringConverterOption = StringConverterOption.CLEAR_ZERO,
) -> int:
    """Gen7 text, mapping Chinese characters back into the private-use block."""
    if language in (CHINESE_SIMPLIFIED, CHINESE_TRADITIONAL):
        traditional = language == CHINESE_TRADITIONAL
        value = "".join(unicode_to_zh(c, traditional) for c in value)
    return set_string6(buffer, value, max_length, language, option)


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
