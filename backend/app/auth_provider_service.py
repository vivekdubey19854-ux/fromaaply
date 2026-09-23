from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping
from uuid import uuid4

import httpx
import jwt
from sqlalchemy import text
from sqlalchemy.orm import Session

from .auth import hash_password, issue_access_token, issue_refresh_token
from .config import settings
from .credential_crypto import decrypt_admin_api_key


class ProviderAuthError(RuntimeError):
    pass


class InvalidProviderCredential(ProviderAuthError):
    """The user supplied an invalid password, OTP, code or identity token."""


class ProviderUnavailable(ProviderAuthError):
    """The configured provider could not be reached or timed out."""


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    display_name: str
    priority: int
    enabled: bool
    methods: tuple[str, ...]
    config: Mapping[str, Any]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.utcnow()


def provider_configs(db: Session, method: str) -> list[ProviderConfig]:
    rows = db.execute(text("SELECT provider,display_name,priority,enabled,methods_json,credentials_encrypted,client_id,issuer,authorize_url,token_url,userinfo_url,otp_request_url,otp_verify_url FROM auth_provider_registry WHERE enabled=true ORDER BY priority,provider")).mappings().all()
    result: list[ProviderConfig] = []
    for row in rows:
        try:
            methods = tuple(str(item) for item in json.loads(row["methods_json"] or "[]"))
        except (TypeError, ValueError):
            methods = ()
        if method not in methods:
            continue
        credentials: dict[str, Any] = {}
        if row["credentials_encrypted"]:
            try:
                decrypted = decrypt_admin_api_key(row["credentials_encrypted"])
                credentials = json.loads(decrypted) if isinstance(decrypted, str) else dict(decrypted)
            except Exception:
                # A malformed secret is a configuration failure, not a user credential failure.
                credentials = {"configuration_error": True}
        for key in ("client_id", "issuer", "jwks_url", "authorize_url", "token_url", "userinfo_url", "otp_request_url", "otp_verify_url"):
            if row[key]:
                credentials[key] = row[key]
        result.append(ProviderConfig(str(row["provider"]), str(row["display_name"]), int(row["priority"]), bool(row["enabled"]), methods, credentials))
    return result


def _request_json(method: str, url: str, *, data: Mapping[str, Any] | None = None, json_body: Mapping[str, Any] | None = None, params: Mapping[str, Any] | None = None, headers: Mapping[str, str] | None = None, timeout: float = 8.0) -> Mapping[str, Any]:
    if not url:
        raise ProviderUnavailable("provider endpoint is not configured")
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.request(method, url, data=data, json=json_body, params=params, headers=headers)
            if response.status_code in {400, 401, 403, 404, 422}:
                raise InvalidProviderCredential("provider rejected the authentication credential")
            if response.status_code in {408, 425, 429} or response.status_code >= 500:
                raise ProviderUnavailable("authentication provider unavailable")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, Mapping):
                raise ProviderUnavailable("provider returned an invalid response")
            return payload
    except InvalidProviderCredential:
        raise
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
        raise ProviderUnavailable("authentication provider unavailable") from exc
    except ValueError as exc:
        raise ProviderUnavailable("provider returned invalid JSON") from exc


def _normalise_external(payload: Mapping[str, Any], provider: str) -> dict[str, Any]:
    subject = payload.get("sub") or payload.get("user_id") or payload.get("id") or payload.get("localId") or payload.get("user", {}).get("id")
    email = payload.get("email") or payload.get("user", {}).get("email")
    if not subject:
        raise InvalidProviderCredential("provider identity has no subject")
    return {"provider": provider, "subject": str(subject), "email": str(email).strip().lower() if email else None, "full_name": payload.get("name") or payload.get("full_name") or payload.get("user", {}).get("name"), "email_verified": bool(payload.get("email_verified", payload.get("emailVerified", payload.get("user", {}).get("email_confirmed_at"))))}


