from datetime import date
from types import SimpleNamespace

import pytest

from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.db_models import AddressRecord, EducationRecord, ProfileRecord
from app.verified_data_repository import VerifiedDataRepository, VerifiedField
from app.verified_data_service import VerifiedDataService, VerifiedDataStatus
from app.browser_use_agent import BrowserUseSafetyError, normalize_agent_field_request
from app.form_execution import _verified_gateway_value
from app.form_mapping import is_high_confidence_self_heal, map_controls


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_on_demand_profile_field_is_verified_and_scoped():
    db = make_db()
    db.add(ProfileRecord(user_id="u1", full_name="Demo User", date_of_birth=date(2000, 1, 2)))
    db.commit()
    result = VerifiedDataService(db).get_field("u1", "full_name")
    assert result.status == VerifiedDataStatus.VERIFIED
    assert result.value == "Demo User"
    db.close()


def test_missing_field_returns_not_found_without_value():
    db = make_db()
    db.add(ProfileRecord(user_id="u1", full_name="Demo User"))
    db.commit()
    result = VerifiedDataService(db).get_field("u1", "phone")
    assert result.status == VerifiedDataStatus.NOT_FOUND
    assert result.value is None
    db.close()


def test_duplicate_permanent_address_is_conflict():
    db = make_db()
    db.add(ProfileRecord(user_id="u1", full_name="Demo User"))
    db.add_all([
        AddressRecord(user_id="u1", label="permanent", line1="One"),
        AddressRecord(user_id="u1", label="permanent", line1="Two"),
    ])
    db.commit()
    result = VerifiedDataService(db).get_field("u1", "permanent_address.line1")
    assert result.status == VerifiedDataStatus.CONFLICT
    assert result.value is None
    db.close()


def test_duplicate_latest_education_is_conflict():
    db = make_db()
    db.add(ProfileRecord(user_id="u1", full_name="Demo User"))
    db.add_all([
        EducationRecord(user_id="u1", qualification="BSc", passing_year=2024),
        EducationRecord(user_id="u1", qualification="BA", passing_year=2024),
    ])
    db.commit()
    result = VerifiedDataService(db).get_field("u1", "education.latest.qualification")
    assert result.status == VerifiedDataStatus.CONFLICT
    assert result.value is None
    db.close()


def test_arbitrary_field_is_rejected():
    db = make_db()
    result = VerifiedDataService(db).get_field("u1", "profiles.secret_column")
    assert result.status == VerifiedDataStatus.INVALID_FIELD
    assert result.value is None
    db.close()


def _schema(db):
    db.execute(sa_text("""
        CREATE TABLE field_provenance (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, field_name TEXT NOT NULL,
            field_value TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT,
            source_locator TEXT, confidence REAL NOT NULL,
            verification_status TEXT NOT NULL, verified_at TEXT,
            revoked_at TEXT, created_at TEXT
        )
    """))
    db.commit()


def _insert(db, **kwargs):
    cols = ", ".join(kwargs)
    vals = ", ".join(f":{key}" for key in kwargs)
    db.execute(sa_text(f"INSERT INTO field_provenance ({cols}) VALUES ({vals})"), kwargs)
    db.commit()


def candidate(value, confidence, source_type, source_id):
    return VerifiedField(
        field="date_of_birth", value=value, confidence=confidence,
        verification_status="verified", source_type=source_type,
        source_id=source_id, source_locator="page:1",
        provenance_id=f"prov-{source_id}", verified_at=None,
    )


def test_repository_user_scoped_verified_read():
    db = make_db()
    _schema(db)
    common = dict(field_name="phone", source_locator="page:1", confidence=0.99,
                  verification_status="verified", verified_at="2026-01-01",
                  revoked_at=None, created_at="2026-01-01")
    _insert(db, id="1", user_id="u1", field_value="9999999999", source_type="manual", source_id="m1", **common)
    _insert(db, id="2", user_id="u2", field_value="8888888888", source_type="manual", source_id="m2", **common)
    result = VerifiedDataRepository(db).get_verified_field("u1", "phone")
    assert result.status == "verified"
    assert result.value == "9999999999"


def test_conflicting_verified_sources_fail_closed():
    db = make_db()
    _schema(db)
    common = dict(user_id="u1", field_name="phone", source_locator="page:1",
                  confidence=0.95, verification_status="verified",
                  verified_at="2026-01-01", revoked_at=None, created_at="2026-01-01")
    _insert(db, id="1", field_value="9999999999", source_type="aadhaar", source_id="a", **common)
    _insert(db, id="2", field_value="8888888888", source_type="pan", source_id="b", **common)
    result = VerifiedDataRepository(db).get_verified_field("u1", "phone")
    assert result.status == "conflict"
    assert result.value is None
    assert len(result.candidates) == 2


