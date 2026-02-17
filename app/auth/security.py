from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


class PasswordService:
    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or PasswordHasher()

    def hash_password(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify_password(self, password_hash: str, password: str) -> bool:
        try:
            return bool(self._hasher.verify(password_hash, password))
        except (InvalidHashError, VerificationError):
            return False

