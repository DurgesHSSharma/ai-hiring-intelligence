import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.config import AppEnv, settings
from app.core.error_handlers import register_exception_handlers
from app.core.exceptions import ModelUnavailableError
from app.core.logging import configure_logging
from app.ml.attrition import predictor as attrition_predictor

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The DB engine itself is created at import time in database.py — a
    # SQLAlchemy Engine doesn't open a connection until first use, so there
    # is nothing to eagerly do here for Phase 2.
    #
    # Phase 11: the attrition model is loaded exactly once, here, never per
    # request (Rules.md 4.6, PRD F9.6). A missing/corrupt artifact set must
    # NOT crash the whole app — Phases.md Phase 11's own acceptance
    # criterion is that unrelated endpoints stay healthy — so the failure is
    # caught and logged, and attrition_predictor.get_artifacts() (called
    # from every attrition route via attrition_service.py) raises
    # ModelUnavailableError(code=ATTRITION_MODEL_MISSING) per request
    # instead, degrading only the attrition routes.
    try:
        artifacts = attrition_predictor.load_artifacts(settings.ATTRITION_MODEL_PATH)
        attrition_predictor.set_artifacts(artifacts)
        logger.info("Attrition model loaded (version=%s).", artifacts.model_version)
    except ModelUnavailableError as exc:
        attrition_predictor.set_artifacts(None)
        logger.error("Attrition model unavailable at startup: %s", exc.message)

    yield


def create_app() -> FastAPI:
    configure_logging("DEBUG" if settings.APP_ENV == AppEnv.DEVELOPMENT else "INFO")

    app = FastAPI(
        title="AI Hiring Intelligence",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_app()
