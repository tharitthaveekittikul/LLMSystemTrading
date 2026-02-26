"""Credential encryption using Fernet symmetric encryption.

All broker passwords must be encrypted before storage and decrypted only
at the moment of MT5 connection. The key lives exclusively in .env.
"""
from cryptography.fernet import Fernet

from core.config import settings


def _cipher() -> Fernet:
    return Fernet(settings.encryption_key.encode())


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns a URL-safe base64-encoded token."""
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a token back to plaintext."""
    return _cipher().decrypt(ciphertext.encode()).decode()
