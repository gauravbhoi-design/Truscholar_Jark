"""AES-256-GCM encryption for storing user cloud credentials securely."""

import base64
import os

import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

logger = structlog.get_logger()


def _get_key() -> bytes:
    """Get the 32-byte encryption key from settings."""
    settings = get_settings()
    key_b64 = settings.credentials_encryption_key
    if not key_b64:
        raise ValueError(
            "CREDENTIALS_ENCRYPTION_KEY is not set. "
            "Generate one with: python -c \"import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())\""
        )
    return base64.urlsafe_b64decode(key_b64)


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return base64-encoded ciphertext (nonce + ciphertext)."""
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce for GCM
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    # Prepend nonce to ciphertext and base64 encode
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("utf-8")


def decrypt(encrypted_b64: str) -> str:
    """Decrypt a base64-encoded ciphertext (nonce + ciphertext) back to string."""
    key = _get_key()
    aesgcm = AESGCM(key)
    raw = base64.urlsafe_b64decode(encrypted_b64)
    nonce = raw[:12]
    ciphertext = raw[12:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


def generate_encryption_key() -> str:
    """Generate a new base64-encoded 256-bit key."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode("utf-8")
