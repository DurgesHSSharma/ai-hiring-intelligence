import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.enums import UserRole
from app.database import Base, get_db
from app.dependencies import interview_question_rate_limiter
from app.main import app
from app.models.user import User
from app.utils import files as files_module


@pytest.fixture(autouse=True)
def _reset_interview_rate_limiter():
    """The rate limiter (app/core/rate_limit.py) is a module-level
    singleton shared by the whole test process, unlike the database or
    upload_dir fixtures above, which are freshly isolated per test. Most
    tests register their own first user in a fresh in-memory DB, so that
    user consistently gets id 1 — meaning, without this reset, unrelated
    tests hitting POST /candidates/{id}/interview-questions would
    silently share one running count and could start failing with a
    spurious 429 depending on run order alone.
    """
    interview_question_rate_limiter.reset()
    yield
    interview_question_rate_limiter.reset()


@pytest.fixture
def db_session():
    """A fresh in-memory SQLite database per test (Rules.md 6).

    StaticPool is required, not incidental: without it, every new connection
    the engine opens (FastAPI's get_db opens one per request) would see its
    own empty :memory: database instead of the one Base.metadata.create_all
    populated below. The FK-enforcement pragma is attached here too, so
    tests exercise the same enforcement path production does.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    """Isolates resume file storage per test, the same way db_session
    isolates the database above — without this, every upload/delete test
    would read and write the real backend/storage/, and a delete test could
    in principle remove a real file left there by manual use of the app.
    utils/files.py's save/resolve/delete helpers all read the module-level
    UPLOAD_DIR at call time, so patching the attribute here is enough to
    redirect every one of them; no caller needs to know about tmp_path.
    monkeypatch reverts the attribute automatically at teardown.
    """
    monkeypatch.setattr(files_module, "UPLOAD_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def client(db_session, upload_dir) -> TestClient:
    """Default client: server exceptions propagate (fine for 2xx/4xx tests)."""
    return TestClient(app)


@pytest.fixture
def client_allow_server_errors(db_session, upload_dir) -> TestClient:
    """TestClient defaults to raise_server_exceptions=True, which re-raises an
    unhandled exception instead of returning the 500 response. Any test that
    exercises the unhandled_exception_handler needs this fixture instead.
    """
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth_headers(client, db_session) -> dict[str, str]:
    """A registered recruiter's bearer token. Recruiter is the only role a
    client can ever self-assign (Rules.md 1.6/1.7 — role changes are out of
    scope for v1), so this is the ordinary authenticated-user fixture.
    """
    client.post(
        "/api/v1/auth/register",
        json={"name": "Test Recruiter", "email": "recruiter@example.com", "password": "correct-horse-battery"},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "recruiter@example.com", "password": "correct-horse-battery"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def admin_headers(client, db_session) -> dict[str, str]:
    """An admin's bearer token. There is deliberately no client-facing way to
    create one — register normally, then promote directly in the DB, exactly
    as a real admin promotion would happen out-of-band in v1.
    """
    client.post(
        "/api/v1/auth/register",
        json={"name": "Test Admin", "email": "admin@example.com", "password": "correct-horse-battery"},
    )
    user = db_session.query(User).filter(User.email == "admin@example.com").one()
    user.role = UserRole.ADMIN
    db_session.commit()
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}
