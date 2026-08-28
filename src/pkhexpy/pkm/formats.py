"""Concrete entity classes: one per file format.

Each class pins the constants the generated layout cannot express - sizes,
context, which personal and location tables apply - and adds the derived
properties whose C# definitions are logic rather than a byte offset.
"""

from __future__ import annotations

from .. import crypto
from ..data import gender_ratio
from . import _layouts as _L
from . import species_convert

#: Value stored in a Gen9 tera-type override slot meaning "not overridden".
TERA_OVERRIDE_NONE = 19

STRING_LENGTH_JAPANESE = 6
STRING_LENGTH_INTERNATIONAL = 11


def _adopt(source: type) -> dict:
    """Copy a generated layout's descriptors into a class that cannot inherit it."""
    return dict(source.fields())


class _HandlerFriendship:
    """Gen6+ keep two friendship values and expose whichever handler is current."""

    @property
    def current_friendship(self) -> int:
        return (self.original_trainer_friendship if self.current_handler == 0
                else self.handling_trainer_friendship)

    @current_friendship.setter
    def current_friendship(self, value: int) -> None:
        if self.current_handler == 0:
            self.original_trainer_friendship = value
        else:
            self.handling_trainer_friendship = value


class _Gen89Checksum(_HandlerFriendship):
    """Checksum and validity for the Switch-era formats."""

    CHECKSUM_END: int = crypto.SIZE_8STORED

    def calculate_checksum(self) -> int:
        return crypto.add16(self.data, 8, self.CHECKSUM_END)

    @property
    def valid(self) -> bool:
        return self.sanity == 0 and self.checksum_valid


# --------------------------------------------------------------------------
# Generation 9
# --------------------------------------------------------------------------


class PK9(_Gen89Checksum, _L.PK9Layout):
    """Scarlet/Violet."""

    FORMAT = 9
    CONTEXT = "gen9"
    SIZE_STORED = crypto.SIZE_8STORED
    SIZE_PARTY = crypto.SIZE_8PARTY
    PERSONAL_TABLE = "sv"
    LOCATION_CONTEXT = "gen9"
    LOCATION_GAME = "sv"
    _encrypt = staticmethod(crypto.encrypt8)
    _decrypt_if_encrypted = staticmethod(crypto.decrypt_if_encrypted8)

    @property
    def species(self) -> int:
        return species_convert.to_national9(self.species_internal)

    @species.setter
    def species(self, value: int) -> None:
        self.species_internal = species_convert.to_internal9(value)

    @property
    def tera_type(self) -> int:
        override = self.tera_type_override
        return self.tera_type_original if override == TERA_OVERRIDE_NONE else override

    @property
    def is_untraded(self) -> bool:
        return self.data[0xA8] == 0 and self.data[0xA9] == 0


class PA9(_Gen89Checksum, _L.PA9Layout):
    """Legends: Z-A."""

    FORMAT = 9
    CONTEXT = "gen9a"
    SIZE_STORED = crypto.SIZE_8STORED
    SIZE_PARTY = crypto.SIZE_8PARTY
    PERSONAL_TABLE = "za"
    LOCATION_CONTEXT = "gen9a"
    LOCATION_GAME = "za"
    _encrypt = staticmethod(crypto.encrypt8)
    _decrypt_if_encrypted = staticmethod(crypto.decrypt_if_encrypted8)

    @property
    def species(self) -> int:
        return species_convert.to_national9(self.species_internal)

    @species.setter
    def species(self, value: int) -> None:
        self.species_internal = species_convert.to_internal9(value)

    @property
    def is_untraded(self) -> bool:
        return self.data[0xB8] == 0 and self.data[0xB9] == 0


# --------------------------------------------------------------------------
# Generation 8
# --------------------------------------------------------------------------


