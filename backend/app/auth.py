import base64
import hashlib
import hmac
import secrets
from datetime import timedelta
from functools import lru_cache
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from .accounts import User
from .config import settings, signing_key
from .db import get_db, utcnow

bearer = HTTPBearer(auto_error=False)
key = lru_cache(maxsize=1)(signing_key)


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return "$".join(
        [
            "pbkdf2_sha256",
            "600000",
            base64.b64encode(salt).decode(),
            base64.b64encode(digest).decode(),
        ]
    )


def password_matches(password, encoded):
    scheme, iterations, salt, digest = encoded.split("$")
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), base64.b64decode(salt), int(iterations)
    )
    return scheme == "pbkdf2_sha256" and hmac.compare_digest(
        candidate, base64.b64decode(digest)
    )


@lru_cache(maxsize=1)
def dummy_hash():
    return hash_password(secrets.token_hex(32))


def token(user):
    now = utcnow()
    return jwt.encode(
        {
            "sub": user.id,
            "iss": "sourcera",
            "iat": now,
            "exp": now + timedelta(hours=24 * 30 if user.is_guest else settings.token_hours),
        },
        key(),
        algorithm="HS256",
    )


def user_for_token(db, token):
    try:
        payload = jwt.decode(
            token or "",
            key(),
            algorithms=["HS256"],
            issuer="sourcera",
            options={"require": ["sub", "iat", "exp"]},
        )
        return db.get(User, payload["sub"])
    except jwt.InvalidTokenError:
        return None


def current_user(token=Depends(bearer), db=Depends(get_db)):
    user = user_for_token(db, token.credentials if token else None)
    if not user:
        raise HTTPException(
            401, "Please sign in", headers={"WWW-Authenticate": "Bearer"}
        )
    return user


def admin_user(user=Depends(current_user)):
    if not user.is_admin:
        raise HTTPException(403, "Operator access required")
    return user
