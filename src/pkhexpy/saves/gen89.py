"""Switch-era saves: Sword/Shield, Legends Arceus, Scarlet/Violet, Legends Z-A.

These have no fixed layout. The file is a list of key-addressed blocks (see
``swish``), and each piece of save data is found by its 32-bit key. Which key
holds the boxes differs per game, so each class names the keys it needs.
"""

from __future__ import annotations

from ..binio import read_u16, read_u32
from ..pkm.formats import PA8, PA9, PK8, PK9
from . import swish
from .base import SaveFile, fit
from .swish import SCBlock


class SAV89(SaveFile):
    """A save stored as SwishCrypto blocks."""

    #: Block keys this format uses.
    KEY_BOX: int = 0
    KEY_PARTY: int = 0
    KEY_MY_STATUS: int = 0
    KEY_PLAY_TIME: int = 0
    KEY_MONEY: int | None = None
    KEY_BOX_LAYOUT: int = 0x19722C89
    KEY_CURRENT_BOX: int = 0x017C3CBB

    #: Offsets within the trainer block.
    STATUS_ID_OFFSET: int = 0
    STATUS_GAME_OFFSET: int = 4
    STATUS_GENDER_OFFSET: int = 5
    STATUS_LANGUAGE_OFFSET: int = 7
    STATUS_OT_OFFSET: int = 0x10

    #: Length of one box-name entry inside the box-layout block.
    BOX_NAME_LENGTH: int = 0x22

    #: Distance between consecutive slots. Legends Z-A pads each slot past the
    #: record it holds; everywhere else these match SIZE_BOXSLOT/SIZE_PARTY_SLOT.
    BOX_SLOT_STRIDE: int | None = None
    PARTY_SLOT_STRIDE: int | None = None

    #: How the play-time block is laid out. Sword/Shield and Legends Arceus use
    #: a 16-bit hour count followed by two bytes; Gen9 widened all three to
    #: 32-bit fields.
    PLAY_TIME_WIDE: bool = False

    def __init__(self, data: bytes | bytearray) -> None:
        super().__init__(data)
        self.blocks: list[SCBlock] = swish.decrypt(bytes(self.data))
        self._by_key = {block.key: block for block in self.blocks}

    # --- block access --------------------------------------------------------

    def block(self, key: int) -> SCBlock | None:
        return self._by_key.get(key)

    def block_data(self, key: int) -> bytearray:
        block = self.block(key)
        return block.data if block is not None else bytearray()

    @property
    def box_data(self) -> bytearray:
        return self.block_data(self.KEY_BOX)

    @property
    def party_data(self) -> bytearray:
        return self.block_data(self.KEY_PARTY)

    @property
    def status_data(self) -> bytearray:
        return self.block_data(self.KEY_MY_STATUS)

    # --- storage -------------------------------------------------------------

    @property
    def box_stride(self) -> int:
        return self.BOX_SLOT_STRIDE or self.SIZE_BOXSLOT

    @property
    def party_stride(self) -> int:
        return self.PARTY_SLOT_STRIDE or self.SIZE_PARTY_SLOT

    def box_slot_offset(self, box: int, slot: int) -> int:
        return self.box_offset(box) + slot * self.box_stride

    def box_offset(self, box: int) -> int:
        return self.box_stride * self.BOX_SLOT_COUNT * box

    def party_offset(self, slot: int) -> int:
        return self.party_stride * slot

    @property
    def party_count(self) -> int:
        data = self.party_data
        index = self.PARTY_SLOT_COUNT * self.party_stride
        return data[index] if index < len(data) else 0

    def _read_from(self, buffer: bytearray, offset: int, size: int):
        raw = bytes(buffer[offset:offset + size])
        if len(raw) < size or not self.slot_present(raw):
            return None
        entity = self.ENTITY(self.ENTITY.decrypt_buffer(raw))
        return entity if entity.species else None

    def get_box_slot(self, box: int, slot: int):
        return self._read_from(self.box_data,
                               self.box_slot_offset(box, slot), self.SIZE_BOXSLOT)

    def set_box_slot(self, box: int, slot: int, entity) -> None:
        offset = self.box_slot_offset(box, slot)
        raw = entity.encrypted_bytes() if entity is not None else b""
        self.box_data[offset:offset + self.SIZE_BOXSLOT] = fit(raw, self.SIZE_BOXSLOT)

    def get_party_slot(self, slot: int):
        return self._read_from(self.party_data,
                               self.party_offset(slot), self.SIZE_PARTY_SLOT)

    def set_party_slot(self, slot: int, entity) -> None:
        offset = self.party_offset(slot)
        raw = entity.encrypted_bytes() if entity is not None else b""
        self.party_data[offset:offset + self.SIZE_PARTY_SLOT] = fit(raw, self.SIZE_PARTY_SLOT)

    def box_name(self, box: int) -> str | None:
        data = self.block_data(self.KEY_BOX_LAYOUT)
        start = box * self.BOX_NAME_LENGTH
        if start + self.BOX_NAME_LENGTH > len(data):
            return None
        name = self.decode_string(bytes(data[start:start + self.BOX_NAME_LENGTH]))
        return name or None

    @property
    def current_box(self) -> int:
        block = self.block(self.KEY_CURRENT_BOX)
        return int(block.get_value()) if block is not None else 0

    # --- trainer -------------------------------------------------------------

    @property
    def trainer_name(self) -> str:
        data = self.status_data
        start = self.STATUS_OT_OFFSET
        return self.decode_string(bytes(data[start:start + 0x1A]))

    @property
    def tid16(self) -> int:
        return read_u16(self.status_data, self.STATUS_ID_OFFSET)

    @property
    def sid16(self) -> int:
        return read_u16(self.status_data, self.STATUS_ID_OFFSET + 2)

    @property
    def version(self) -> int:
        return self.status_data[self.STATUS_GAME_OFFSET]

    @property
    def trainer_gender(self) -> int:
        return self.status_data[self.STATUS_GENDER_OFFSET]

    @property
    def language(self) -> int:
        return self.status_data[self.STATUS_LANGUAGE_OFFSET]

    @property
    def play_time(self) -> tuple[int, int, int]:
        data = self.block_data(self.KEY_PLAY_TIME)
        if self.PLAY_TIME_WIDE:
            if len(data) < 12:
                return (0, 0, 0)
            return read_u32(data, 0), read_u32(data, 4), read_u32(data, 8)
        if len(data) < 4:
            return (0, 0, 0)
        return read_u16(data, 0), data[2], data[3]

    @property
    def money(self) -> int | None:
        if self.KEY_MONEY is None:
            return None
        block = self.block(self.KEY_MONEY)
        return int(block.get_value()) if block is not None else None

    # --- integrity -----------------------------------------------------------

    @property
    def checksums_valid(self) -> bool:
        """These saves have one SHA-256 over the whole payload, not per-block."""
        return swish.is_hash_valid(bytes(self.data))

    def fix_checksums(self) -> None:
        self.data = bytearray(swish.encrypt(self.blocks))

    def to_bytes(self) -> bytes:
        return bytes(swish.encrypt(self.blocks))


