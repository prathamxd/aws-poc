"""Password hashing with PBKDF2-SHA256 (Python standard library only)."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets

ALGORITHM = "pbkdf2_sha256"


def _iterations() -> int:
    # Tests lower this through the environment to run faster.
    return int(os.getenv("PASSWORD_HASH_ITERATIONS", "310000"))


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = _iterations()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return f"{ALGORITHM}${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$")
        if algorithm != ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), expected)
