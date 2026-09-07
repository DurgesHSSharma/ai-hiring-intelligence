"""FastAPI dependency-injection glue: current-user resolution and shared
query-parameter dependencies. Sits between api/ and services/ — api/ route
signatures use the CurrentUser alias so they never need to import
app.models directly (Rules.md 4.2: api/ must not import models).
"""
from datetime import date
from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.enums import UserRole
from app.core.exceptions import AuthenticationError, AuthorizationError, RateLimitError, ValidationError
from app.core.rate_limit import FixedWindowRateLimiter
from app.core.security import decode_access_token
from app.database import get_db
from app.models.user import User
from app.services import auth_service

MIN_COMPARE_CANDIDATES = 2
MAX_COMPARE_CANDIDATES = 4

# auto_error=False is deliberate: with the default True, a request with no
# Authorization header never reaches this function at all — FastAPI raises
# its own HTTPException(401) first, which the existing Starlette handler
# maps to the HTTP_ERROR fallback code, not TOKEN_MISSING. auto_error=False
# makes the scheme return None instead, so every failure path below raises
# the correct AppError itself: TOKEN_MISSING, TOKEN_INVALID, TOKEN_EXPIRED,
# and INVALID_CREDENTIALS are deliberately four different codes (not all
# collapsed into one) so the frontend can tell "never logged in" apart from
# "session expired" and react differently to each.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login", auto_error=False
)


def get_current_user(
    token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    if token is None:
        raise AuthenticationError("Authentication required.", code="TOKEN_MISSING")

    try:
        payload = decode_access_token(token)
    except ExpiredSignatureError:
        raise AuthenticationError("Token has expired.", code="TOKEN_EXPIRED")
    except JWTError:
        raise AuthenticationError("Invalid authentication token.", code="TOKEN_INVALID")

    subject = payload.get("sub")
    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise AuthenticationError("Invalid authentication token.", code="TOKEN_INVALID")

    user = auth_service.get_user_by_id(db, user_id)
    if user is None:
        raise AuthenticationError("User not found.", code="INVALID_CREDENTIALS")

    return user


# So api/ route signatures never need `from app.models.user import User`.
CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(current_user: CurrentUser) -> User:
    """Layered on top of get_current_user, not standalone: an unauthenticated
    request fails at the auth dependency first (401 TOKEN_MISSING/etc.), so this
    403 only ever fires for an authenticated caller who isn't an admin
    (PRD F1.5 — v1 role enforcement is exactly this one check, nothing else).
    """
    if current_user.role != UserRole.ADMIN:
        raise AuthorizationError(
            "Only administrators can perform this action.", code="ADMIN_REQUIRED"
        )
    return current_user


AdminUser = Annotated[User, Depends(require_admin)]

# Module-level singleton, the same precedent as oauth2_scheme above: one
# counter set shared by every request this process handles, for the life
# of the process. WINDOW_SECONDS is fixed at one hour to match the
# setting's name; only the request count is configurable.
INTERVIEW_RATE_LIMIT_WINDOW_SECONDS = 3600
interview_question_rate_limiter = FixedWindowRateLimiter(
    max_requests=settings.INTERVIEW_RATE_LIMIT_PER_HOUR,
    window_seconds=INTERVIEW_RATE_LIMIT_WINDOW_SECONDS,
)


def enforce_interview_generation_rate_limit(current_user: CurrentUser) -> None:
    """Depends on CurrentUser, not a bare token, so an unauthenticated
    caller is rejected by get_current_user (401 TOKEN_MISSING/etc.)
    before this ever runs — the rate limit only ever gates an
    already-authenticated user, keyed by their id so one user's usage
    never affects another's (PRD/Phases.md Phase 15).
    """
    allowed, retry_after_seconds = interview_question_rate_limiter.check(str(current_user.id))
    if not allowed:
        raise RateLimitError(
            "Too many interview-question generation requests. Please try again later.",
            details={"retry_after_seconds": retry_after_seconds},
        )


def pagination_params(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, int]:
    return {"page": page, "page_size": page_size}


def analytics_filters(
    job_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> dict[str, object]:
    """Shared `?job_id=&from=&to=` filter set for every `/analytics/*`
    endpoint (Architecture.md 6.2). Validated once, here, rather than
    separately in each of the four analytics_service functions.
    """
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValidationError(
            "'from' must not be after 'to'.",
            details={"from": str(date_from), "to": str(date_to)},
        )
    return {"job_id": job_id, "date_from": date_from, "date_to": date_to}


def compare_candidate_ids(
    candidate_ids: str = Query(
        ..., description="Comma-separated candidate ids, 2-4, e.g. '12,17,33'."
    ),
) -> list[int]:
    """`GET /jobs/{id}/compare?candidate_ids=1,2,3` (Architecture.md 6.2) —
    a single comma-joined query value, not FastAPI's repeatable-param
    convention (contrast `/candidates?skills=`), so it needs its own parse
    step rather than a plain `list[int]` type annotation. Malformed values
    and an out-of-[2,4]-bounds count are both reported as
    INVALID_CANDIDATE_COUNT (Rules.md 5.3): either way, what was requested
    isn't a usable candidate set, and there's no meaningful difference to a
    caller between "typed something that isn't a number" and "asked to
    compare 1 candidate."
    """
    raw_parts = [part.strip() for part in candidate_ids.split(",") if part.strip()]
    try:
        parsed = [int(part) for part in raw_parts]
    except ValueError:
        raise ValidationError(
            "candidate_ids must be a comma-separated list of integers.",
            code="INVALID_CANDIDATE_COUNT",
            details={"candidate_ids": candidate_ids},
        )

    if not (MIN_COMPARE_CANDIDATES <= len(parsed) <= MAX_COMPARE_CANDIDATES):
        raise ValidationError(
            f"candidate_ids must list between {MIN_COMPARE_CANDIDATES} and "
            f"{MAX_COMPARE_CANDIDATES} candidates, got {len(parsed)}.",
            code="INVALID_CANDIDATE_COUNT",
            details={"provided_count": len(parsed), "min": MIN_COMPARE_CANDIDATES, "max": MAX_COMPARE_CANDIDATES},
        )
    return parsed
