"""Shared entity behavior layered on top of the generated field layouts.

Everything here is derived from fields rather than stored: level from EXP,
shininess from the trainer and personality values, the met date from its three
byte components. Formats override the class constants that these depend on.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
from typing import Any
from collections.abc import Callable, Iterable

from .. import data
from .layout import LayoutBase


class Entity(LayoutBase):
    """A single Pokemon record."""

    #: Entity context name, matching PKHeX (``gen9``, ``gen8a``, ``gen7b``, ...).
    CONTEXT: str = ""
    #: Key into the packaged personal tables, for growth rate and gender ratio.
    PERSONAL_TABLE: str = ""
    #: Which met-location list this format's location ids index into.
    LOCATION_CONTEXT: str = ""
    LOCATION_GAME: str = ""

    MAX_IV: int = 31
    MAX_EV: int = 252
    MAX_STRING_LENGTH_NICKNAME: int = 12
    MAX_STRING_LENGTH_TRAINER: int = 12

    #: Trainer and personality values are compared after this right shift; Gen3-5
    #: use 3 (8 shiny frames) and Gen6 onward use 4 (16 frames).
    SHINY_SHIFT: int = 4

    #: Whole-buffer encryption for this format, or None when stored in the clear.
    _encrypt: Callable[[bytearray], None] | None = None
    _decrypt_if_encrypted: Callable[[bytearray], None] | None = None

    # --- identity -----------------------------------------------------------

    @property
    def extension(self) -> str:
        return type(self).__name__.lower()

    @property
    def generation(self) -> int:
        """Generation of the originating game, which can differ from the format."""
        return self.FORMAT

    @property
    def encryption_constant(self) -> int:
        """The value the shuffle and cipher are keyed from.

        Gen6 onward stores this as its own 32-bit field at offset 0. Gen3 to 5
        reuse the PID for it, and Gen1/2 have neither.
        """
        return self.pid

    # --- trainer and shininess ---------------------------------------------

    @property
    def tsv(self) -> int:
        """Trainer shiny value."""
        return (self.tid16 ^ self.sid16) >> self.SHINY_SHIFT

    @property
    def psv(self) -> int:
        """Personality shiny value."""
        pid = self.pid
        return ((pid >> 16) ^ (pid & 0xFFFF)) >> self.SHINY_SHIFT

    @property
    def shiny_xor(self) -> int:
        combined = self.id32 ^ self.pid
        return (combined ^ (combined >> 16)) & 0xFFFF

    @property
    def is_shiny(self) -> bool:
        return self.tsv == self.psv

    # --- level and stats ----------------------------------------------------

    @property
    def growth_rate(self) -> int:
        return data.growth_rate(self.PERSONAL_TABLE, self.species)

    @property
    def current_level(self) -> int:
        """Level implied by EXP and the species' growth curve."""
        table = data.experience_tables()[self.growth_rate]
        exp = self.exp
        if exp >= table[-1]:
            return 100
        level = 1
        while level < 100 and exp >= table[level]:
            level += 1
        return level

    @current_level.setter
    def current_level(self, value: int) -> None:
        value = max(1, min(100, int(value)))
        self.exp = data.experience_tables()[self.growth_rate][value - 1]

    @property
    def ivs(self) -> tuple[int, ...]:
        """IVs in PKHeX's order: HP, ATK, DEF, SPE, SPA, SPD."""
        return (self.iv_hp, self.iv_atk, self.iv_def,
                self.iv_spe, self.iv_spa, self.iv_spd)

    @ivs.setter
    def ivs(self, value: Iterable[int]) -> None:
        (self.iv_hp, self.iv_atk, self.iv_def,
         self.iv_spe, self.iv_spa, self.iv_spd) = value

    @property
    def evs(self) -> tuple[int, ...]:
        return (self.ev_hp, self.ev_atk, self.ev_def,
                self.ev_spe, self.ev_spa, self.ev_spd)

    @evs.setter
    def evs(self, value: Iterable[int]) -> None:
        (self.ev_hp, self.ev_atk, self.ev_def,
         self.ev_spe, self.ev_spa, self.ev_spd) = value

    @property
    def iv_total(self) -> int:
        return sum(self.ivs)

    @property
    def ev_total(self) -> int:
        return sum(self.evs)

    @property
    def moves(self) -> tuple[int, ...]:
        return (self.move1, self.move2, self.move3, self.move4)

    @moves.setter
    def moves(self, value: Iterable[int]) -> None:
        self.move1, self.move2, self.move3, self.move4 = value

    @property
    def move_pps(self) -> tuple[int, ...]:
        return (self.move1_pp, self.move2_pp, self.move3_pp, self.move4_pp)

    @property
    def move_pp_ups(self) -> tuple[int, ...]:
        return (self.move1_pp_ups, self.move2_pp_ups,
                self.move3_pp_ups, self.move4_pp_ups)

    @property
    def relearn_moves(self) -> tuple[int, ...]:
        if not hasattr(type(self), "relearn_move1"):
            return ()
        return (self.relearn_move1, self.relearn_move2,
                self.relearn_move3, self.relearn_move4)

    # --- dates --------------------------------------------------------------

    @staticmethod
    def _to_date(year: int, month: int, day: int) -> _dt.date | None:
        if not (year or month or day):
            return None
        try:
            return _dt.date(2000 + year, month, day)
        except ValueError:
            return None

    @property
    def met_date(self) -> _dt.date | None:
        if not hasattr(type(self), "met_year"):
            return None
        return self._to_date(self.met_year, self.met_month, self.met_day)

    @met_date.setter
    def met_date(self, value: _dt.date | None) -> None:
        if value is None:
            self.met_year = self.met_month = self.met_day = 0
        else:
            self.met_year = value.year - 2000
            self.met_month = value.month
            self.met_day = value.day

    @property
    def egg_met_date(self) -> _dt.date | None:
        if not hasattr(type(self), "egg_year"):
            return None
        return self._to_date(self.egg_year, self.egg_month, self.egg_day)

    @egg_met_date.setter
    def egg_met_date(self, value: _dt.date | None) -> None:
        if value is None:
            self.egg_year = self.egg_month = self.egg_day = 0
        else:
            self.egg_year = value.year - 2000
            self.egg_month = value.month
            self.egg_day = value.day

    # --- names stored in the record -----------------------------------------

    def _read_name(self, span_field: str) -> str:
        return self.decode_string(getattr(self, span_field))

    def encode_name(self, size: int, value: str, max_chars: int) -> bytearray:
        """Encode a name into a ``size``-byte buffer, refusing to mangle it.

        Older games have per-language glyph tables, and a character missing from
        the one in use terminates the string where it appears. Left alone that
        turns into a silently truncated or empty name, so the text is decoded
        back and compared before the caller commits it.
        """
        buffer = bytearray(size)
        self.encode_string(buffer, value, max_chars)
        wanted = value[:max_chars]
        got = self.decode_string(bytes(buffer))
        if got != wanted:
            raise ValueError(
                f"{wanted!r} cannot be written in this entity's encoding "
                f"(generation {self.string_generation}, "
                f"language {self.name_language}); it would be stored as {got!r}"
            )
        return buffer

    def _write_name(self, span_field: str, value: str, max_chars: int) -> None:
        field = type(self)._fields[span_field]
        buffer = self.encode_name(field.length, value, max_chars)
        self.data[field.offset:field.offset + field.length] = buffer

    @property
    def nickname(self) -> str:
        return self._read_name("nickname_trash")

    @nickname.setter
    def nickname(self, value: str) -> None:
        self._write_name("nickname_trash", value, self.MAX_STRING_LENGTH_NICKNAME)

    @property
    def original_trainer_name(self) -> str:
        return self._read_name("original_trainer_trash")

    @original_trainer_name.setter
    def original_trainer_name(self, value: str) -> None:
        self._write_name("original_trainer_trash", value,
                         self.MAX_STRING_LENGTH_TRAINER)

    @property
    def handling_trainer_name(self) -> str:
        if "handling_trainer_trash" not in type(self)._fields:
            return ""
        return self._read_name("handling_trainer_trash")

    @handling_trainer_name.setter
    def handling_trainer_name(self, value: str) -> None:
        self._write_name("handling_trainer_trash", value,
                         self.MAX_STRING_LENGTH_TRAINER)

    # --- integrity ----------------------------------------------------------

    def calculate_checksum(self) -> int:
        """Formats with a stored checksum override this."""
        raise NotImplementedError(f"{type(self).__name__} has no checksum")

    @property
    def checksum_valid(self) -> bool:
        try:
            return self.calculate_checksum() == self.checksum
        except (NotImplementedError, AttributeError):
            return True

    def refresh_checksum(self) -> None:
        # Formats without a stored checksum have nothing to refresh.
        with contextlib.suppress(NotImplementedError, AttributeError):
            self.checksum = self.calculate_checksum()

    # --- encryption ---------------------------------------------------------

    def encrypted_bytes(self) -> bytes:
        """The buffer as the game stores it, checksum refreshed."""
        self.refresh_checksum()
        buffer = bytearray(self.data)
        if self._encrypt is not None:
            type(self)._encrypt(buffer)
        return bytes(buffer)

    @classmethod
    def decrypt_buffer(cls, data_in: bytes | bytearray) -> bytearray:
        buffer = bytearray(data_in)
        if cls._decrypt_if_encrypted is not None:
            cls._decrypt_if_encrypted(buffer)
        return buffer

    # --- names --------------------------------------------------------------

    def name_of(self, kind: str, index: int, language: str | None = None) -> str | None:
        return data.lookup(kind, index, language or self.name_language)

    @property
    def name_language(self) -> str:
        return data.language_code(self.string_language)

    @property
    def species_name(self) -> str | None:
        return self.name_of("species", self.species)

    @property
    def met_location_name(self) -> str | None:
        if not self.LOCATION_CONTEXT or not hasattr(type(self), "met_location"):
            return None
        return data.location_name(self.LOCATION_CONTEXT, self.LOCATION_GAME,
                                  self.met_location, self.name_language)

    def field_value(self, name: str) -> Any:
        return getattr(self, name)
