"""Buffer pre-formatting options for string encoding.

Port of ``PKHeX.Core.StringConverterOption``. The choice matters for round
tripping: each generation pads unused bytes with a different filler, and writing
the wrong one changes bytes the game compares against.
"""

from __future__ import annotations

from enum import Enum


class StringConverterOption(Enum):
    NONE = "none"
    """Leave the buffer untouched before writing."""

    CLEAR_ZERO = "clear_zero"
    """Zero the whole buffer first."""

    CLEAR_50 = "clear_50"
    """Fill with 0x50, the Gen1/2 terminator."""

    CLEAR_7F = "clear_7f"
    """Fill with 0x7F, the Gen1/2 Stadium space."""

    CLEAR_FF = "clear_ff"
    """Fill with 0xFF, the Gen3-5 terminator."""

    CLEAR_ZERO_SAFE_TERMINATE = "clear_zero_safe_terminate"
    """Zero the buffer, then force a terminator into the final slot (Gen5)."""
