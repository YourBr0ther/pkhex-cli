"""Generation 1 and 2 string encoding, including Korean Gold/Silver.

Gen1/2 use a single-byte index into a per-language glyph table. Korean GS
instead uses a two-byte scheme: a lead byte of 0x01-0x0B selects one of eleven
Hangul tables, and anything above that indexes the single-byte table directly.
"""

from __future__ import annotations

from . import tables
from .options import StringConverterOption

TERMINATOR = "\0"
TERMINATOR_CODE = 0x50
TERMINATOR_ZERO = 0x00
TRADE_OT_CODE = 0x5D
SPACE_CODE = 0x7F
TRADE_OT = "*"
LINE_BREAK_CODE = 0x59

# Hiragana the user may type that the tables only hold in their dakuten-less
# form; adding 0x60 to the codepoint reaches the entry that does exist.
HIRAGANA_REMAP = "べぺへり"

KOR_TABLE_INVALID = 0
KOR_TABLE_MIN = 1
KOR_TABLE_MAX = 11

_KOR_TABLES = (
    tables.G2_KOR_0, tables.G2_KOR_1, tables.G2_KOR_2, tables.G2_KOR_3,
    tables.G2_KOR_4, tables.G2_KOR_5, tables.G2_KOR_6, tables.G2_KOR_7,
    tables.G2_KOR_8, tables.G2_KOR_9, tables.G2_KOR_A, tables.G2_KOR_B,
)


def _index_of(table: tuple[str, ...], char: str) -> int:
    try:
        return table.index(char)
    except ValueError:
        return -1


def get_dict_g1(jp: bool) -> tuple[str, ...]:
    return tables.G1_JP if jp else tables.G1_EN


def get_dict_g2(language: int) -> tuple[str, ...]:
    if language == 1:            # Japanese
        return tables.G2_JP
    if language in (3, 5):       # French, and German, which shares the table
        return tables.G2_FRE
    if language in (4, 7):       # Italian, and Spanish, which shares the table
        return tables.G2_ITA
    return tables.G2_EN


def is_hangul_data(data: bytes) -> bool:
    """Korean strings always start with a table-select byte of 0x00-0x0B."""
    return len(data) > 0 and data[0] <= 0x0B


def is_hangul_text(value: str) -> bool:
    if not value:
        return False
    first = value[0]
    return (
        "가" <= first <= "힯"
        or "㄰" <= first <= "㆏"
        or first == "　"
    )


def get_string_kor(data: bytes) -> str:
    if not data:
        return ""
    if data[0] == TRADE_OT_CODE:
        return TRADE_OT

    result: list[str] = []
    i = 0
    while i < len(data):
        value = data[i]
        if value == KOR_TABLE_INVALID:
            break
        if value > KOR_TABLE_MAX:
            table = _KOR_TABLES[0]
        else:
            i += 1
            if i == len(data):
                break
            table = _KOR_TABLES[value]
            value = data[i]
        char = table[value]
        if char == TERMINATOR:
            break
        result.append(char)
        i += 1
    return "".join(result)


def _get_korean_char(char: str) -> tuple[int, int]:
    for t in range(KOR_TABLE_MIN, KOR_TABLE_MAX + 1):
        index = _index_of(_KOR_TABLES[t], char)
        if index != -1:
            return t, index
    return KOR_TABLE_INVALID, 0


def set_string_kor(
    buffer: bytearray,
    value: str,
    max_length: int,
    option: StringConverterOption = StringConverterOption.CLEAR_50,
) -> int:
    _condition_buffer(buffer, option)
    if not value:
        return 0
    if value[0] == TRADE_OT:
        buffer[0] = TRADE_OT_CODE
        buffer[1] = TERMINATOR_CODE
        return 2

    value = value[:max_length]
    count = 0
    for char in value:
        table, val = _get_korean_char(char)
        if table != KOR_TABLE_INVALID:
            if count + 2 > len(buffer):
                break
            buffer[count] = table
            buffer[count + 1] = val
            count += 2
        else:
            index = _index_of(_KOR_TABLES[0], char)
            if index in (-1, TERMINATOR_CODE):
                break
            if count + 1 > len(buffer):
                break
            buffer[count] = index
            count += 1
    if count < len(value):
        buffer[count] = TERMINATOR_CODE
        count += 1
    return count


