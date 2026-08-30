"""Domain exception hierarchy. Services raise these; HTTPException is never
raised in service code (Rules.md 5.2). error_handlers.py maps every one of
these to the standard envelope from Architecture.md 6.1.
"""
from typing import Any


class AppError(Exception):
    """Base domain error. Carries the code/message/details/http_status that
    error_handlers.py turns into the response envelope.

    Subclasses set sensible class-level defaults; callers override per-raise
    with the specific error code from Rules.md 5.3, e.g.:
        raise NotFoundError("Job not found.", code="JOB_NOT_FOUND", details={"job_id": job_id})
    """

    code: str = "APP_ERROR"
    http_status: int = 400
    message: str = "An application error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        http_status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(AppError):
    code = "NOT_FOUND"
    http_status = 404
    message = "The requested resource was not found."


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    http_status = 400
    message = "The request violates a business rule."


class ConflictError(AppError):
    code = "CONFLICT"
    http_status = 409
    message = "The request conflicts with existing state."


class AuthenticationError(AppError):
    code = "AUTHENTICATION_ERROR"
    http_status = 401
    message = "Authentication failed."


class AuthorizationError(AppError):
    code = "AUTHORIZATION_ERROR"
    http_status = 403
    message = "You do not have permission to perform this action."


class FileValidationError(AppError):
    code = "FILE_VALIDATION_ERROR"
    http_status = 415
    message = "The uploaded file failed validation."


class ParsingError(AppError):
    code = "PARSING_ERROR"
    http_status = 422
    message = "The file could not be parsed."


class ModelUnavailableError(AppError):
    code = "MODEL_UNAVAILABLE"
    http_status = 503
    message = "The required model artefact is unavailable."


class LLMError(AppError):
    code = "LLM_ERROR"
    http_status = 503
    message = "The language model provider failed."
