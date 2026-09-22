from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import (
    AddressCreate, AddressResponse, DocumentMetadata, EducationCreate,
    EducationResponse, ExtractionResponse, ProfileResponse, ProfileUpdate,
)
from app.auth import require_user_id
from app.config import settings
from app.database import get_db
from app.db_models import AddressRecord, AuditLogRecord, DocumentRecord, EducationRecord, ProfileRecord
from app.document_intelligence import extract_document
from app.security import sha256_bytes, validate_upload
from app.storage import PrivateStorage
from app.storage_service import StorageServiceAdapter, StorageUploadError

router = APIRouter(prefix="/v1", tags=["profile-vault"])
storage = PrivateStorage(settings.storage_root)


def _object_key(user_id: str, key: str) -> str:
    return f"users/{user_id}/{key}" if settings.environment == "production" else key


def _save_object(db: Session, user_id: str, key: str, data: bytes, content_type: str) -> str:
    if settings.environment == "production":
        return StorageServiceAdapter(db).upload_bytes(object_key=_object_key(user_id, key), data=data, content_type=content_type)
    storage.save(user_id, key, data)
    return key


def _read_object(db: Session, user_id: str, key: str) -> bytes:
    return StorageServiceAdapter(db).download_bytes(object_key=key) if settings.environment == "production" else storage.read(user_id, key)


def _delete_object(db: Session, user_id: str, key: str) -> None:
    if settings.environment == "production":
        StorageServiceAdapter(db).delete_object(object_key=key)
    else:
        storage.delete(user_id, key)


def ensure_profile(db: Session, user_id: str) -> ProfileRecord:
    profile = db.get(ProfileRecord, user_id)
    if profile is None:
        profile = ProfileRecord(user_id=user_id)
        db.add(profile)
        db.flush()
    return profile


def audit(db: Session, user_id: str, action: str, resource_type: str, resource_id: str | None = None) -> None:
    db.add(AuditLogRecord(user_id=user_id, action=action, resource_type=resource_type, resource_id=resource_id))


def safe_filename(filename: str) -> str:
    name = Path(filename).name.replace('"', "'").strip()
    return name[:255] or "document"


def extraction_key(document: DocumentRecord) -> str:
    return f"{document.storage_key}.extraction.json"


