from app.operational_policy import PauseReason, action_decision, classify_page_text, filter_agent_actions


def test_captcha_pauses():
    result = classify_page_text("Please complete reCAPTCHA")
    assert result.pause is True
    assert result.reason == PauseReason.CAPTCHA


def test_otp_pauses():
    result = classify_page_text("Enter OTP sent to your mobile")
    assert result.reason == PauseReason.OTP


def test_legal_declaration_pauses():
    result = action_decision("self_attestation")
    assert result.reason == PauseReason.LEGAL_DECLARATION


def test_payment_pauses():
    result = action_decision("payment")
    assert result.reason == PauseReason.PAYMENT


def test_final_submit_pauses():
    result = action_decision("submit", final_submission=True)
    assert result.reason == PauseReason.FINAL_SUBMISSION


def test_safe_actions_are_preserved_until_first_restricted_action():
    safe, pause = filter_agent_actions([
        {"action": "navigate"},
        {"action": "fill"},
        {"action": "otp"},
        {"action": "submit"},
    ])
    assert [x["action"] for x in safe] == ["navigate", "fill"]
    assert pause is not None
    assert pause.reason == PauseReason.OTP
