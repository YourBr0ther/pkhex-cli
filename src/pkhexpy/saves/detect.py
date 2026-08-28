"""Identify which game a save file came from.

Sizes narrow the field; a magic value, a footer, or a structural check settles
it. This follows ``PKHeX.Core.SaveUtil``, in the same order, so a file that
PKHeX recognizes is recognized here too.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..binio import read_u32
from . import gen3, gen8b, gen12, swish
from .gen45 import SAV4DP, SAV4HGSS, SAV4Pt, SAV5B2W2, SAV5BW, SIZE_G4RAW, SIZE_G5RAW
from .gen67 import SAV6AO, SAV6XY, SAV7SM, SAV7USUM, SAV7b, has_beef_footer
from .gen89 import SAV8LA, SAV8SWSH, SAV9SV, SAV9ZA

SIZE_G6XY = 0x65600
SIZE_G6ORAS = 0x76000
SIZE_G7SM = 0x6BE00
SIZE_G7USUM = 0x6CC00
SIZE_G7GG = 0x100000

SIZE_G8SWSH = (0x1716B3, 0x17195E, 0x180B19, 0x180AD0,
               0x1876B1, 0x187693, 0x187668, 0x18764A)
SIZE_G8LA = (0x136DDE, 0x13AD06)
SIZE_G8BDSP = (0xE9828, 0xEDC20, 0xEED8C, 0xEF0A4)
SIZE_G9ZA = (0x2F3284, 0x2F3289, 0x309FA6, 0x309FB3)

#: Scarlet/Violet grew with each patch and DLC; the exact sizes plus the ranges
#: PKHeX accepts, all of which are confirmed by the trailing hash anyway.
SIZE_G9SV_EXACT = (
    0x31626F, 0x31627C, 0x319DB3, 0x319DC0, 0x319DC3, 0x319DD0,
    0x31A2C0, 0x31A2CD, 0x31A2DD, 0x31A2D0,
    0x31CA6F, 0x31CF7C,
)
SIZE_G9SV_RANGES = ((0x4329A0, 0x432ED6 + 100 + 0x83AD),)


#: Recognized, deliberately unsupported. The Pokemon formats these games use
#: do work; it is the save containers around them that are out of scope.
UNSUPPORTED_SIZES: dict[int, str] = {
    0x5A00: "the Omega Ruby/Alpha Sapphire demo, which this port does not read",
    0x56000: "Pokemon XD, which this port does not read",
    0x60000: "Pokemon Colosseum, which this port does not read",
    0x76000: "Ruby/Sapphire Box, which this port does not read",
    0x380000: "Battle Revolution, which this port does not read",
    0x54000: "My Pokemon Ranch, which this port does not read",
    0x7C000: "My Pokemon Ranch (Platinum), which this port does not read",
    0x1FF00: "a Stadium save, which this port does not read",
}


class SaveFormatError(ValueError):
    """Raised when a buffer does not match any known save format."""


#: Sizes that name a game even when the structural check fails, so a file that
#: is the right length but the wrong shape gets a useful message.
KNOWN_SIZES: dict[int, str] = {}


def _register_sizes() -> None:
    KNOWN_SIZES[0x8000] = "Red/Blue/Yellow or Gold/Silver/Crystal"
    KNOWN_SIZES[0x10000] = "a Japanese Gold/Silver/Crystal or half-size GBA save"
    KNOWN_SIZES[0x20000] = "a Game Boy Advance save"
    KNOWN_SIZES[SIZE_G4RAW] = "a DS save (Diamond/Pearl, Platinum, HeartGold/SoulSilver, or Gen5)"
    KNOWN_SIZES[SIZE_G6XY] = "X/Y"
    KNOWN_SIZES[SIZE_G6ORAS] = "Omega Ruby/Alpha Sapphire"
    KNOWN_SIZES[SIZE_G7SM] = "Sun/Moon"
    KNOWN_SIZES[SIZE_G7USUM] = "Ultra Sun/Ultra Moon"
    KNOWN_SIZES[SIZE_G7GG] = "Let's Go"
    for size in SIZE_G8SWSH:
        KNOWN_SIZES[size] = "Sword/Shield"
    for size in SIZE_G8LA:
        KNOWN_SIZES[size] = "Legends: Arceus"
    for size in SIZE_G8BDSP:
        KNOWN_SIZES[size] = "Brilliant Diamond/Shining Pearl"
    for size in SIZE_G9ZA:
        KNOWN_SIZES[size] = "Legends: Z-A"
    for size in SIZE_G9SV_EXACT:
        KNOWN_SIZES[size] = "Scarlet/Violet"
    # UNSUPPORTED_SIZES stays out of this table on purpose. A size a supported
    # game already claims keeps that game's message, and detect() adds the
    # out-of-scope one after it rather than in place of it.


#: Emulators append their real-time-clock state after a Game Boy or GBA save.
#: The sizes vary by emulator, so accept a plausible range the way PKHeX does.
RTC_FOOTER_MIN = 0x0C
RTC_FOOTER_MAX = 0x30
RTC_BASE_SIZES = (0x20000, 0x10000, 0x8000)  # GBA, Gen2 Japanese, Gen1/Gen2


def split_rtc_footer(data: bytes) -> tuple[bytes, bytes]:
    """Split a trailing emulator RTC footer off, if one is present."""
    footer_size = len(data) & 0x3F
    if footer_size == 0:
        return data, b""
    plausible = (footer_size == 0x07
                 or (footer_size % 2 == 0
                     and RTC_FOOTER_MIN <= footer_size <= RTC_FOOTER_MAX))
    if not plausible:
        return data, b""
    body = len(data) - footer_size
    if body not in RTC_BASE_SIZES:
        return data, b""
    return data[:body], data[body:]


_register_sizes()


def _is_gen9_sv_size(length: int) -> bool:
    if length in SIZE_G9SV_EXACT:
        return True
    return any(low <= length <= high for low, high in SIZE_G9SV_RANGES)


def _gen9_sv(data: bytes):
    """Scarlet/Violet grew with every patch, so the size is a range check."""
    if not _is_gen9_sv_size(len(data)) or not swish.is_hash_valid(data):
        return None
    return SAV9SV, {}


def _gen1(data: bytes):
    if gen12.is_gen1_japanese(data):
        return gen12.SAV1, {"japanese": True}
    if gen12.is_gen1_international(data):
        return gen12.SAV1, {}
    return None


def _gen2(data: bytes):
    for check, kwargs in (
        (gen12.is_gen2_gs_international, {}),
        (gen12.is_gen2_crystal_international, {"crystal": True}),
        (gen12.is_gen2_gs_japanese, {"japanese": True}),
        (gen12.is_gen2_crystal_japanese, {"japanese": True, "crystal": True}),
    ):
        if check(data):
            return gen12.SAV2, kwargs
    return None


def _gen3(data: bytes):
    if not gen3.is_gen3(data):
        return None
    # Every Gen3 game shares a layout; the small block names the version.
    probe = gen3.SAV3E(data)
    return gen3.BY_VERSION[gen3.detect_version(bytes(probe.small))], {}


def _gen4(data: bytes):
    for cls in (SAV4DP, SAV4Pt, SAV4HGSS):
        if _is_gen4(data, cls):
            return cls, {}
    return None


def _gen5(data: bytes):
    if _is_gen5(data, 0x24000, 0x8C):
        return SAV5BW, {}
    if _is_gen5(data, 0x26000, 0x94):
        return SAV5B2W2, {}
    return None


def _beef(cls, limit: int | None = None):
    """A 3DS save, told apart by the "BEEF" chunk near the end."""
    def check(data: bytes):
        return (cls, {}) if has_beef_footer(data[:limit] if limit else data) else None
    return check


def _hashed(cls):
    """A Switch save, told apart by the SHA-256 over its payload."""
    def check(data: bytes):
        return (cls, {}) if swish.is_hash_valid(data) else None
    return check


def _bdsp(data: bytes):
    return (gen8b.SAV8BS, {}) if gen8b.is_bdsp(data) else None


#: Tried in order. ``sizes`` of None means the size does not narrow it down, so
#: the check runs on any buffer that got this far.
PROBES: tuple[tuple[tuple[int, ...] | None, Callable], ...] = (
    ((gen12.SIZE_G1RAW,), _gen1),
    ((gen12.SIZE_G2RAW_U, gen12.SIZE_G2RAW_J), _gen2),
    (None, _gen3),
    ((SIZE_G4RAW,), _gen4),
    ((SIZE_G5RAW,), _gen5),
    ((SIZE_G6XY,), _beef(SAV6XY)),
    ((SIZE_G6ORAS,), _beef(SAV6AO)),
    ((SIZE_G7SM,), _beef(SAV7SM)),
    ((SIZE_G7USUM,), _beef(SAV7USUM)),
    ((SIZE_G7GG,), _beef(SAV7b, 0xB8800)),
    (SIZE_G8SWSH, _hashed(SAV8SWSH)),
    (SIZE_G8LA, _hashed(SAV8LA)),
    (None, _bdsp),
    (None, _gen9_sv),
    (SIZE_G9ZA, _hashed(SAV9ZA)),
)


def detect(data: bytes):
    """Return the save class and constructor keyword arguments for ``data``."""
    size = len(data)
    for sizes, check in PROBES:
        if sizes is not None and size not in sizes:
            continue
        found = check(data)
        if found is not None:
            return found

    known = KNOWN_SIZES.get(size)
    if known:
        message = (
            f"{size} bytes is the right size for {known}, but the file does not "
            "have the structure one should. It may still be encrypted, or be a "
            "container the dumper wrapped around the save"
        )
        # The size may also belong to a game that is simply out of scope, which
        # is worth saying rather than leaving the caller to suspect their file.
        other = UNSUPPORTED_SIZES.get(size)
        if other:
            message += f". It is also the size of {other}"
        raise SaveFormatError(message)
    unsupported = UNSUPPORTED_SIZES.get(size)
    if unsupported:
        raise SaveFormatError(
            f"this looks like {unsupported}. The Pokemon in it are readable as "
            "individual files; only the save container is out of scope"
        )
    raise SaveFormatError(f"no save format matches a {size}-byte file")


MAGIC_JAPAN_INTL = 0x20060623
MAGIC_KOREAN = 0x20070903


def _is_gen4(data: bytes, cls) -> bool:
    """The general block's footer records its own length and an SDK magic."""
    general = data[0x40000:0x40000 + cls.GENERAL_SIZE]
    if len(general) < 0xC:
        return False
    if read_u32(general, len(general) - 0xC) != len(general):
        return False
    return read_u32(general, len(general) - 0x8) in (MAGIC_JAPAN_INTL, MAGIC_KOREAN)


def _is_gen5(data: bytes, main_size: int, info_length: int) -> bool:
    from . import checksums
    footer = data[main_size - 0x100: main_size - 0x100 + info_length + 0x10]
    if len(footer) < info_length + 2:
        return False
    stored = int.from_bytes(footer[-2:], "little")
    return stored == checksums.crc16_ccitt(bytes(footer[:info_length]))


def from_bytes(data: bytes):
    body, footer = split_rtc_footer(data)
    cls, kwargs = detect(body)
    sav = cls(body, **kwargs)
    if footer:
        # Keep it so writing the file back restores what the emulator expects.
        sav.rtc_footer = footer
    return sav


def read_file(path: str | Path):
    path = Path(path)
    return from_bytes(path.read_bytes())