class SAV8SWSH(SAV89):
    KEY = "swsh"
    GAME = "Sword/Shield"
    GENERATION = 8
    STRING_GENERATION = 8
    ENTITY = PK8
    BOX_COUNT = 32
    SIZE_BOXSLOT = 0x158        # SW/SH stores party-sized slots in boxes
    SIZE_PARTY_SLOT = 0x158
    KEY_BOX = 0x0D66012C
    KEY_PARTY = 0x2985FE5D
    KEY_MY_STATUS = 0xF25C070E
    KEY_PLAY_TIME = 0x8CBBFD90
    STATUS_ID_OFFSET = 0xA0
    STATUS_GAME_OFFSET = 0xA4
    STATUS_GENDER_OFFSET = 0xA5
    STATUS_LANGUAGE_OFFSET = 0xA7
    STATUS_OT_OFFSET = 0xB0


class SAV8LA(SAV89):
    KEY = "la"
    GAME = "Legends: Arceus"
    GENERATION = 8
    STRING_GENERATION = 8
    ENTITY = PA8
    BOX_COUNT = 32
    SIZE_BOXSLOT = 0x168
    SIZE_PARTY_SLOT = 0x178
    KEY_BOX = 0x47E1CEAB
    KEY_PARTY = 0x2985FE5D
    KEY_MY_STATUS = 0xF25C070E
    KEY_PLAY_TIME = 0xC4FA7C8C
    KEY_MONEY = 0x3279D927
    STATUS_ID_OFFSET = 0x10
    STATUS_GAME_OFFSET = 0x14
    STATUS_GENDER_OFFSET = 0x15
    STATUS_LANGUAGE_OFFSET = 0x17
    STATUS_OT_OFFSET = 0x20


class SAV9SV(SAV89):
    KEY = "sv"
    GAME = "Scarlet/Violet"
    GENERATION = 9
    STRING_GENERATION = 9
    ENTITY = PK9
    BOX_COUNT = 32
    SIZE_BOXSLOT = 0x158
    SIZE_PARTY_SLOT = 0x158
    KEY_BOX = 0x0D66012C
    KEY_PARTY = 0x3AA1A9AD
    KEY_MY_STATUS = 0xE3E89BD1
    KEY_PLAY_TIME = 0xEDAFF794
    KEY_MONEY = 0x4F35D0DD
    PLAY_TIME_WIDE = True


class SAV9ZA(SAV9SV):
    """Legends: Z-A.

    Shares Scarlet/Violet's block keys but not its storage geometry: every slot
    is padded past the record it holds, the party count is found by scanning
    rather than stored, and the file carries no checksums beyond the whole-file
    hash that SwishCrypto already covers.
    """

    KEY = "za"
    GAME = "Legends: Z-A"
    ENTITY = PA9
    #: 0x158 record plus 0x40 of padding.
    BOX_SLOT_STRIDE = 0x158 + 0x40
    #: 0x158 record plus 0x48, then the same 0x40 padding.
    PARTY_SLOT_STRIDE = 0x158 + 0x48 + 0x40

    @property
    def party_count(self) -> int:
        """Z-A stores no count; the party runs until the first empty slot."""
        data = self.party_data
        for slot in range(self.PARTY_SLOT_COUNT):
            start = self.party_offset(slot)
            raw = bytes(data[start:start + self.SIZE_PARTY_SLOT])
            if len(raw) < self.SIZE_PARTY_SLOT or not self.slot_present(raw):
                return slot
        return self.PARTY_SLOT_COUNT

    @property
    def checksums_valid(self) -> bool:
        """Z-A keeps no per-block checksums; only the whole-file hash applies."""
        return swish.is_hash_valid(bytes(self.data))