class PK8(_Gen89Checksum, _L.PK8Layout):
    """Sword/Shield."""

    FORMAT = 8
    CONTEXT = "gen8"
    SIZE_STORED = crypto.SIZE_8STORED
    SIZE_PARTY = crypto.SIZE_8PARTY
    PERSONAL_TABLE = "swsh"
    LOCATION_CONTEXT = "gen8"
    LOCATION_GAME = "swsh"
    _encrypt = staticmethod(crypto.encrypt8)
    _decrypt_if_encrypted = staticmethod(crypto.decrypt_if_encrypted8)


class PB8(_Gen89Checksum, _L.PB8Layout):
    """Brilliant Diamond/Shining Pearl."""

    FORMAT = 8
    CONTEXT = "gen8b"
    SIZE_STORED = crypto.SIZE_8STORED
    SIZE_PARTY = crypto.SIZE_8PARTY
    PERSONAL_TABLE = "bdsp"
    LOCATION_CONTEXT = "gen8b"
    LOCATION_GAME = "bdsp"
    _encrypt = staticmethod(crypto.encrypt8)
    _decrypt_if_encrypted = staticmethod(crypto.decrypt_if_encrypted8)


class PA8(_Gen89Checksum, _L.PA8Layout):
    """Legends: Arceus."""

    # Stats add Ganbaru values, so the shared formula does not apply.
    STAT_FORMULA = None

    FORMAT = 8
    CONTEXT = "gen8a"
    SIZE_STORED = crypto.SIZE_8ASTORED
    SIZE_PARTY = crypto.SIZE_8APARTY
    CHECKSUM_END = crypto.SIZE_8ASTORED
    PERSONAL_TABLE = "la"
    LOCATION_CONTEXT = "gen8a"
    LOCATION_GAME = "la"
    _encrypt = staticmethod(crypto.encrypt8a)
    _decrypt_if_encrypted = staticmethod(crypto.decrypt_if_encrypted8a)


# --------------------------------------------------------------------------
# Generations 6 and 7
# --------------------------------------------------------------------------


class _G6Base(_HandlerFriendship):
    SIZE_STORED = crypto.SIZE_6STORED
    SIZE_PARTY = crypto.SIZE_6PARTY
    _encrypt = staticmethod(crypto.encrypt67)
    _decrypt_if_encrypted = staticmethod(crypto.decrypt_if_encrypted67)

    def calculate_checksum(self) -> int:
        return crypto.add16(self.data, 8, crypto.SIZE_6STORED)

    @property
    def valid(self) -> bool:
        return self.sanity == 0 and self.checksum_valid


class PK6(_G6Base, _L.PK6Layout):
    """X/Y and Omega Ruby/Alpha Sapphire."""

    FORMAT = 6
    CONTEXT = "gen6"
    PERSONAL_TABLE = "ao"
    LOCATION_CONTEXT = "gen6"
    LOCATION_GAME = "xy"


class PK7(_G6Base, _L.PK7Layout):
    """Sun/Moon and Ultra Sun/Ultra Moon."""

    FORMAT = 7
    CONTEXT = "gen7"
    PERSONAL_TABLE = "uu"
    LOCATION_CONTEXT = "gen7"
    LOCATION_GAME = "sm"


class PB7(_G6Base, _L.PB7Layout):
    """Let's Go Pikachu/Eevee."""

    # Stats add Awakening Values and scale with friendship, so the shared
    # formula does not apply.
    STAT_FORMULA = None

    FORMAT = 7
    CONTEXT = "gen7b"
    PERSONAL_TABLE = "gg"
    LOCATION_CONTEXT = "gen7"
    LOCATION_GAME = "gg"


# --------------------------------------------------------------------------
# Generations 3 to 5
# --------------------------------------------------------------------------


#: Unown is the only Gen3 species with a form, and it comes out of the PID.
UNOWN = 201


def unown_form3(pid: int) -> int:
    value = (((pid & 0x3000000) >> 18) | ((pid & 0x30000) >> 12)
             | ((pid & 0x300) >> 6) | (pid & 0x3))
    return value % 28


