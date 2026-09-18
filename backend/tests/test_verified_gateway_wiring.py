from types import SimpleNamespace

import pytest

from app.browser_use_agent import BrowserUseSafetyError, normalize_agent_field_request
from app.form_execution import _verified_gateway_value
from app.form_mapping import is_high_confidence_self_heal, map_controls


class FakeGateway:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def get_requested_field(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def test_high_confidence_self_heal_is_marked_for_gateway():
    controls = [{
        "type": "text",
        "id": "changed-123",
        "name": "field-9",
        "ariaLabel": "Date of Birth",
        "label": "Date of Birth",
        "nearbyText": "Enter date of birth",
    }]
    mapping = map_controls(controls)[0]
    assert mapping["field"] == "date_of_birth"
    assert mapping["self_healed"] is True
    assert mapping["confidence"] >= 0.86
    assert is_high_confidence_self_heal(mapping) is True


def test_gateway_requests_exactly_one_field():
    result = SimpleNamespace(
        status="verified", field="date_of_birth", value="2000-01-01",
        confidence=0.99, source_type="aadhaar", source_id="doc-1", provenance_id="prov-1",
        reason=None,
    )
    gateway = FakeGateway(result)
    resolved = _verified_gateway_value(gateway, "user-a", "date_of_birth")
    assert resolved["status"] == "verified"
    assert resolved["field"] == "date_of_birth"
    assert gateway.calls == [{"user_id": "user-a", "requested_field": "date_of_birth"}]


def test_conflict_pauses_and_returns_no_value():
    result = SimpleNamespace(status="conflict", field="date_of_birth", value=None, reason="sources disagree")
    gateway = FakeGateway(result)
    resolved = _verified_gateway_value(gateway, "user-a", "date_of_birth")
    assert resolved["status"] == "paused"
    assert "sources disagree" in resolved["reason"]
    assert "value" not in resolved


def test_not_found_pauses_and_returns_no_value():
    result = SimpleNamespace(status="not_found", field="date_of_birth", value=None, reason="no verified value")
    gateway = FakeGateway(result)
    resolved = _verified_gateway_value(gateway, "user-a", "date_of_birth")
    assert resolved["status"] == "paused"
    assert "no verified value" in resolved["reason"]
    assert "value" not in resolved


def test_browser_use_cannot_request_wildcard_or_profile_dump():
    with pytest.raises(BrowserUseSafetyError):
        normalize_agent_field_request("*")
    with pytest.raises(BrowserUseSafetyError):
        normalize_agent_field_request("profile")
    with pytest.raises(BrowserUseSafetyError):
        normalize_agent_field_request("all")
