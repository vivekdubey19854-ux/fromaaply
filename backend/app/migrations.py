from app.database import Base, engine
from app import db_models  # noqa: F401


def create_schema() -> None:
    """Development bootstrap. Production deployment should use Alembic migrations."""
    Base.metadata.create_all(bind=engine)
