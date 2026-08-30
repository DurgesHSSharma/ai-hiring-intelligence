from sqlalchemy.exc import OperationalError

from app.database import get_db
from app.main import app


def test_health_returns_200_and_status_healthy(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "healthy",
        "version": "0.1.0",
        "environment": "development",
        "database": "connected",
    }


class _BrokenSession:
    def execute(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


def test_health_returns_503_when_database_unreachable(client):
    def _broken_get_db():
        yield _BrokenSession()

    original_override = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = _broken_get_db
    try:
        response = client.get("/api/v1/health")
    finally:
        app.dependency_overrides[get_db] = original_override

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"