def exchange_oauth_code(config: ProviderConfig, code: str, redirect_uri: str, state: str | None = None) -> dict[str, Any]:
    if config.config.get("configuration_error"):
        raise ProviderUnavailable("provider credential configuration is invalid")
    token_url = str(config.config.get("token_url") or ("https://oauth2.googleapis.com/token" if config.provider == "google" else ""))
    client_id = str(config.config.get("client_id", ""))
    client_secret = str(config.config.get("client_secret", ""))
    token = _request_json("POST", token_url, data={"code": code, "client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
    if token.get("error"):
        raise InvalidProviderCredential("OAuth authorization code was rejected")
    access_token = token.get("access_token")
    id_token = token.get("id_token")
    if config.provider == "google" and id_token:
        identity = _normalise_external(_request_json("GET", "https://oauth2.googleapis.com/tokeninfo", params={"id_token": id_token}), config.provider)
    elif config.config.get("userinfo_url") and access_token:
        identity = _normalise_external(_request_json("GET", str(config.config["userinfo_url"]), headers={"Authorization": f"Bearer {access_token}"}), config.provider)
    else:
        identity = _normalise_external(token, config.provider)
    identity["access_token"] = access_token
    identity["refresh_token"] = token.get("refresh_token")
    return identity


def verify_provider_token(config: ProviderConfig, token: str) -> dict[str, Any]:
    if not token or len(token) > 20000:
        raise InvalidProviderCredential("provider token is invalid")
    if config.provider == "firebase":
        api_key = str(config.config.get("api_key", ""))
        if not api_key:
            raise ProviderUnavailable("Firebase API key is not configured")
        payload = _request_json("POST", f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={api_key}", json_body={"idToken": token})
        users = payload.get("users") or []
        if not users:
            raise InvalidProviderCredential("Firebase identity token is invalid")
        return _normalise_external(users[0], config.provider)
    if config.provider == "supabase":
        base = str(config.config.get("supabase_url") or config.config.get("url") or "").rstrip("/")
        anon = str(config.config.get("anon_key") or config.config.get("api_key") or "")
        if not base or not anon:
            raise ProviderUnavailable("Supabase URL or anon key is not configured")
        return _normalise_external(_request_json("GET", f"{base}/auth/v1/user", headers={"Authorization": f"Bearer {token}", "apikey": anon}), config.provider)
    if config.provider in {"clerk", "stytch", "descope"} and not config.config.get("userinfo_url") and config.config.get("token_url"):
        return _normalise_external(_request_json("POST", str(config.config["token_url"]), data={"token": token}, headers={"Authorization": f"Bearer {token}"}), config.provider)
    if config.config.get("userinfo_url"):
        return _normalise_external(_request_json("GET", str(config.config["userinfo_url"]), headers={"Authorization": f"Bearer {token}"}), config.provider)
    issuer = config.config.get("issuer")
    if issuer:
        jwks_url = str(config.config.get("jwks_url") or "").strip()
        if not jwks_url:
            raise ProviderUnavailable("provider JWKS URL is not configured")
        try:
            signing_key = jwt.PyJWKClient(jwks_url).get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, signing_key, algorithms=["RS256", "RS384", "RS512", "ES256"], issuer=issuer, options={"require": ["sub", "exp"]})
        except jwt.PyJWKClientError as exc:
            raise ProviderUnavailable("provider JWKS endpoint is unavailable") from exc
        except jwt.PyJWTError as exc:
            raise InvalidProviderCredential("provider identity token is invalid") from exc
        return _normalise_external(claims, config.provider)
    raise ProviderUnavailable("provider token verification is not configured")


def resolve_identity(db: Session, identity: Mapping[str, Any], *, create: bool = True) -> str:
    provider, subject = str(identity["provider"]), str(identity["subject"])
    existing = db.execute(text("SELECT user_id FROM auth_identity_mappings WHERE provider=:provider AND subject=:subject"), {"provider": provider, "subject": subject}).scalar()
    if existing:
        return str(existing)
    email = str(identity.get("email") or "").strip().lower()
    user_id = db.execute(text("SELECT user_id FROM auth_users WHERE email=:email"), {"email": email}).scalar() if email else None
    if not user_id:
        if not create:
            raise InvalidProviderCredential("external identity is not linked")
        user_id = str(uuid4())
        db.execute(text("INSERT INTO auth_users(user_id,email,password_hash,status,role) VALUES (:user_id,:email,:password,'active','user')"), {"user_id": user_id, "email": email or f"{provider}-{subject}@identity.invalid", "password": hash_password(secrets.token_urlsafe(32))})
        db.execute(text("INSERT INTO profiles(user_id,email,full_name) VALUES (:user_id,:email,:name)"), {"user_id": user_id, "email": email or None, "name": identity.get("full_name")})
    elif not bool(identity.get("email_verified")):
        raise InvalidProviderCredential("verified provider email is required to link an existing account")
    db.execute(text("INSERT INTO auth_identity_mappings(mapping_id,user_id,provider,subject) VALUES (:mapping_id,:user_id,:provider,:subject)"), {"mapping_id": str(uuid4()), "user_id": str(user_id), "provider": provider, "subject": subject})
    db.commit()
    return str(user_id)


def issue_session(db: Session, user_id: str, *, user_agent: str | None = None, ip_address: str | None = None) -> dict[str, Any]:
    access = issue_access_token(user_id)
    refresh = issue_refresh_token(user_id)
    claims = jwt.decode(refresh, settings.jwt_secret, algorithms=[settings.jwt_algorithm], options={"verify_exp": False})
    expires = _now() + timedelta(days=30)
    db.execute(text("INSERT INTO auth_sessions(session_id,user_id,refresh_jti_hash,expires_at,user_agent,ip_address) VALUES (:session,:user,:jti,:expires,:ua,:ip)"), {"session": str(uuid4()), "user": user_id, "jti": _sha(str(claims["jti"])), "expires": expires, "ua": user_agent, "ip": ip_address})
    db.commit()
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer", "expires_in": 900}


def rotate_session(db: Session, refresh_token: str, *, user_agent: str | None = None, ip_address: str | None = None) -> tuple[str, dict[str, Any]]:
    try:
        claims = jwt.decode(refresh_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm], options={"require": ["sub", "exp", "jti"]})
    except jwt.PyJWTError as exc:
        raise InvalidProviderCredential("invalid refresh token") from exc
    if claims.get("role") != "refresh":
        raise InvalidProviderCredential("invalid refresh token")
    row = db.execute(text("SELECT session_id,user_id,expires_at,revoked_at FROM auth_sessions WHERE refresh_jti_hash=:jti"), {"jti": _sha(str(claims["jti"]))}).mappings().first()
    if not row:
        user_id = str(claims.get("sub", ""))
        if db.execute(text("SELECT 1 FROM revoked_tokens WHERE jti=:jti"), {"jti": str(claims["jti"])}).scalar():
            raise InvalidProviderCredential("refresh token has been revoked")
        db.execute(text("INSERT INTO revoked_tokens(jti,user_id,expires_at) VALUES (:jti,:user,:expires) ON CONFLICT(jti) DO NOTHING"), {"jti": str(claims["jti"]), "user": user_id, "expires": datetime.fromtimestamp(claims["exp"])})
        db.commit()
        return user_id, issue_session(db, user_id, user_agent=user_agent, ip_address=ip_address)
    if row["revoked_at"] or row["expires_at"] <= _now():
        raise InvalidProviderCredential("refresh session is revoked or expired")
    db.execute(text("INSERT INTO revoked_tokens(jti,user_id,expires_at) VALUES (:jti,:user,:expires) ON CONFLICT(jti) DO NOTHING"), {"jti": str(claims["jti"]), "user": str(row["user_id"]), "expires": datetime.fromtimestamp(claims["exp"])})
    db.execute(text("UPDATE auth_sessions SET revoked_at=:now,last_seen_at=:now WHERE session_id=:session"), {"now": _now(), "session": row["session_id"]})
    result = issue_session(db, str(row["user_id"]), user_agent=user_agent, ip_address=ip_address)
    return str(row["user_id"]), result


def revoke_session(db: Session, refresh_token: str | None, user_id: str) -> None:
    if not refresh_token:
        return
    try:
        claims = jwt.decode(refresh_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm], options={"verify_exp": False})
        if str(claims.get("sub")) != user_id:
            return
        if claims.get("jti"):
            db.execute(text("INSERT INTO revoked_tokens(jti,user_id,expires_at) VALUES (:jti,:user,:expires) ON CONFLICT(jti) DO NOTHING"), {"jti": str(claims["jti"]), "user": user_id, "expires": datetime.fromtimestamp(int(claims.get("exp", int(time.time()) + 1)))})
        db.execute(text("UPDATE auth_sessions SET revoked_at=:now WHERE user_id=:user AND refresh_jti_hash=:jti"), {"now": _now(), "user": user_id, "jti": _sha(str(claims.get("jti", "")))})
        db.commit()
    except jwt.PyJWTError:
        return


