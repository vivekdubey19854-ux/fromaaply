import pytest
from app.config import settings
from app.security import validate_production_security

def test_production_requires_strong_secret(monkeypatch):
    monkeypatch.setattr(settings,'environment','production'); monkeypatch.setattr(settings,'jwt_secret','change-me-in-production'); monkeypatch.setattr(settings,'allow_legacy_user_header',False)
    with pytest.raises(RuntimeError): validate_production_security()

def test_upload_security_boundaries():
    from app.security import validate_upload
    with pytest.raises(ValueError): validate_upload('../secret.pdf','application/pdf',10,100)
    with pytest.raises(ValueError): validate_upload('doc.png','application/pdf',10,100)
