from __future__ import annotations
import hashlib
from pathlib import Path
from app.config import settings

ALLOWED_CONTENT_TYPES={"application/pdf":{".pdf"},"image/jpeg":{".jpg",".jpeg"},"image/png":{".png"},"image/webp":{".webp"}}

def sha256_bytes(data:bytes)->str:return hashlib.sha256(data).hexdigest()

def validate_upload(filename:str,content_type:str,size_bytes:int,max_size:int)->None:
    if not filename or Path(filename).name!=filename: raise ValueError("invalid filename")
    if content_type not in ALLOWED_CONTENT_TYPES: raise ValueError("unsupported document type")
    if Path(filename).suffix.lower() not in ALLOWED_CONTENT_TYPES[content_type]: raise ValueError("file extension does not match content type")
    if size_bytes<=0 or size_bytes>max_size: raise ValueError("document size is outside the allowed range")

def validate_production_security()->None:
    if settings.environment=="production":
        if settings.jwt_secret=="change-me-in-production" or len(settings.jwt_secret)<32: raise RuntimeError("FORMWISE_JWT_SECRET must be a strong secret of at least 32 characters")
        if settings.allow_legacy_user_header: raise RuntimeError("legacy X-User-ID authentication must be disabled in production")
