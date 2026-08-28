"""String encoding and decoding across every generation.

``get_string`` and ``set_string`` mirror ``PKHeX.Core.StringConverter``: pick the
per-generation implementation from the format's generation, endianness, and the
entity's language.
"""

from __future__ import annotations

from . import gen12, gen345, modern
from .options import StringConverterOption

__all__ = ["StringConverterOption", "gen12", "gen345", "get_string", "modern", "set_string"]


def get_string(
    data: bytes,
    generation: int,
    jp: bool = False,
    big_endian: bool = False,
    language: int = 0,
) -> str:
    """Decode ``data`` into text using the encoding for ``generation``."""
    if big_endian:
        # GameCube-era formats (Colosseum/XD, Battle Revolution).
        from . import gamecube
        if generation == 3:
            return gamecube.get_string3(data)
        if generation == 4:
            return gamecube.get_string4(data)
    if generation == 1:
        return gen12.get_string1(data, jp)
    if generation == 2:
        return gen12.get_string2(data, language)
    if generation == 3:
        return gen345.get_string3(data, language)
    if generation == 4:
        return gen345.get_string4(data)
    if generation == 5:
        return gen345.get_string5(data)
    if generation == 6:
        return modern.get_string6(data)
    if generation == 7:
        return modern.get_string7(data)
    if generation in (8, 9):
        return modern.get_string8(data)
    raise ValueError(f"no string encoding for generation {generation}")


def set_string(
    buffer: bytearray,
    value: str,
    max_length: int,
    generation: int,
    jp: bool = False,
    big_endian: bool = False,
    language: int = 0,
    option: StringConverterOption | None = None,
) -> int:
    """Encode ``value`` into ``buffer``; returns the number of bytes written."""
    if big_endian:
        from . import gamecube
        if generation == 3:
            return gamecube.set_string3(buffer, value, max_length,
                                        option or StringConverterOption.CLEAR_ZERO)
        if generation == 4:
            return gamecube.set_string4(buffer, value, max_length, language,
                                        option or StringConverterOption.CLEAR_ZERO)
    if generation == 1:
        return gen12.set_string1(buffer, value, max_length, jp,
                                 option or StringConverterOption.CLEAR_50)
    if generation == 2:
        return gen12.set_string2(buffer, value, max_length, language,
                                 option or StringConverterOption.CLEAR_50)
    if generation == 3:
        return gen345.set_string3(buffer, value, max_length, language,
                                  option or StringConverterOption.CLEAR_FF)
    if generation == 4:
        return gen345.set_string4(buffer, value, max_length, language,
                                  option or StringConverterOption.CLEAR_ZERO)
    if generation == 5:
        return gen345.set_string5(buffer, value, max_length, language,
                                  option or StringConverterOption.CLEAR_ZERO)
    if generation == 6:
        return modern.set_string6(buffer, value, max_length, language,
                                  option or StringConverterOption.CLEAR_ZERO)
    if generation == 7:
        return modern.set_string7(buffer, value, max_length, language,
                                  option or StringConverterOption.CLEAR_ZERO)
    if generation in (8, 9):
        return modern.set_string8(buffer, value, max_length,
                                  option or StringConverterOption.CLEAR_ZERO)
    raise ValueError(f"no string encoding for generation {generation}")