def _condition_buffer(buffer: bytearray, option: StringConverterOption) -> None:
    if option is StringConverterOption.CLEAR_ZERO:
        buffer[:] = bytes(len(buffer))
    elif option is StringConverterOption.CLEAR_50:
        buffer[:] = bytes([TERMINATOR_CODE]) * len(buffer)
    elif option is StringConverterOption.CLEAR_7F:
        buffer[:] = bytes([SPACE_CODE]) * len(buffer)


def _load(data: bytes, table: tuple[str, ...]) -> str:
    if not data:
        return ""
    if data[0] == TRADE_OT_CODE:
        return TRADE_OT
    result: list[str] = []
    for value in data:
        char = table[value]
        if char == TERMINATOR:
            break
        result.append(char)
    return "".join(result)


def _try_get_index(table: tuple[str, ...], char: str) -> int | None:
    index = _index_of(table, char)
    if index == -1:
        if char in HIRAGANA_REMAP:
            # The dakuten-less form is what the table actually holds.
            remapped = _index_of(table, chr(ord(char) + 0x60))
            return remapped if remapped > 0 else None
        return None
    # Index 0 is the terminator; a user should never be able to enter it.
    return index if index != 0 else None


def _set(
    buffer: bytearray,
    value: str,
    max_length: int,
    table: tuple[str, ...],
    option: StringConverterOption,
) -> int:
    _condition_buffer(buffer, option)
    if not value:
        return 0
    if value[0] == TRADE_OT:
        buffer[0] = TRADE_OT_CODE
        buffer[1] = TERMINATOR_CODE
        return 2

    value = value[:max_length]
    count = 0
    for char in value:
        index = _try_get_index(table, char)
        if index is None:
            break
        buffer[count] = index
        count += 1
    if count == len(buffer):
        return count
    buffer[count] = TERMINATOR_CODE
    return count + 1


# --- ligatures --------------------------------------------------------------

#: Single glyphs standing for an apostrophe plus a letter. The games spend one
#: byte on each; PKHeX expands them on the way out and folds them back on the
#: way in. Only box names and mail use them, which is why the entity name path
#: leaves them alone.
LIGATURE_CODES = "０１２３４５６７８９ＡＢ"
#: The letter each code carries, per language group. English puts the
#: apostrophe first ('d); French and German put it last (c'), except index 8.
LIGATURE_ENG = "dlmrstv"
LIGATURE_FRE = "cdjlmnpsstuy"
#: The one French entry that reads 's rather than s'.
LIGATURE_FRE_APOSTROPHE_FIRST = 8
APOSTROPHE = "’"

LANGUAGES_WITHOUT_LIGATURES = (1, 8)     # Japanese, Korean
LANGUAGES_APOSTROPHE_LAST = (3, 5)       # French, German


def inflate_ligatures(text: str, language: int) -> str:
    """Expand each ligature glyph into the two characters it stands for."""
    if language in LANGUAGES_WITHOUT_LIGATURES:
        return text
    last = language in LANGUAGES_APOSTROPHE_LAST
    letters = LIGATURE_FRE if last else LIGATURE_ENG
    out: list[str] = []
    for char in text:
        index = LIGATURE_CODES.find(char)
        if index == -1 or index >= len(letters):
            out.append(char)
            continue
        letter = letters[index]
        if last and index != LIGATURE_FRE_APOSTROPHE_FIRST:
            out.append(letter + APOSTROPHE)
        else:
            out.append(APOSTROPHE + letter)
    return "".join(out)


def get_string1(data: bytes, jp: bool) -> str:
    if not jp and is_hangul_data(data):
        return get_string_kor(data)
    return _load(data, get_dict_g1(jp))


def set_string1(
    buffer: bytearray,
    value: str,
    max_length: int,
    jp: bool,
    option: StringConverterOption = StringConverterOption.CLEAR_50,
) -> int:
    if not jp and is_hangul_text(value):
        return set_string_kor(buffer, value, max_length, option)
    return _set(buffer, value, max_length, get_dict_g1(jp), option)


def get_string2(data: bytes, language: int) -> str:
    if language == 8 or (language != 1 and is_hangul_data(data)):  # Korean
        return get_string_kor(data)
    return _load(data, get_dict_g2(language))


def set_string2(
    buffer: bytearray,
    value: str,
    max_length: int,
    language: int,
    option: StringConverterOption = StringConverterOption.CLEAR_50,
) -> int:
    if language == 8 or (language != 1 and is_hangul_text(value)):
        return set_string_kor(buffer, value, max_length, option)
    return _set(buffer, value, max_length, get_dict_g2(language), option)
