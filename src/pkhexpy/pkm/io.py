"""Reading and writing entity files.

A .pkX file is the raw record, usually encrypted. Which format it is follows
from the extension when there is one, and otherwise from the length plus the
same heuristics PKHeX uses to separate formats that share a size.
"""

from __future__ import annotations

from pathlib import Path

from .. import crypto
from ..binio import read_u16, read_u32
from .formats import BY_NAME, PK1, PK2, PK4, PK5, PK6, PK7, PA8, PA9, PB7, PK8, PK9
from .formats import BK4, CK3, RK4, SK2, XK3, PK3
from .formats import STRING_LENGTH_INTERNATIONAL, STRING_LENGTH_JAPANESE

#: Gen1/2 files are a one-slot list: a count byte, a terminated species list,
#: then the record body and the two name buffers.
LIST_HEADER_SIZE = 1 + 2

LIST_SIZES = {
    crypto.SIZE_1JLIST: (PK1, True),
    crypto.SIZE_1ULIST: (PK1, False),
    crypto.SIZE_2JLIST: (PK2, True),
    crypto.SIZE_2ULIST: (PK2, False),
}

#: Sizes that identify exactly one format.
UNIQUE_SIZES = {
    crypto.SIZE_2STADIUM: SK2,
    crypto.SIZE_3STORED: PK3,
    crypto.SIZE_3PARTY: PK3,
    crypto.SIZE_3CSTORED: CK3,
    crypto.SIZE_3XSTORED: XK3,
    crypto.SIZE_4RSTORED: RK4,
    crypto.SIZE_8ASTORED: PA8,
    crypto.SIZE_8APARTY: PA8,
}


class EntityFormatError(ValueError):
    """Raised when a buffer does not match any known entity format."""


def _strip_list_header(raw: bytes, cls: type, japanese: bool) -> bytearray:
    """Turn a Gen1/2 one-slot list into this port's body+names buffer."""
    length = STRING_LENGTH_JAPANESE if japanese else STRING_LENGTH_INTERNATIONAL
    body_start = LIST_HEADER_SIZE
    body_end = body_start + cls.SIZE_PARTY
    ot_start = body_end
    nick_start = ot_start + length
    buffer = bytearray(cls.SIZE_PARTY + 2 * length)
    buffer[:cls.SIZE_PARTY] = raw[body_start:body_end]
    buffer[cls.SIZE_PARTY:cls.SIZE_PARTY + length] = raw[ot_start:ot_start + length]
    buffer[cls.SIZE_PARTY + length:] = raw[nick_start:nick_start + length]
    return buffer


def _add_list_header(entity, japanese: bool) -> bytes:
    """Write a Gen1/2 entity back out as a one-slot list."""
    cls = type(entity)
    length = STRING_LENGTH_JAPANESE if japanese else STRING_LENGTH_INTERNATIONAL
    out = bytearray(LIST_HEADER_SIZE + cls.SIZE_PARTY + 2 * length)
    out[0] = 1
    out[1] = cls.SLOT_EGG if entity.is_egg else entity.species_internal
    out[2] = 0xFF  # list terminator
    body = entity.data
    out[LIST_HEADER_SIZE:LIST_HEADER_SIZE + cls.SIZE_PARTY] = body[:cls.SIZE_PARTY]
    out[LIST_HEADER_SIZE + cls.SIZE_PARTY:] = body[cls.SIZE_PARTY:]
    return bytes(out)


def _detect_45(raw: bytes) -> type:
    """Separate PK4, BK4, and PK5, which share sizes. Assumes decrypted input."""
    if read_u16(raw, 0x04) != 0:
        return BK4                      # BK4 leaves a non-zero sanity value
    if raw[0x5F] < 0x10 and read_u16(raw, 0x80) < 0x3333:
        return BK4 if len(raw) == crypto.SIZE_5PARTY else PK4
    if read_u16(raw, 0x46) != 0:        # PK4 met-location extension, unused in PK5
        return BK4 if len(raw) == crypto.SIZE_5PARTY else PK4
    return PK5


# Highest ids reachable in Gen6; anything above means the file is really Gen7.
MAX_SPECIES_6 = 721
MAX_MOVE_6 = 621
MAX_ABILITY_6 = 191
MAX_ITEM_6 = 775
MAX_GAME_6 = 27


def _detect_67(raw: bytes) -> type:
    """Separate PK6, PK7, and PB7, which share a size."""
    pk = PK6(crypto.decrypt_buffer67(raw))
    version = pk.version
    if version > MAX_GAME_6:
        return PB7 if version in (42, 43, 34) else PK7   # GP, GE, GO
    if pk.species > MAX_SPECIES_6:
        return PK7
    if any(m > MAX_MOVE_6 for m in pk.moves + pk.relearn_moves):
        return PK7
    if pk.ability > MAX_ABILITY_6:
        return PK7
    if pk.held_item > MAX_ITEM_6:
        return PK7
    return PK6


