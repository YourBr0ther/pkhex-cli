"""Entity encryption round trips."""

from __future__ import annotations

import pytest

from pkhexpy import binio, crypto


@pytest.mark.parametrize("encrypt,decrypt,size", [
    (crypto.encrypt3, crypto.decrypt3, crypto.SIZE_3STORED),
    (crypto.encrypt45, crypto.decrypt45, crypto.SIZE_4STORED),
    (crypto.encrypt45, crypto.decrypt45, crypto.SIZE_4PARTY),
    (crypto.encrypt67, crypto.decrypt67, crypto.SIZE_6STORED),
    (crypto.encrypt67, crypto.decrypt67, crypto.SIZE_6PARTY),
    (crypto.encrypt8, crypto.decrypt8, crypto.SIZE_8STORED),
    (crypto.encrypt8, crypto.decrypt8, crypto.SIZE_8PARTY),
    (crypto.encrypt8a, crypto.decrypt8a, crypto.SIZE_8ASTORED),
])
def test_encrypt_decrypt_is_reversible(encrypt, decrypt, size: int) -> None:
    original = bytes((i * 7 + 13) & 0xFF for i in range(size))
    buffer = bytearray(original)
    encrypt(buffer)
    assert bytes(buffer) != original, "encryption should change the payload"
    decrypt(buffer)
    assert bytes(buffer) == original


def test_shuffle_covers_all_permutations() -> None:
    """Every shuffle value must be undone by its inverted counterpart."""
    for sv in range(24):
        data = bytearray(range(8 + 4 * 8))
        original = bytes(data)
        crypto._shuffle(data, 8, sv, 8)
        crypto._shuffle(data, 8, crypto.BLOCK_POSITION_INVERT[sv], 8)
        assert bytes(data) == original, f"shuffle value {sv} did not round trip"


def test_add16_matches_manual_sum() -> None:
    data = bytes([0x01, 0x02, 0x03, 0x04])
    assert crypto.add16(data) == (0x0201 + 0x0403) & 0xFFFF


def test_a_short_read_raises_rather_than_returning_a_smaller_number() -> None:
    """Slicing past the end of a buffer yields fewer bytes and decodes to a
    plausible value. Every offset here is fixed by a file format, so a read
    that does not fit is a bug, and a believable answer hides it."""
    for read, size in ((binio.read_u16, 2), (binio.read_u32, 4),
                       (binio.read_u64, 8), (binio.read_u16_be, 2),
                       (binio.read_u32_be, 4)):
        buffer = bytearray(size - 1)
        with pytest.raises(IndexError):
            read(buffer, 0)
        # A full-width read at the start of a big enough buffer still works.
        assert read(bytearray(size), 0) == 0


def test_a_negative_offset_raises_rather_than_reading_from_the_end() -> None:
    """A negative offset slices to nothing and used to decode as zero, so an
    offset computed one subtraction wrong returned a clean answer."""
    with pytest.raises(IndexError):
        binio.read_u32(bytearray(range(8)), -4)
    with pytest.raises(IndexError):
        binio.read_int(bytearray(range(8)), -1, 2)