def request_otp(db: Session, phone: str, *, user_id: str | None = None) -> dict[str, Any]:
    phone = phone.strip()
    if not phone.startswith("+") or not phone[1:].isdigit() or len(phone) < 8 or len(phone) > 20:
        raise InvalidProviderCredential("phone must be in international E.164 format")
    failures: list[Exception] = []
    for config in provider_configs(db, "phone_otp"):
        try:
            url = str(config.config.get("otp_request_url", ""))
            payload = _request_json("POST", url, data={"phone": phone}, headers={"Authorization": f"Bearer {config.config.get('api_key', '')}"})
            challenge_id = str(uuid4())
            reference = str(payload.get("challenge_id") or payload.get("sessionInfo") or payload.get("sid") or payload.get("reference") or challenge_id)
            db.execute(text("INSERT INTO auth_otp_challenges(challenge_id,provider,phone_hash,provider_reference,user_id,expires_at) VALUES (:id,:provider,:phone,:reference,:user,:expires)"), {"id": challenge_id, "provider": config.provider, "phone": _sha(phone), "reference": reference, "user": user_id, "expires": _now() + timedelta(minutes=10)})
            db.commit()
            return {"challenge_id": challenge_id, "provider": config.provider, "expires_in": 600}
        except InvalidProviderCredential:
            raise
        except ProviderUnavailable as exc:
            failures.append(exc)
    raise ProviderUnavailable("all enabled phone OTP providers are unavailable") from (failures[-1] if failures else None)


