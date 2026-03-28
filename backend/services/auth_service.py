"""Authentication service — password hashing, JWT token management."""

import os
import secrets
from datetime import datetime, timezone, timedelta
import bcrypt
import jwt

from config import JWT_SECRET

TOKEN_EXPIRY_HOURS = 24
_jwt_secret: str = JWT_SECRET


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _get_secret() -> str:
    global _jwt_secret
    if not _jwt_secret:
        import config
        _jwt_secret = config.JWT_SECRET
    return _jwt_secret


def create_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _get_secret(), algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, _get_secret(), algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def ensure_jwt_secret():
    """Generate and write JWT_SECRET to .env if missing."""
    global _jwt_secret
    import config

    if config.JWT_SECRET:
        _jwt_secret = config.JWT_SECRET
        return

    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")

    # Read existing content
    existing = ""
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            existing = f.read()

    # Check if JWT_SECRET already in file
    for line in existing.splitlines():
        line = line.strip()
        if line.startswith("JWT_SECRET=") and len(line) > len("JWT_SECRET="):
            secret = line.split("=", 1)[1].strip().strip("'\"")
            if secret:
                _jwt_secret = secret
                config.JWT_SECRET = secret
                return

    # Generate new secret
    secret = secrets.token_hex(32)
    _jwt_secret = secret
    config.JWT_SECRET = secret

    from dotenv import set_key
    if not os.path.exists(env_path):
        with open(env_path, "w") as f:
            f.write("")
    set_key(env_path, "JWT_SECRET", secret)
