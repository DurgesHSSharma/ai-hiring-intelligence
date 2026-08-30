"""Password hashing and JWT encode/decode. Pure functions — no DB access,
no FastAPI imports. Callers (dependencies.py, services/auth_service.py)
decide what to do with a JWTError; this module only raises what
python-jose itself raises.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import jwt
from passlib.context import CryptContext

from app.config import settings

ALGORITHM = "HS256"

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _pwd_context.verify(plain_password, password_hash)


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    minutes = expires_minutes if expires_minutes is not None else settings.ACCESS_TOKEN_EXPIRE_MINUTES
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jose.ExpiredSignatureError on an expired token, jose.JWTError
    (its base class, which also covers ExpiredSignatureError) on anything
    else invalid — malformed, wrong signature, wrong algorithm.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