class _Gen3Form:
    """Gen3 stores no form field; only Unown varies, keyed off the PID."""

    @property
    def form(self) -> int:
        return unown_form3(self.pid) if self.species == UNOWN else 0


class _PIDDerived:
    """Gen3/4 read nature and gender out of the personality value."""

    SHINY_SHIFT = 3

    @property
    def nature(self) -> int:
        return self.pid % 25

    @property
    def pid_gender(self) -> int:
        """Gender implied by the PID and the species' gender ratio."""
        ratio = gender_ratio(self.PERSONAL_TABLE, self.species)
        if ratio == 255:
            return 2      # genderless
        if ratio == 254:
            return 1      # always female
        if ratio == 0:
            return 0      # always male
        return 1 if (self.pid & 0xFF) < ratio else 0


class PK5(_L.PK5Layout):
    """Black/White and Black 2/White 2."""

    FORMAT = 5
    CONTEXT = "gen5"
    SIZE_STORED = crypto.SIZE_5STORED
    SIZE_PARTY = crypto.SIZE_5PARTY
    SHINY_SHIFT = 3
    MAX_EV = 255
    MAX_STRING_LENGTH_NICKNAME = 10
    MAX_STRING_LENGTH_TRAINER = 7
    PERSONAL_TABLE = "b2w2"
    LOCATION_CONTEXT = "gen5"
    LOCATION_GAME = "bw2"
    _encrypt = staticmethod(crypto.encrypt45)
    _decrypt_if_encrypted = staticmethod(crypto.decrypt_if_encrypted45)

    def calculate_checksum(self) -> int:
        return crypto.add16(self.data, 8, crypto.SIZE_5STORED)


class PK4(_PIDDerived, _L.PK4Layout):
    """Diamond/Pearl, Platinum, and HeartGold/SoulSilver."""

    FORMAT = 4
    CONTEXT = "gen4"
    SIZE_STORED = crypto.SIZE_4STORED
    SIZE_PARTY = crypto.SIZE_4PARTY
    MAX_EV = 255
    MAX_STRING_LENGTH_NICKNAME = 10
    MAX_STRING_LENGTH_TRAINER = 7
    PERSONAL_TABLE = "hgss"
    LOCATION_CONTEXT = "gen4"
    LOCATION_GAME = "hgss"
    _encrypt = staticmethod(crypto.encrypt45)
    _decrypt_if_encrypted = staticmethod(crypto.decrypt_if_encrypted45)

    def calculate_checksum(self) -> int:
        return crypto.add16(self.data, 8, crypto.SIZE_4STORED)


class BK4(_PIDDerived, _L.BK4Layout):
    """Battle Revolution storage; big-endian and unencrypted at rest."""

    FORMAT = 4
    CONTEXT = "gen4"
    SIZE_STORED = crypto.SIZE_4STORED
    SIZE_PARTY = crypto.SIZE_4BPARTY
    BIG_ENDIAN = True
    MAX_EV = 255
    MAX_STRING_LENGTH_NICKNAME = 10
    MAX_STRING_LENGTH_TRAINER = 7
    PERSONAL_TABLE = "hgss"
    LOCATION_CONTEXT = "gen4"
    LOCATION_GAME = "hgss"
    _encrypt = staticmethod(crypto.encrypt4be)
    _decrypt_if_encrypted = staticmethod(crypto.decrypt4be)


class RK4(_PIDDerived, _L.RK4Layout):
    """My Pokemon Ranch storage."""

    FORMAT = 4
    CONTEXT = "gen4"
    SIZE_STORED = crypto.SIZE_4RSTORED
    SIZE_PARTY = crypto.SIZE_4RSTORED
    MAX_EV = 255
    MAX_STRING_LENGTH_NICKNAME = 10
    MAX_STRING_LENGTH_TRAINER = 7
    PERSONAL_TABLE = "hgss"
    LOCATION_CONTEXT = "gen4"
    LOCATION_GAME = "hgss"


