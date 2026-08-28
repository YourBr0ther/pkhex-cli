"""Generation 3, 4, and 5 string encoding.

Gen3 is single-byte indexed with language-dependent quotation marks. Gen4 is
16-bit indexed through a shared international table plus a Korean extension
block. Gen5 drops the index table and stores UTF-16 directly, but keeps Gen4's
half-width gender glyphs and the 0xFFFF terminator.
"""

from __future__ import annotations

from ..binio import read_u16, write_u16
from . import tables
from .options import StringConverterOption

# --- Generation 3 -----------------------------------------------------------

G3_TERMINATOR_BYTE = 0xFF
G3_TERMINATOR = chr(G3_TERMINATOR_BYTE)
G3_QUOTE_LEFT_BYTE = 0xB1
G3_QUOTE_RIGHT_BYTE = 0xB2
G3_APOSTROPHE_BYTE = 0xB4

# --- Generation 4 -----------------------------------------------------------

G4_TERMINATOR = 0xFFFF
G4_KOR_START = 0x400
G4_SAVE_INVALID_AS = 0x1AC  # '?'
G4_APOSTROPHE = 0x1B3

# Half-width gender glyphs as stored by Gen4/5; normalized to the full-width
# forms for display so nicknames read as "Nidoran♂" rather than a private-use box.
HGM = "\u246D"  # rendered as ♂ by the game
HGF = "\u246E"  # rendered as ♀ by the game
FGM = "♂"
FGF = "♀"


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


def is_full_width_string(value: str) -> bool:
    """True when the string needs the full-width glyph set to render."""
    for char in value:
        if ord(char) >> 12 in (0, 0xE):
            continue
        if char in (FGF, FGM):
            continue
        return True
    return False


def _index_of(table: tuple[str, ...], char: str) -> int:
    try:
        return table.index(char)
    except ValueError:
        return -1


def get_quote_left(language: int) -> str:
    if language in (2, 4, 7):    # English, Italian, Spanish
        return "“"
    if language == 3:            # French
        return "«"
    if language == 5:            # German
        return "„"
    return "『"              # Japanese and anything unrecognized


def get_quote_right(language: int) -> str:
    if language in (2, 4, 7):
        return "”"
    if language == 3:
        return "»"
    if language == 5:
        return "“"
    return "』"


def get_string3(data: bytes, language: int) -> str:
    table = tables.G3_JP if language == 1 else tables.G3_EN
    result: list[str] = []
    for value in data:
        if value == G3_QUOTE_LEFT_BYTE:
            char = get_quote_left(language)
        elif value == G3_QUOTE_RIGHT_BYTE:
            char = get_quote_right(language)
        else:
            char = table[value]
        if char == G3_TERMINATOR:
            break
        result.append(normalize_gender_symbol(char))
    return "".join(result)


def _remap3(char: str, language: int) -> int:
    mapping = {
        "’": G3_APOSTROPHE_BYTE,
        "“": G3_QUOTE_LEFT_BYTE if language != 5 else G3_QUOTE_RIGHT_BYTE,
        "”": G3_QUOTE_RIGHT_BYTE,
        "«": G3_QUOTE_LEFT_BYTE,
        "»": G3_QUOTE_RIGHT_BYTE,
        "„": G3_QUOTE_LEFT_BYTE,
        "『": G3_QUOTE_LEFT_BYTE,
        "』": G3_QUOTE_RIGHT_BYTE,
    }
    return mapping.get(char, G3_TERMINATOR_BYTE)


def _try_get_index3(table: tuple[str, ...], char: str, language: int) -> int | None:
    index = _index_of(table, char)
    if index == -1 or char == "“":
        remapped = _remap3(char, language)
        return remapped if remapped != G3_TERMINATOR_BYTE else None
    return index if index != G3_TERMINATOR_BYTE else None


def set_string3(
    buffer: bytearray,
    value: str,
    max_length: int,
    language: int,
    option: StringConverterOption = StringConverterOption.CLEAR_FF,
) -> int:
    value = value[:max_length]
    if option is StringConverterOption.CLEAR_FF:
        buffer[:] = b"\xff" * len(buffer)
    elif option is StringConverterOption.CLEAR_ZERO:
        buffer[:] = bytes(len(buffer))

    jp = language == 1
    table = tables.G3_JP if jp else tables.G3_EN
    count = 0
    for char in value:
        if not jp:
            char = unnormalize_gender_symbol(char)
        index = _try_get_index3(table, char, language)
        if index is None:
            break
        buffer[count] = index
        count += 1
    if count < len(buffer):
        buffer[count] = G3_TERMINATOR_BYTE
        count += 1
    return count


def convert_value_to_char_g4(value: int) -> int:
    if value < len(tables.G4_INT):
        return ord(tables.G4_INT[value])
    index = value - G4_KOR_START
    if 0 <= index < len(tables.G4_KOR):
        return ord(tables.G4_KOR[index])
    return G4_TERMINATOR


def convert_char_to_value_g4(char: str) -> int:
    index = _index_of(tables.G4_INT, char)
    if index >= 0:
        return index
    index = _index_of(tables.G4_KOR, char)
    if index >= 0:
        return index + G4_KOR_START
    if char == "’":
        return G4_APOSTROPHE
    return G4_SAVE_INVALID_AS


def get_string4(data: bytes) -> str:
    result: list[str] = []
    for i in range(0, len(data) - 1, 2):
        value = read_u16(data, i)
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
        write_u16(buffer, i * 2, convert_char_to_value_g4(char))

    count = len(value) * 2
    if count == len(buffer):
        return count
    write_u16(buffer, count, G4_TERMINATOR)
    return count + 2


def get_string5(data: bytes) -> str:
    result: list[str] = []
    for i in range(0, len(data) - 1, 2):
        value = read_u16(data, i)
        if value in (G4_TERMINATOR, 0):
            break
        result.append(normalize_gender_symbol(chr(value)))
    return "".join(result)


def set_string5(
    buffer: bytearray,
    value: str,
    max_length: int,
    language: int,
    option: StringConverterOption = StringConverterOption.CLEAR_ZERO,
) -> int:
    value = value[:max_length]
    if option in (StringConverterOption.CLEAR_ZERO,
                  StringConverterOption.CLEAR_ZERO_SAFE_TERMINATE):
        buffer[:] = bytes(len(buffer))
    elif option is StringConverterOption.CLEAR_FF:
        buffer[:] = b"\xff" * len(buffer)

    half_width = language == 8 or not is_full_width_string(value)
    for i, char in enumerate(value):
        if half_width:
            char = unnormalize_gender_symbol(char)
        write_u16(buffer, i * 2, ord(char))

    count = len(value) * 2
    if count == len(buffer):
        return count
    write_u16(buffer, count, G4_TERMINATOR)
    if option is StringConverterOption.CLEAR_ZERO_SAFE_TERMINATE:
        write_u16(buffer, len(buffer) - 2, G4_TERMINATOR)
    return count + 2