GAME_VERSION_ZA = 53


def _detect_89(raw: bytes) -> type:
    """Separate the Switch-era formats, which all share a size."""
    core = crypto.decrypt_buffer8(raw)
    if read_u32(core, 0x120) == 0:      # never captured: no met or egg location
        if core[0xCE] == GAME_VERSION_ZA:
            return PA9
        if core[0xE8] == 0:             # Gen8 writes 0xFF for the affixed ribbon
            return PK9
        return PK8
    if core[0x11F] == 0:                # Gen8 alignment byte, Gen9 obedience level
        ivs = read_u32(core, 0x8C)
        if (ivs >> 30) & 1 != 1:        # not an egg, so Gen9 would have set it
            return PK8
        if core[0xDE] != 0:
            return PK8
        return PK9
    if core[0xCE] == GAME_VERSION_ZA:
        return PA9
    if core[0x23] != 0:                 # IsAlpha
        return PA9
    if any(core[0x96:0xA0]) or any(core[0xD6:0xF7]):
        return PA9
    if any(core[0x82:0x8A]):            # relearn moves, unused by Z-A
        return PK9
    return PK9


def detect_format(raw: bytes, extension: str | None = None) -> tuple[type, bool]:
    """Pick the entity class for ``raw``.

    Returns the class and whether the data is a Gen1/2 list wrapper. An explicit
    ``extension`` wins when it names a known format and the length agrees; the
    formats that share a size cannot always be told apart from bytes alone.
    """
    size = len(raw)
    if size in LIST_SIZES:
        return LIST_SIZES[size][0], True

    hinted = BY_NAME.get((extension or "").lstrip(".").lower())
    if hinted is not None and size in (hinted.SIZE_STORED, hinted.SIZE_PARTY):
        return hinted, False

    if size in UNIQUE_SIZES:
        return UNIQUE_SIZES[size], False
    if size in (crypto.SIZE_1STORED, crypto.SIZE_1PARTY):
        return PK1, False
    if size in (crypto.SIZE_2STORED, crypto.SIZE_2PARTY):
        return PK2, False
    if size in (crypto.SIZE_4STORED, crypto.SIZE_4PARTY, crypto.SIZE_5PARTY):
        return _detect_45(crypto.decrypt_buffer45(raw)), False
    if size in (crypto.SIZE_6STORED, crypto.SIZE_6PARTY):
        return _detect_67(raw), False
    if size in (crypto.SIZE_8STORED, crypto.SIZE_8PARTY):
        return _detect_89(raw), False
    raise EntityFormatError(f"no entity format has size {size}")


def from_bytes(raw: bytes, extension: str | None = None, japanese: bool | None = None):
    """Build an entity from raw file bytes, decrypting when needed."""
    cls, is_list = detect_format(raw, extension)
    if is_list:
        jp = len(raw) in (crypto.SIZE_1JLIST, crypto.SIZE_2JLIST)
        return cls(_strip_list_header(raw, cls, jp), japanese=jp,
                   is_egg=raw[1] == cls.SLOT_EGG)

    if cls in (PK1, PK2):
        # A bare record carries no names; default to the international width.
        jp = bool(japanese)
        length = STRING_LENGTH_JAPANESE if jp else STRING_LENGTH_INTERNATIONAL
        buffer = bytearray(cls.SIZE_PARTY + 2 * length)
        buffer[:min(len(raw), cls.SIZE_PARTY)] = raw[:cls.SIZE_PARTY]
        return cls(buffer, japanese=jp)

    return cls(cls.decrypt_buffer(raw))


def to_bytes(entity, *, encrypted: bool = False) -> bytes:
    """Serialize an entity back to its file representation.

    PKHeX writes .pkX files decrypted, so that is the default here too; pass
    ``encrypted=True`` for the form a save file stores.
    """
    if isinstance(entity, (PK1, PK2)):
        return _add_list_header(entity, entity.japanese)
    if not encrypted:
        entity.refresh_checksum()
        return bytes(entity.data)
    return entity.encrypted_bytes()


def read_file(path: str | Path):
    path = Path(path)
    return from_bytes(path.read_bytes(), extension=path.suffix)


def write_file(path: str | Path, entity, *, encrypted: bool = False) -> None:
    Path(path).write_bytes(to_bytes(entity, encrypted=encrypted))
