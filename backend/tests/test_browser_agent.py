import socket

import pytest

from app.browser_agent import BrowserSafetyError, validate_navigation_url


def test_allows_public_https_url(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    assert validate_navigation_url("https://example.com/form") == "https://example.com/form"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://user:pass@example.com/",
        "http://localhost:8000/",
    ],
)
def test_blocks_unsafe_url_shapes(url):
    with pytest.raises(BrowserSafetyError):
        validate_navigation_url(url)


def test_blocks_private_resolved_destination(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
    )
    with pytest.raises(BrowserSafetyError):
        validate_navigation_url("https://example.com/")
