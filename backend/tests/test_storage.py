from pathlib import Path

import pytest

from app.storage import PrivateStorage


def test_storage_isolated_by_user(tmp_path: Path) -> None:
    storage = PrivateStorage(str(tmp_path))
    storage.save("user-a", "doc.pdf", b"secret")
    assert storage.read("user-a", "doc.pdf") == b"secret"
    with pytest.raises(FileNotFoundError):
        storage.read("user-b", "doc.pdf")


def test_storage_rejects_traversal(tmp_path: Path) -> None:
    storage = PrivateStorage(str(tmp_path))
    with pytest.raises(ValueError):
        storage.key_path("user-a", "../user-b/secret.pdf")