@router.get("/profile", response_model=ProfileResponse)
def get_profile(user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    return ensure_profile(db, user_id)


@router.put("/profile", response_model=ProfileResponse)
def update_profile(payload: ProfileUpdate, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    profile = ensure_profile(db, user_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    audit(db, user_id, "profile.updated", "profile", user_id)
    db.commit(); db.refresh(profile)
    return profile


@router.post("/addresses", response_model=AddressResponse, status_code=201)
def add_address(payload: AddressCreate, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    ensure_profile(db, user_id)
    record = AddressRecord(user_id=user_id, **payload.model_dump())
    db.add(record); db.flush(); audit(db, user_id, "address.created", "address", record.id); db.commit(); db.refresh(record)
    return record


@router.get("/addresses", response_model=list[AddressResponse])
def list_addresses(user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    return list(db.scalars(select(AddressRecord).where(AddressRecord.user_id == user_id)).all())


@router.delete("/addresses/{address_id}")
def delete_address(address_id: str, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    row = db.scalar(select(AddressRecord).where(AddressRecord.id == address_id, AddressRecord.user_id == user_id))
    if row is None: raise HTTPException(status_code=404, detail="address not found")
    db.delete(row); audit(db, user_id, "address.deleted", "address", address_id); db.commit()
    return {"deleted": True}


@router.post("/education", response_model=EducationResponse, status_code=201)
def add_education(payload: EducationCreate, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    ensure_profile(db, user_id)
    record = EducationRecord(user_id=user_id, **payload.model_dump())
    db.add(record); db.flush(); audit(db, user_id, "education.created", "education", record.id); db.commit(); db.refresh(record)
    return record


@router.get("/education", response_model=list[EducationResponse])
def list_education(user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    return list(db.scalars(select(EducationRecord).where(EducationRecord.user_id == user_id)).all())


@router.post("/documents", response_model=DocumentMetadata, status_code=201)
async def upload_document(file: UploadFile = File(...), user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    content_type = file.content_type or "application/octet-stream"
    chunks: list[bytes] = []; total = 0; max_size = settings.max_upload_size_bytes
    while True:
        chunk = await file.read(min(1024 * 1024, max_size + 1 - total))
        if not chunk: break
        chunks.append(chunk); total += len(chunk)
        if total > max_size: break
    data = b"".join(chunks)
    try: validate_upload(file.filename or "", content_type, total, max_size)
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc
    digest = sha256_bytes(data); storage_key = _object_key(user_id, f"{secrets.token_hex(16)}-{digest}.bin")
    try:
        if settings.environment == "production":
            StorageServiceAdapter(db).upload_bytes(object_key=storage_key, data=data, content_type=content_type, checksum_sha256=digest)
        else:
            storage.save(user_id, storage_key, data)
    except StorageUploadError as exc:
        raise HTTPException(status_code=503, detail="document storage is temporarily unavailable") from exc
    record = DocumentRecord(user_id=user_id, original_filename=safe_filename(file.filename or "document"), storage_key=storage_key, content_type=content_type, size_bytes=total, sha256=digest, status="uploaded")
    try:
        db.add(record); db.flush(); audit(db, user_id, "document.uploaded", "document", record.id); db.commit(); db.refresh(record)
    except Exception:
        db.rollback()
        try: _delete_object(db, user_id, storage_key)
        except Exception: pass
        raise
    return record


@router.get("/documents", response_model=list[DocumentMetadata])
def list_documents(user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    rows = db.scalars(select(DocumentRecord).where(DocumentRecord.user_id == user_id, DocumentRecord.status != "deleted").order_by(DocumentRecord.created_at.desc())).all()
    return list(rows)


@router.get("/documents/{document_id}", response_model=DocumentMetadata)
def get_document(document_id: str, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    row = db.scalar(select(DocumentRecord).where(DocumentRecord.id == document_id, DocumentRecord.user_id == user_id, DocumentRecord.status != "deleted"))
    if row is None: raise HTTPException(status_code=404, detail="document not found")
    return row


@router.post("/documents/{document_id}/extract", response_model=ExtractionResponse)
def extract_document_endpoint(document_id: str, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    row = db.scalar(select(DocumentRecord).where(DocumentRecord.id == document_id, DocumentRecord.user_id == user_id, DocumentRecord.status != "deleted"))
    if row is None: raise HTTPException(status_code=404, detail="document not found")
    try:
        data = _read_object(db, user_id, row.storage_key)
        result = extract_document(data, row.content_type, row.original_filename)
        extraction_data = __import__("json").dumps(result, separators=(",", ":")).encode()
        if settings.environment == "production":
            StorageServiceAdapter(db).upload_bytes(object_key=extraction_key(row), data=extraction_data, content_type="application/json")
        else:
            storage.save_json(user_id, extraction_key(row), result)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit(db, user_id, "document.extracted", "document", document_id); db.commit()
    return result


@router.get("/documents/{document_id}/extraction", response_model=ExtractionResponse)
def get_extraction(document_id: str, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    row = db.scalar(select(DocumentRecord).where(DocumentRecord.id == document_id, DocumentRecord.user_id == user_id, DocumentRecord.status != "deleted"))
    if row is None: raise HTTPException(status_code=404, detail="document not found")
    try:
        if settings.environment == "production":
            return __import__("json").loads(_read_object(db, user_id, extraction_key(row)))
        return storage.read_json(user_id, extraction_key(row))
    except (FileNotFoundError, StorageUploadError, ValueError): raise HTTPException(status_code=404, detail="document has not been extracted")


@router.get("/documents/{document_id}/download")
def download_document(document_id: str, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    row = db.scalar(select(DocumentRecord).where(DocumentRecord.id == document_id, DocumentRecord.user_id == user_id, DocumentRecord.status != "deleted"))
    if row is None: raise HTTPException(status_code=404, detail="document not found")
    audit(db, user_id, "document.downloaded", "document", document_id); db.commit()
    if settings.environment == "production":
        try: return RedirectResponse(StorageServiceAdapter(db).presigned_download_url(object_key=row.storage_key), status_code=307)
        except StorageUploadError as exc: raise HTTPException(status_code=503, detail="document storage is temporarily unavailable") from exc
    try: data = storage.read(user_id, row.storage_key)
    except FileNotFoundError as exc: raise HTTPException(status_code=404, detail="document content not found") from exc
    return Response(content=data, media_type=row.content_type, headers={"Content-Disposition": f'attachment; filename="{safe_filename(row.original_filename)}"'})


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    row = db.scalar(select(DocumentRecord).where(DocumentRecord.id == document_id, DocumentRecord.user_id == user_id))
    if row is None: raise HTTPException(status_code=404, detail="document not found")
    _delete_object(db, user_id, row.storage_key)
    try: _delete_object(db, user_id, extraction_key(row))
    except ValueError: pass
    row.status = "deleted"; audit(db, user_id, "document.deleted", "document", document_id); db.commit()
    return {"deleted": True}
