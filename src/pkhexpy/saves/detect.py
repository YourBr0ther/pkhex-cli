"""Identify which game a save file came from.

Sizes narrow the field; a magic value, a footer, or a structural check settles
it. This follows ``PKHeX.Core.SaveUtil``, in the same order, so a file that
PKHeX recognizes is recognized here too.
"""

from __future__ import annotations

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


def detect(data: bytes, filename: str | None = None):
    """Return the save class and constructor keyword arguments for ``data``."""
    size = len(data)

    # Game Boy: identified by the shape of their packed Pokemon lists.
    if size == gen12.SIZE_G1RAW:
        if gen12.is_gen1_japanese(data):
            return gen12.SAV1, {"japanese": True}
        if gen12.is_gen1_international(data):
            return gen12.SAV1, {}
    if size in (gen12.SIZE_G2RAW_U, gen12.SIZE_G2RAW_J):
        if gen12.is_gen2_gs_international(data):
            return gen12.SAV2, {}
        if gen12.is_gen2_crystal_international(data):
            return gen12.SAV2, {"crystal": True}
        if gen12.is_gen2_gs_japanese(data):
            return gen12.SAV2, {"japanese": True}
        if gen12.is_gen2_crystal_japanese(data):
            return gen12.SAV2, {"japanese": True, "crystal": True}

    # Game Boy Advance: 14 sectors per copy, version told apart by the small block.
    if gen3.is_gen3(data):
        probe = gen3.SAV3E(data)
        version = gen3.detect_version(bytes(probe.small))
        return gen3.BY_VERSION[version], {}

    # DS: block footers carry a size and an SDK magic.
    if size == SIZE_G4RAW:
        for cls in (SAV4DP, SAV4Pt, SAV4HGSS):
            if _is_gen4(data, cls):
                return cls, {}
    if size == SIZE_G5RAW:
        if _is_gen5(data, 0x24000, 0x8C):
            return SAV5BW, {}
        if _is_gen5(data, 0x26000, 0x94):
            return SAV5B2W2, {}

    # 3DS: a "BEEF" metadata chunk near the end.
    if size == SIZE_G6XY and has_beef_footer(data):
        return SAV6XY, {}
    if size == SIZE_G6ORAS and has_beef_footer(data):
        return SAV6AO, {}
    if size == SIZE_G7SM and has_beef_footer(data):
        return SAV7SM, {}
    if size == SIZE_G7USUM and has_beef_footer(data):
        return SAV7USUM, {}
    if size == SIZE_G7GG and has_beef_footer(data[:0xB8800]):
        return SAV7b, {}

    # Switch: a trailing SHA-256 over the whole payload.
    if size in SIZE_G8SWSH and swish.is_hash_valid(data):
        return SAV8SWSH, {}
    if size in SIZE_G8LA and swish.is_hash_valid(data):
        return SAV8LA, {}
    if gen8b.is_bdsp(data):
        return gen8b.SAV8BS, {}
    if _is_gen9_sv_size(size) and swish.is_hash_valid(data):
        return SAV9SV, {}
    if size in SIZE_G9ZA and swish.is_hash_valid(data):
        return SAV9ZA, {}

    known = KNOWN_SIZES.get(size)
    if known:
        raise SaveFormatError(
            f"{size} bytes is the right size for {known}, but the file does not "
            "have the structure one should. It may still be encrypted, or be a "
            "container the dumper wrapped around the save"
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


def from_bytes(data: bytes, filename: str | None = None):
    body, footer = split_rtc_footer(data)
    cls, kwargs = detect(body, filename)
    sav = cls(body, **kwargs)
    if footer:
        # Keep it so writing the file back restores what the emulator expects.
        sav.rtc_footer = footer
    return sav


def read_file(path: str | Path):
    path = Path(path)
    return from_bytes(path.read_bytes(), filename=path.name)