class PK3(_Gen3Form, _PIDDerived, _L.PK3Layout):
    """Ruby/Sapphire, Emerald, and FireRed/LeafGreen."""

    FORMAT = 3
    CONTEXT = "gen3"
    SIZE_STORED = crypto.SIZE_3STORED
    SIZE_PARTY = crypto.SIZE_3PARTY
    MAX_EV = 255
    MAX_STRING_LENGTH_NICKNAME = 10
    MAX_STRING_LENGTH_TRAINER = 7
    PERSONAL_TABLE = "e"
    LOCATION_CONTEXT = "gen3"
    LOCATION_GAME = "rsefrlg"
    _encrypt = staticmethod(crypto.encrypt3)
    _decrypt_if_encrypted = staticmethod(crypto.decrypt_if_encrypted3)

    def calculate_checksum(self) -> int:
        return crypto.add16(self.data, crypto.SIZE_3HEADER, crypto.SIZE_3STORED)

    @property
    def species(self) -> int:
        return species_convert.to_national3(self.species_internal)

    @species.setter
    def species(self, value: int) -> None:
        self.species_internal = species_convert.to_internal3(value)


class CK3(_Gen3Form, _PIDDerived, _L.CK3Layout):
    """Colosseum storage; big-endian."""

    FORMAT = 3
    CONTEXT = "gen3"
    SIZE_STORED = crypto.SIZE_3CSTORED
    SIZE_PARTY = crypto.SIZE_3CSTORED
    BIG_ENDIAN = True
    MAX_EV = 255
    PERSONAL_TABLE = "e"
    LOCATION_CONTEXT = "gen3"
    LOCATION_GAME = "cxd"

    @property
    def species(self) -> int:
        return species_convert.to_national3(self.species_internal)

    @species.setter
    def species(self, value: int) -> None:
        self.species_internal = species_convert.to_internal3(value)


class XK3(_Gen3Form, _PIDDerived, _L.XK3Layout):
    """XD: Gale of Darkness storage; big-endian."""

    FORMAT = 3
    CONTEXT = "gen3"
    SIZE_STORED = crypto.SIZE_3XSTORED
    SIZE_PARTY = crypto.SIZE_3XSTORED
    BIG_ENDIAN = True
    MAX_EV = 255
    PERSONAL_TABLE = "e"
    LOCATION_CONTEXT = "gen3"
    LOCATION_GAME = "cxd"

    @property
    def species(self) -> int:
        return species_convert.to_national3(self.species_internal)

    @species.setter
    def species(self, value: int) -> None:
        self.species_internal = species_convert.to_internal3(value)


# --------------------------------------------------------------------------
# Generations 1 and 2
# --------------------------------------------------------------------------


