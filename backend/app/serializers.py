from __future__ import annotations

from datetime import date, datetime
from typing import Any


def serialize_model(obj: Any) -> dict[str, Any]:
    """Serialize only mapped columns; never leak SQLAlchemy internal state."""
    result: dict[str, Any] = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        result[column.name] = value
    return result
