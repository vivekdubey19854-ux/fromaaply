import pytest

from app.approval_engine import ApprovalError, approve, create_approval, read_approval
from app.storage import PrivateStorage


def test_sensitive_action_requires_approval(tmp_path):
    storage = PrivateStorage(str(tmp_path))
    a = create_approval(storage, "u1", "fill_sensitive", "s1", {"field": "pan_number", "value": "ABCDE1234F"})
    assert a.status == "pending"
    approved = approve(storage, "u1", a.approval_id, "fill_sensitive", "s1", {"field": "pan_number", "value": "ABCDE1234F"})
    assert approved.status == "approved"


def test_payload_cannot_change_after_approval(tmp_path):
    storage = PrivateStorage(str(tmp_path))
    a = create_approval(storage, "u1", "fill_sensitive", "s1", {"field": "pan_number", "value": "ABCDE1234F"})
    with pytest.raises(ApprovalError, match="payload mismatch"):
        approve(storage, "u1", a.approval_id, "fill_sensitive", "s1", {"field": "pan_number", "value": "AAAAA9999A"})


def test_blocked_material_action_never_gets_approval(tmp_path):
    storage = PrivateStorage(str(tmp_path))
    with pytest.raises(ApprovalError, match="cannot be approved"):
        create_approval(storage, "u1", "final_submission", "s1", {})


def test_user_isolation(tmp_path):
    storage = PrivateStorage(str(tmp_path))
    a = create_approval(storage, "u1", "fill_sensitive", "s1", {"field": "pan_number", "value": "ABCDE1234F"})
    with pytest.raises((KeyError, FileNotFoundError)):
        read_approval(storage, "u2", a.approval_id)