class _GBBase:
    """Gen1/2 keep the nickname and trainer name outside the record.

    The game stores them in parallel arrays alongside the party or box list. To
    keep one entity in one buffer, this port appends both strings after the
    record body, in the order the list uses: trainer name, then nickname.
    """

    SHINY_SHIFT = 0
    MAX_IV = 15
    MAX_EV = 65535
    STAT_FORMULA = "gb"

    #: Slot marker a Gen2 list uses in place of the species id for an egg.
    SLOT_EGG = 0xFD

    _INSTANCE_ATTRS = frozenset({"data", "japanese", "string_length", "is_egg"})

    def __init__(self, data: bytes | bytearray | None = None, *,
                 japanese: bool = False, is_egg: bool = False) -> None:
        object.__setattr__(self, "string_length",
                           STRING_LENGTH_JAPANESE if japanese
                           else STRING_LENGTH_INTERNATIONAL)
        # Gen1/2 record the egg state in the list slot marker, not the record.
        object.__setattr__(self, "is_egg", is_egg)
        super().__init__(data, japanese=japanese)
        # The base class sizes to SIZE_PARTY, which stops short of the two name
        # buffers this port appends. Without this a fresh record writes its
        # nickname over the trainer name.
        wanted = self.buffer_size(japanese)
        if len(self.data) < wanted:
            self.data.extend(bytes(wanted - len(self.data)))

    @property
    def MAX_STRING_LENGTH_NICKNAME(self) -> int:
        return 5 if self.japanese else 10

    @property
    def MAX_STRING_LENGTH_TRAINER(self) -> int:
        return 5 if self.japanese else 7

    def clone(self):
        return type(self)(bytes(self.data), japanese=self.japanese, is_egg=self.is_egg)

    @classmethod
    def buffer_size(cls, japanese: bool) -> int:
        length = STRING_LENGTH_JAPANESE if japanese else STRING_LENGTH_INTERNATIONAL
        return cls.SIZE_PARTY + 2 * length

    def _string_slice(self, index: int) -> slice:
        start = self.SIZE_PARTY + index * self.string_length
        return slice(start, start + self.string_length)

    @property
    def original_trainer_trash(self) -> bytes:
        return bytes(self.data[self._string_slice(0)])

    @property
    def nickname_trash(self) -> bytes:
        return bytes(self.data[self._string_slice(1)])

    @property
    def original_trainer_name(self) -> str:
        return self.decode_string(self.original_trainer_trash)

    @original_trainer_name.setter
    def original_trainer_name(self, value: str) -> None:
        buffer = self.encode_name(self.string_length, value,
                                  self.MAX_STRING_LENGTH_TRAINER)
        self.data[self._string_slice(0)] = buffer

    @property
    def nickname(self) -> str:
        return self.decode_string(self.nickname_trash)

    @nickname.setter
    def nickname(self, value: str) -> None:
        buffer = self.encode_name(self.string_length, value,
                                  self.MAX_STRING_LENGTH_NICKNAME)
        self.data[self._string_slice(1)] = buffer

    # Gen1/2 pack four 4-bit DVs into one big-endian word.
    @property
    def iv_spc(self) -> int:
        return self.dv16 & 0xF

    @iv_spc.setter
    def iv_spc(self, value: int) -> None:
        self.dv16 = (self.dv16 & ~0xF) | (min(15, int(value)) & 0xF)

    @property
    def iv_spe(self) -> int:
        return (self.dv16 >> 4) & 0xF

    @iv_spe.setter
    def iv_spe(self, value: int) -> None:
        self.dv16 = (self.dv16 & ~0x00F0) | ((min(15, int(value)) & 0xF) << 4)

    @property
    def iv_def(self) -> int:
        return (self.dv16 >> 8) & 0xF

    @iv_def.setter
    def iv_def(self, value: int) -> None:
        self.dv16 = (self.dv16 & ~0x0F00) | ((min(15, int(value)) & 0xF) << 8)

    @property
    def iv_atk(self) -> int:
        return (self.dv16 >> 12) & 0xF

    @iv_atk.setter
    def iv_atk(self, value: int) -> None:
        self.dv16 = (self.dv16 & 0x0FFF) | ((min(15, int(value)) & 0xF) << 12)

    @property
    def iv_hp(self) -> int:
        """The HP DV is the low bit of the other four, in ATK/DEF/SPE/SPC order."""
        return (((self.iv_atk & 1) << 3) | ((self.iv_def & 1) << 2)
                | ((self.iv_spe & 1) << 1) | (self.iv_spc & 1))

    # Gen1 and Gen2 have one Special value where later games have two, so both
    # names read it and writing either one writes it, the way PKHeX does.
    @property
    def iv_spa(self) -> int:
        return self.iv_spc

    @iv_spa.setter
    def iv_spa(self, value: int) -> None:
        self.iv_spc = value

    @property
    def iv_spd(self) -> int:
        return self.iv_spc

    @iv_spd.setter
    def iv_spd(self, value: int) -> None:
        self.iv_spc = value

    @property
    def ev_spa(self) -> int:
        return self.ev_spc

    @ev_spa.setter
    def ev_spa(self, value: int) -> None:
        self.ev_spc = value

    @property
    def ev_spd(self) -> int:
        return self.ev_spc

    @ev_spd.setter
    def ev_spd(self, value: int) -> None:
        self.ev_spc = value

    @property
    def form(self) -> int:
        """Only Unown has a form in Gen2, and it is derived from the DVs."""
        if self.species != 201:
            return 0
        value = (((self.iv_atk & 0x6) << 5)
                 | ((self.iv_def & 0x6) << 3)
                 | ((self.iv_spe & 0x6) << 1)
                 | ((self.iv_spc & 0x6) >> 1))
        return value // 10

    @property
    def is_shiny(self) -> bool:
        """Shininess is fixed DVs: DEF/SPE/SPC are 10 and ATK has bit 1 set."""
        return (self.iv_def == 10 and self.iv_spe == 10 and self.iv_spc == 10
                and (self.iv_atk & 2) == 2)

    @property
    def pid(self) -> int:
        return 0

    @property
    def encryption_constant(self) -> int:
        return 0

    @property
    def sid16(self) -> int:
        return 0

    @property
    def id32(self) -> int:
        return self.tid16


