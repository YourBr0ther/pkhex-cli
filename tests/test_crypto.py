"""Entity encryption round trips."""

from __future__ import annotations

import pytest

from pkhexpy import crypto


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
