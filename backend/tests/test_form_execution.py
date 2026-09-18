from app.form_execution import _blocked_page,_page_signals,_resolve_value

def test_resolve_value_requires_unique_verified_source():
    chunks=[{"text":"Profile: email: user@example.com","source_type":"profile","source_id":"u1","score":0.9}]
    result=_resolve_value("email",chunks)
    assert result and result["value"]=="user@example.com"

def test_resolve_value_rejects_ambiguous_values():
    chunks=[{"text":"email: one@example.com","source_type":"a","source_id":"1","score":0.8},{"text":"email: two@example.com","source_type":"b","source_id":"2","score":0.8}]
    assert _resolve_value("email",chunks) is None

def test_blocked_page_detects_safety_signals_without_blocking_generic_submit():
    inspection={"title":"Application Form","url":"https://example.com/apply","controls":[{"text":"I agree to declaration"},{"text":"CAPTCHA"},{"text":"Submit"}]}
    signals=_blocked_page(inspection)
    assert "captcha" not in signals
    assert "submit" not in signals
    assert "legal declaration" in signals
    assert "captcha" in _page_signals(inspection)["human"]

def test_human_gate_is_clear_after_user_fills_control():
    inspection={"title":"Application Form","url":"https://example.com/apply","controls":[{"name":"otp","value":"123456"},{"name":"captcha","value":"7X9K2"},{"text":"Submit"}]}
    signals=_page_signals(inspection)
    assert signals["human"]==[]