class PK1(_GBBase, _L.PK1Layout):
    """Red/Blue/Yellow."""

    FORMAT = 1
    CONTEXT = "gen1"
    SIZE_STORED = crypto.SIZE_1STORED
    SIZE_PARTY = crypto.SIZE_1PARTY
    PERSONAL_TABLE = "rb"

    # Gen1 has one Special stat that later games split in two. PKHeX exposes it
    # under both names, and writing SpD is a no-op, as it is there.
    @property
    def stat_spa(self) -> int:
        return self.stat_spc

    @stat_spa.setter
    def stat_spa(self, value: int) -> None:
        self.stat_spc = value

    @property
    def stat_spd(self) -> int:
        return self.stat_spc

    @stat_spd.setter
    def stat_spd(self, value: int) -> None:
        pass

    @property
    def species(self) -> int:
        return species_convert.to_national1(self.species_internal)

    @species.setter
    def species(self, value: int) -> None:
        self.species_internal = species_convert.to_internal1(value)

    @property
    def exp(self) -> int:
        """Stored as a 24-bit big-endian value."""
        return int.from_bytes(self.data[0x0E:0x11], "big")

    @exp.setter
    def exp(self, value: int) -> None:
        self.data[0x0E:0x11] = int(value).to_bytes(3, "big")


class PK2(_GBBase, _L.PK2Layout):
    """Gold/Silver/Crystal."""

    FORMAT = 2
    CONTEXT = "gen2"
    SIZE_STORED = crypto.SIZE_2STORED
    SIZE_PARTY = crypto.SIZE_2PARTY
    PERSONAL_TABLE = "c"
    LOCATION_CONTEXT = "gen2"
    LOCATION_GAME = "gsc"

    @property
    def exp(self) -> int:
        return int.from_bytes(self.data[0x08:0x0B], "big")

    @exp.setter
    def exp(self, value: int) -> None:
        self.data[0x08:0x0B] = int(value).to_bytes(3, "big")


class SK2(_L.SK2Layout):
    """Stadium 2 storage."""

    FORMAT = 2
    CONTEXT = "gen2"
    SIZE_STORED = crypto.SIZE_2STADIUM
    SIZE_PARTY = crypto.SIZE_2STADIUM
    SHINY_SHIFT = 0
    MAX_IV = 15
    PERSONAL_TABLE = "c"
    MAX_STRING_LENGTH_NICKNAME = 10
    MAX_STRING_LENGTH_TRAINER = 7


ALL_FORMATS: tuple[type, ...] = (
    PK1, PK2, SK2, PK3, CK3, XK3, PK4, BK4, RK4, PK5,
    PK6, PK7, PB7, PK8, PB8, PA8, PK9, PA9,
)

BY_NAME = {cls.__name__.lower(): cls for cls in ALL_FORMATS}
