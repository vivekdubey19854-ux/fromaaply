from app.form_mapping import map_controls, resolve_field_mapping


def test_self_heals_when_dom_id_and_name_change():
    controls = [
        {
            "index": 0,
            "tag": "input",
            "type": "text",
            "id": "react-8f21a",
            "name": "field_7391",
            "ariaLabel": "Applicant's full name",
            "label": "Applicant Full Name",
            "nearbyText": "Enter applicant full name exactly as on your identity document",
            "placeholder": "Enter value",
        }
    ]
    mapped = map_controls(controls)
    assert mapped[0]["field"] == "full_name"
    assert mapped[0]["self_healed"] is True
    assert mapped[0]["confidence"] >= 0.86


def test_self_healing_uses_accessibility_context_after_selector_drift():
    controls = [
        {"index": 0, "type": "text", "id": "random-a", "label": "Unrelated field", "nearbyText": "Reference code"},
        {"index": 1, "type": "text", "id": "random-b", "ariaLabel": "Mobile number", "nearbyText": "10 digit mobile number used for OTP", "placeholder": "Enter value"},
    ]
    healed = resolve_field_mapping("phone", controls, preferred_index=9)
    assert healed is not None
    assert healed.field == "phone"
    assert healed.self_healed is True
    assert healed.score >= 0.86
    assert "control index=1" in healed.reason


def test_ambiguous_self_healing_fails_closed():
    controls = [
        {"index": 0, "type": "text", "ariaLabel": "Email address", "label": "Email"},
        {"index": 1, "type": "text", "ariaLabel": "Email address", "label": "Email"},
    ]
    assert resolve_field_mapping("email", controls, preferred_index=99) is None
