"""Tests for services/auth_service.py"""

import os
import time

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests")

from services.auth_service import hash_password, verify_password, create_token, decode_token


class TestPasswordHashing:
    def test_hash_returns_string(self):
        h = hash_password("test123")
        assert isinstance(h, str)
        assert h != "test123"

    def test_verify_correct_password(self):
        h = hash_password("mysecret")
        assert verify_password("mysecret", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("mysecret")
        assert verify_password("wrong", h) is False

    def test_different_hashes_for_same_password(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt uses random salt

    def test_round_trip(self):
        password = "complex!@#$%^&*()_+123"
        h = hash_password(password)
        assert verify_password(password, h) is True


class TestJwtTokens:
    def test_create_token_returns_string(self):
        token = create_token("user-1", "admin")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_decode_valid_token(self):
        token = create_token("user-1", "admin")
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user-1"
        assert payload["role"] == "admin"

    def test_decode_invalid_token(self):
        result = decode_token("invalid.token.here")
        assert result is None

    def test_decode_empty_token(self):
        result = decode_token("")
        assert result is None

    def test_token_contains_exp_and_iat(self):
        token = create_token("user-1", "user")
        payload = decode_token(token)
        assert "exp" in payload
        assert "iat" in payload

    def test_expired_token(self):
        import jwt as pyjwt
        from datetime import datetime, timezone, timedelta
        payload = {
            "sub": "user-1",
            "role": "user",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        token = pyjwt.encode(payload, "test-secret-key-for-unit-tests", algorithm="HS256")
        assert decode_token(token) is None

    def test_wrong_secret(self):
        import jwt as pyjwt
        from datetime import datetime, timezone, timedelta
        payload = {
            "sub": "user-1",
            "role": "user",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "iat": datetime.now(timezone.utc),
        }
        token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")
        assert decode_token(token) is None
