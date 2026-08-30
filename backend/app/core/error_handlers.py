"""Maps every exception type that can reach the ASGI boundary to the single
error envelope from Architecture.md 6.1, so one Axios interceptor on the
frontend can handle every failure the same way.
"""
import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

_STARLETTE_CODE_BY_STATUS = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content=_envelope(exc.code, exc.message, exc.details),
    )


async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = [
        {"field": ".".join(str(p) for p in err["loc"] if p != "body"), "message": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_envelope(
            "REQUEST_VALIDATION_ERROR", "Request validation failed.", {"errors": errors}
        ),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Catches FastAPI's own HTTPException plus Starlette's routing failures
    (unmatched route -> 404, wrong method -> 405) that would otherwise return
    the framework default {"detail": "..."}  instead of the envelope.
    """
    code = _STARLETTE_CODE_BY_STATUS.get(exc.status_code, "HTTP_ERROR")
    message = exc.detail if isinstance(exc.detail, str) else "An HTTP error occurred."
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(code, message),
        headers=getattr(exc, "headers", None),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = str(uuid.uuid4())
    logger.error(
        "Unhandled exception (correlation_id=%s) on %s %s",
        correlation_id,
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content=_envelope(
            "INTERNAL_ERROR",
            "An unexpected error occurred. Reference this ID if you need support.",
            {"correlation_id": correlation_id},
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