def test_unverified_values_are_never_returned():
    db = make_db()
    _schema(db)
    _insert(db, id="1", user_id="u1", field_name="pan_number", field_value="ABCDE1234F",
            source_type="pan", source_id="doc-1", source_locator="page:1",
            confidence=0.99, verification_status="review_required",
            verified_at=None, revoked_at=None, created_at="2026-01-01")
    result = VerifiedDataRepository(db).get_verified_field("u1", "pan_number")
    assert result.status == "not_found"


class FakeRepository:
    def __init__(self, result):
        self.result = result
        self.calls = []
    def get_verified_field(self, user_id, field, *, min_confidence):
        self.calls.append((user_id, field, min_confidence))
        return self.result


def test_only_requested_field_is_read():
    repo = FakeRepository(SimpleNamespace(
        status="verified", candidates=(candidate("2000-01-02", 0.99, "aadhaar", "a1"),),
        reason=None,
    ))
    result = VerifiedDataService(repo).get_requested_field(user_id="u1", requested_field="date_of_birth")
    assert result.status == "verified"
    assert result.value == "2000-01-02"
    assert result.source_type == "aadhaar"
    assert repo.calls == [("u1", "date_of_birth", 0.80)]


def test_profile_or_wildcard_access_is_rejected():
    repo = FakeRepository(None)
    service = VerifiedDataService(repo)
    with pytest.raises(ValueError): service.get_requested_fields(user_id="u1", requested_fields=["*"])
    with pytest.raises(ValueError): service.get_requested_fields(user_id="u1", requested_fields=["profile"])
    with pytest.raises(ValueError): service.get_requested_fields(user_id="u1", requested_fields=[])
    assert repo.calls == []


def test_highest_confidence_wins_when_verified_values_agree():
    repo = FakeRepository(SimpleNamespace(
        status="verified",
        candidates=(candidate("2000-01-02", 0.91, "profile", "p1"),
                    candidate("2000-01-02", 0.99, "aadhaar", "a1")),
        reason=None,
    ))
    result = VerifiedDataService(repo).get_requested_field(user_id="u1", requested_field="date_of_birth")
    assert result.confidence == 0.99
    assert result.source_type == "aadhaar"


def test_source_priority_breaks_equal_confidence_tie():
    repo = FakeRepository(SimpleNamespace(
        status="verified",
        candidates=(candidate("2000-01-02", 0.99, "profile", "p1"),
                    candidate("2000-01-02", 0.99, "aadhaar", "a1")),
        reason=None,
    ))
    result = VerifiedDataService(repo).get_requested_field(user_id="u1", requested_field="date_of_birth")
    assert result.source_type == "aadhaar"


def test_conflict_is_fail_closed_even_if_one_source_has_higher_confidence():
    repo = FakeRepository(SimpleNamespace(
        status="conflict", candidates=(),
        reason="multiple verified sources disagree; human confirmation required",
    ))
    result = VerifiedDataService(repo).get_requested_field(user_id="u1", requested_field="date_of_birth")
    assert result.status == "conflict"
    assert result.value is None


def test_high_confidence_self_heal_is_marked_for_gateway():
    controls = [{
        "type": "text", "id": "changed-123", "name": "field-9",
        "ariaLabel": "Date of Birth", "label": "Date of Birth",
        "nearbyText": "Enter date of birth",
    }]
    mapping = map_controls(controls)[0]
    assert mapping["field"] == "date_of_birth"
    assert mapping["self_healed"] is True
    assert mapping["confidence"] >= 0.86
    assert is_high_confidence_self_heal(mapping) is True


def test_gateway_requests_exactly_one_field():
    result = SimpleNamespace(status="verified", field="date_of_birth", value="2000-01-01",
                             confidence=0.99, source_type="aadhaar", source_id="doc-1",
                             provenance_id="prov-1", reason=None)
    class FakeGateway:
        def __init__(self, result): self.result, self.calls = result, []
        def get_requested_field(self, **kwargs): self.calls.append(kwargs); return self.result
    gateway = FakeGateway(result)
    resolved = _verified_gateway_value(gateway, "user-a", "date_of_birth")
    assert resolved["status"] == "verified"
    assert gateway.calls == [{"user_id": "user-a", "requested_field": "date_of_birth"}]


def test_conflict_and_not_found_pause_without_value():
    class FakeGateway:
        def __init__(self, result): self.result = result
        def get_requested_field(self, **kwargs): return self.result
    for result in (
        SimpleNamespace(status="conflict", field="date_of_birth", value=None, reason="sources disagree"),
        SimpleNamespace(status="not_found", field="date_of_birth", value=None, reason="no verified value"),
    ):
        resolved = _verified_gateway_value(FakeGateway(result), "user-a", "date_of_birth")
        assert resolved["status"] == "paused"
        assert "value" not in resolved


def test_browser_use_cannot_request_wildcard_or_profile_dump():
    with pytest.raises(BrowserUseSafetyError): normalize_agent_field_request("*")
    with pytest.raises(BrowserUseSafetyError): normalize_agent_field_request("profile")
    with pytest.raises(BrowserUseSafetyError): normalize_agent_field_request("all")
