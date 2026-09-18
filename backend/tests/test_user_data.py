from datetime import date

from app.db_models import ProfileRecord
from app.user_data import get_user_data


def test_get_user_data_returns_only_requested_profile_field(db_session, tmp_path):
    user_id = "user-1"
    db_session.add(ProfileRecord(
        user_id=user_id,
        full_name="Test User",
        date_of_birth=date(2000, 1, 2),
        gender="Male",
        email="test@example.com",
        phone="9999999999",
    ))
    db_session.commit()
    from app.storage import PrivateStorage
    result = get_user_data(db_session, PrivateStorage(str(tmp_path)), user_id, "email")
    assert result["value"] == "test@example.com"
    assert result["source_type"] == "profile"


def test_get_user_data_returns_none_when_missing(db_session, tmp_path):
    user_id = "user-2"
    db_session.add(ProfileRecord(user_id=user_id, full_name="Only Name"))
    db_session.commit()
    from app.storage import PrivateStorage
    assert get_user_data(db_session, PrivateStorage(str(tmp_path)), user_id, "phone") is None
