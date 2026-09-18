from sqlalchemy import text

from app.verified_data_repository import VerifiedDataRepository


def _schema(db):
    db.execute(text("""
        CREATE TABLE field_provenance (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_value TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT,
            source_locator TEXT,
            confidence NUMERIC NOT NULL,
            verification_status TEXT NOT NULL,
            verified_at TEXT,
            revoked_at TEXT,
            created_at TEXT NOT NULL
        )
    """))
    db.execute(text("""
        CREATE TABLE verification_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            new_status TEXT NOT NULL,
            confidence NUMERIC NOT NULL,
            verifier_type TEXT NOT NULL,
            verifier_id TEXT,
            reason TEXT,
            evidence TEXT,
            created_at TEXT NOT NULL
        )
    """))
    db.commit()


def _insert(db, **values):
    db.execute(
        text("""
            INSERT INTO field_provenance
            (id,user_id,field_name,field_value,source_type,source_id,source_locator,
             confidence,verification_status,verified_at,revoked_at,created_at)
            VALUES (:id,:user_id,:field_name,:field_value,:source_type,:source_id,
                    :source_locator,:confidence,:verification_status,:verified_at,
                    :revoked_at,:created_at)
        """),
        values,
    )
    db.commit()


def test_verified_field_is_user_scoped_and_provenance_backed(db_session):
    _schema(db_session)
    _insert(
        db_session,
        id="1", user_id="u1", field_name="date_of_birth", field_value="2000-01-02",
        source_type="aadhaar", source_id="doc-1", source_locator="page:1",
        confidence=0.97, verification_status="verified", verified_at="2026-01-01",
        revoked_at=None, created_at="2026-01-01",
    )
    _insert(
        db_session,
        id="2", user_id="u2", field_name="date_of_birth", field_value="1999-01-02",
        source_type="pan", source_id="doc-2", source_locator="page:1",
        confidence=0.99, verification_status="verified", verified_at="2026-01-01",
        revoked_at=None, created_at="2026-01-01",
    )

    repo = VerifiedDataRepository(db_session)
    result = repo.get_verified_field("u1", "date_of_birth")

    assert result.status == "verified"
    assert result.value == "2000-01-02"
    assert result.candidates[0].source_type == "aadhaar"


def test_conflicting_verified_sources_fail_closed(db_session):
    _schema(db_session)
    common = dict(
        user_id="u1", field_name="phone", source_locator="page:1",
        confidence=0.95, verification_status="verified", verified_at="2026-01-01",
        revoked_at=None, created_at="2026-01-01",
    )
    _insert(db_session, id="1", field_value="9999999999", source_type="aadhaar", source_id="a", **common)
    _insert(db_session, id="2", field_value="8888888888", source_type="pan", source_id="b", **common)

    result = VerifiedDataRepository(db_session).get_verified_field("u1", "phone")

    assert result.status == "conflict"
    assert result.value is None
    assert len(result.candidates) == 2


def test_unverified_values_are_never_returned(db_session):
    _schema(db_session)
    _insert(
        db_session,
        id="1", user_id="u1", field_name="pan_number", field_value="ABCDE1234F",
        source_type="pan", source_id="doc-1", source_locator="page:1",
        confidence=0.99, verification_status="review_required", verified_at=None,
        revoked_at=None, created_at="2026-01-01",
    )

    result = VerifiedDataRepository(db_session).get_verified_field("u1", "pan_number")

    assert result.status == "not_found"
