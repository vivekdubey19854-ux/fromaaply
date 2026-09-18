import pytest
from app.orchestrator import _doc_kind, _final_submit_control, _otp_control


def test_document_kind_detection():
    assert _doc_kind("Aadhaar Card.pdf") == "identity"
    assert _doc_kind("Class 12 Marksheet.pdf") == "education_12th"
    assert _doc_kind("passport_photo.jpg") == "photo"
    assert _doc_kind("signature.png") == "signature"


def test_otp_control_detection():
    inspection={"controls":[{"index":0,"type":"text","name":"mobile"},{"index":1,"type":"text","autocomplete":"one-time-code"}]}
    assert _otp_control(inspection)==1


def test_final_submit_requires_unique_safe_candidate():
    inspection={"controls":[{"index":0,"type":"submit","text":"Submit Application"},{"index":1,"type":"button","text":"Cancel"}]}
    assert _final_submit_control(inspection)==0


def test_final_submit_refuses_ambiguous_controls():
    inspection={"controls":[{"index":0,"type":"submit","text":"Submit"},{"index":1,"type":"submit","text":"Submit"}]}
    assert _final_submit_control(inspection) is None
