"""Registration, authentication, and user lookup. Raises domain exceptions
from core/exceptions.py; never HTTPException (Rules.md 5.2 / Architecture.md 2).
"""
from sqlalchemy.orm import Session

from app.core.enums import UserRole
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import UserCreate, UserLogin


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).one_or_none()


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def register(db: Session, payload: UserCreate) -> User:
    if get_user_by_email(db, payload.email) is not None:
        raise ConflictError(
            "An account with this email already exists.",
            code="DUPLICATE_EMAIL",
            details={"email": payload.email},
        )
    # Role is never client-supplied (Rules.md 1.6/1.7 — role changes are out of scope
    # for v1 entirely). Every self-registration is a recruiter; promoting a user to
    # another role has no endpoint and happens only by direct DB access.
    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole.RECRUITER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, payload: UserLogin) -> User:
    user = get_user_by_email(db, payload.email)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AuthenticationError("Incorrect email or password.", code="INVALID_CREDENTIALS")
    return user


def login(db: Session, payload: UserLogin) -> tuple[str, User]:
    user = authenticate(db, payload)
    access_token = create_access_token(subject=str(user.id))
    return access_token, user
