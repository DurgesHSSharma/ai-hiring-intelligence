from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.config import AppEnv, settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The DB engine itself is created at import time in database.py — a
    # SQLAlchemy Engine doesn't open a connection until first use, so there
    # is nothing to eagerly do here for Phase 2. Phase 7/11 load ML artefacts.
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