def verify_otp(db: Session, challenge_id: str, code: str) -> tuple[str, dict[str, Any]]:
    row = db.execute(text("SELECT challenge_id,provider,phone_hash,provider_reference,user_id,expires_at,attempts FROM auth_otp_challenges WHERE challenge_id=:id"), {"id": challenge_id}).mappings().first()
    if not row or row["expires_at"] <= _now() or int(row["attempts"]) >= 5:
        raise InvalidProviderCredential("OTP challenge is invalid or expired")
    db.execute(text("UPDATE auth_otp_challenges SET attempts=attempts+1 WHERE challenge_id=:id"), {"id": challenge_id})
    config = next((item for item in provider_configs(db, "phone_otp") if item.provider == row["provider"]), None)
    if not config:
        raise ProviderUnavailable("OTP provider is no longer enabled")
    payload = _request_json("POST", str(config.config.get("otp_verify_url", "")), data={"challenge_id": row["provider_reference"], "code": code}, headers={"Authorization": f"Bearer {config.config.get('api_key', '')}"})
    identity = _normalise_external(payload, config.provider)
    identity.setdefault("phone", row["phone_hash"])
    user_id = row["user_id"] or resolve_identity(db, identity)
    db.execute(text("UPDATE auth_otp_challenges SET verified_at=:now,user_id=:user WHERE challenge_id=:id"), {"now": _now(), "user": user_id, "id": challenge_id})
    db.commit()
    return user_id, issue_session(db, user_id)
