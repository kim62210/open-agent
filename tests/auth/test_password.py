"""Password hashing and verification tests."""

from core.auth.password import hash_password, verify_password


class TestPasswordHashing:
    """hash_password / verify_password round-trip."""

    def test_hash_and_verify_round_trip(self):
        """Hashed password verifies correctly."""
        plain = "secureP@ss123"
        hashed = hash_password(plain)

        assert verify_password(plain, hashed) is True

    def test_wrong_password_fails_verification(self):
        """Incorrect password does not verify."""
        hashed = hash_password("correctpass")

        assert verify_password("wrongpass", hashed) is False

    def test_different_hashes_for_same_password(self):
        """Same password produces different hashes (salted)."""
        plain = "samePassword!"
        h1 = hash_password(plain)
        h2 = hash_password(plain)

        assert h1 != h2
        # Both still verify
        assert verify_password(plain, h1) is True
        assert verify_password(plain, h2) is True

    def test_hash_is_not_plaintext(self):
        """Hashed output does not contain the original password."""
        plain = "mySecret42"
        hashed = hash_password(plain)

        assert plain not in hashed

    def test_empty_password_hashes(self):
        """Empty string can be hashed and verified (library handles it)."""
        hashed = hash_password("")

        assert verify_password("", hashed) is True
        assert verify_password("notempty", hashed) is False
