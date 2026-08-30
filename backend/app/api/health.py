import logging

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str


@router.get("/health", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
def get_health(response: Response, db: Session = Depends(get_db)) -> HealthResponse:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # Exception type only, never the raw message — some drivers echo the
        # DSN (and therefore DATABASE_URL's credentials) into the error text,
        # which Rules.md 5.5 forbids logging.
        logger.warning("Health check database probe failed: %s", type(exc).__name__)
        response.status_code = 503
        return HealthResponse(
            status="degraded",
            version="0.1.0",
            environment=settings.APP_ENV.value,
            database="unreachable",
        )

    return HealthResponse(
        status="healthy",
        version="0.1.0",
        environment=settings.APP_ENV.value,
        database="connected",
    )
