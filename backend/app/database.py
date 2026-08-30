"""Engine, session factory, declarative base, and the get_db dependency.

SQLite does not enforce foreign keys unless PRAGMA foreign_keys=ON is issued
on every connection — without it, every ondelete= behaviour declared on the
models is silently a no-op in development (Architecture.md 5.2), and
cascade tests would pass for the wrong reason. The listener below is
registered only when the configured DATABASE_URL is actually SQLite; on
PostgreSQL (which enforces foreign keys unconditionally) it is never
attached at all.
"""
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


_connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(settings.DATABASE_URL, connect_args=_connect_args)

if engine.dialect.name == "sqlite":

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
