import pytest

from app.security import sha256_bytes, validate_upload


def test_sha256_is_deterministic() -> None:
    assert sha256_bytes(b"formwise") == sha256_bytes(b"formwise")


def test_upload_accepts_supported_matching_type() -> None:
    validate_upload("id.pdf", "application/pdf", 10, 1000)


def test_upload_rejects_unsupported_type() -> None:
    with pytest.raises(ValueError):
        validate_upload("x.exe", "application/octet-stream", 10, 1000)


def test_upload_rejects_path_traversal_filename() -> None:
    with pytest.raises(ValueError):
        validate_upload("../secret.pdf", "application/pdf", 10, 1000)


def test_upload_rejects_extension_mismatch() -> None:
    with pytest.raises(ValueError):
        validate_upload("id.jpg", "application/pdf", 10, 1000)


def test_upload_rejects_oversized_file() -> None:
    with pytest.raises(ValueError):
        validate_upload("id.pdf", "application/pdf", 1001, 1000)
