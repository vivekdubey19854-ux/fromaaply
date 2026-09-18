from __future__ import annotations

import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class CredentialDecryptionError(RuntimeError):
    """Raised when an encrypted admin credential cannot be decrypted safely."""


class CredentialEncryptionError(RuntimeError):
    """Raised when the application credential encryption key is unavailable."""


def _fernet() -> Fernet:
    key = os.getenv("FORMWISE_CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if not key:
        raise CredentialEncryptionError("FORMWISE_CREDENTIAL_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(key.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise CredentialEncryptionError("FORMWISE_CREDENTIAL_ENCRYPTION_KEY is invalid") from exc


def encrypt_admin_api_key(plaintext: str) -> str:
    """Encrypt a plaintext admin API credential using the process-only Fernet key."""
    value = str(plaintext).strip()
    if not value:
        raise CredentialEncryptionError("credential is empty")
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_admin_api_key(ciphertext: Any) -> Any:
    """Decrypt an application-layer encrypted admin_api_keys value.

    FORMwise stores provider credentials as Fernet ciphertext. The key is supplied only
    through the process environment and is never persisted in the database.
    JSON credential payloads are intentionally left to the caller because this helper
    returns the decrypted string exactly as stored.
    """
    if ciphertext is None or ciphertext == "":
        raise CredentialDecryptionError("encrypted credential is empty")
    try:
        return _fernet().decrypt(str(ciphertext).encode("utf-8")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise CredentialDecryptionError("admin credential decryption failed") from exc
