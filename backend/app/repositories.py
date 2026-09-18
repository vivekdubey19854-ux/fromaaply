from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .entities import AddressEntity, DocumentEntity, EducationEntity, ProfileEntity


class ProfileRepository:
    def get(self, db: Session, user_id: str) -> ProfileEntity | None:
        return db.get(ProfileEntity, user_id)

    def save(self, db: Session, user_id: str, **values) -> ProfileEntity:
        obj = self.get(db, user_id) or ProfileEntity(user_id=user_id)
        for key, value in values.items():
            setattr(obj, key, value)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj


class AddressRepository:
    def list(self, db: Session, user_id: str) -> list[AddressEntity]:
        return list(db.scalars(select(AddressEntity).where(AddressEntity.user_id == user_id)))

    def get_owned(self, db: Session, user_id: str, address_id: str) -> AddressEntity | None:
        return db.scalar(select(AddressEntity).where(AddressEntity.id == address_id, AddressEntity.user_id == user_id))


class EducationRepository:
    def list(self, db: Session, user_id: str) -> list[EducationEntity]:
        return list(db.scalars(select(EducationEntity).where(EducationEntity.user_id == user_id)))


class DocumentRepository:
    def list(self, db: Session, user_id: str) -> list[DocumentEntity]:
        return list(db.scalars(select(DocumentEntity).where(DocumentEntity.user_id == user_id).order_by(DocumentEntity.created_at.desc())))

    def get_owned(self, db: Session, user_id: str, document_id: str) -> DocumentEntity | None:
        return db.scalar(select(DocumentEntity).where(DocumentEntity.id == document_id, DocumentEntity.user_id == user_id))
