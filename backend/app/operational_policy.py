from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class PauseReason(str, Enum):
    CAPTCHA = "captcha"
    OTP = "otp"
    LEGAL_DECLARATION = "legal_declaration"
    PAYMENT = "payment"
    FINAL_SUBMISSION = "final_submission"
    UNEXPECTED_ERROR = "unexpected_error"


@dataclass(frozen=True)
class OperationalDecision:
    allowed: bool
    pause: bool = False
    reason: PauseReason | None = None
    message: str | None = None


BLOCKED_ACTION_TERMS = {
    "captcha": PauseReason.CAPTCHA,
    "recaptcha": PauseReason.CAPTCHA,
    "hcaptcha": PauseReason.CAPTCHA,
    "otp": PauseReason.OTP,
    "one time password": PauseReason.OTP,
    "verification code": PauseReason.OTP,
    "legal declaration": PauseReason.LEGAL_DECLARATION,
    "self attestation": PauseReason.LEGAL_DECLARATION,
    "terms and conditions": PauseReason.LEGAL_DECLARATION,
    "payment": PauseReason.PAYMENT,
    "card number": PauseReason.PAYMENT,
    "banking": PauseReason.PAYMENT,
    "pay & submit": PauseReason.FINAL_SUBMISSION,
    "pay and submit": PauseReason.FINAL_SUBMISSION,
    "final submit": PauseReason.FINAL_SUBMISSION,
    "confirm application": PauseReason.FINAL_SUBMISSION,
    "final submission": PauseReason.FINAL_SUBMISSION,
}


def classify_page_text(text: str) -> OperationalDecision:
    """Classify safety-relevant page text without attempting to solve it."""
    normalized = (text or "").lower()
    for term, reason in BLOCKED_ACTION_TERMS.items():
        if term in normalized:
            messages = {
                PauseReason.CAPTCHA: "PAUSED: CAPTCHA detected. Please solve it manually.",
                PauseReason.OTP: "PAUSED: OTP/verification code requested. Please enter it manually.",
                PauseReason.LEGAL_DECLARATION: "PAUSED: Legal declaration/self-attestation requires your manual action.",
                PauseReason.PAYMENT: "PAUSED: Payment or banking step detected.",
                PauseReason.FINAL_SUBMISSION: "PAUSED: Final submission requires your explicit approval.",
            }
            return OperationalDecision(False, True, reason, messages[reason])
    return OperationalDecision(True)


def action_decision(action: str, *, final_submission: bool = False) -> OperationalDecision:
    """Return the hard boundary for an agent action."""
    normalized = (action or "").strip().lower()
    if final_submission or normalized in {"submit", "final_submit", "confirm_application", "pay_and_submit"}:
        return OperationalDecision(False, True, PauseReason.FINAL_SUBMISSION, "PAUSED: Final submission requires your explicit approval.")
    if normalized in {"captcha", "solve_captcha", "bypass_captcha", "anti_bot_bypass"}:
        return OperationalDecision(False, True, PauseReason.CAPTCHA, "PAUSED: CAPTCHA/anti-bot challenge requires manual action.")
    if normalized in {"otp", "enter_otp", "verification_code"}:
        return OperationalDecision(False, True, PauseReason.OTP, "PAUSED: OTP/verification code requires manual action.")
    if normalized in {"legal_declaration", "self_attestation", "accept_terms"}:
        return OperationalDecision(False, True, PauseReason.LEGAL_DECLARATION, "PAUSED: Legal declaration requires manual action.")
    if normalized in {"payment", "pay", "card_payment", "banking"}:
        return OperationalDecision(False, True, PauseReason.PAYMENT, "PAUSED: Payment/banking step detected.")
    return OperationalDecision(True)


def filter_agent_actions(actions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], OperationalDecision | None]:
    """Keep safe navigation/fill actions and stop before the first restricted action."""
    safe: list[dict[str, Any]] = []
    for action in actions:
        decision = action_decision(str(action.get("action", action.get("type", ""))))
        if not decision.allowed:
            return safe, decision
        safe.append(action)
    return safe, None
