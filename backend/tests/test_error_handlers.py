"""Exercises all four registered handlers end to end through the real app.

Phase 1 builds no business endpoints, so the AppError/validation/unhandled
cases are triggered via throwaway routes added to the app instance here,
rather than routes that belong to a later phase.
"""
from pydantic import BaseModel

from app.core.exceptions import NotFoundError
from app.main import app


def _raise_not_found() -> None:
    raise NotFoundError(
        "Candidate not found.", code="CANDIDATE_NOT_FOUND", details={"candidate_id": 42}
    )


def _raise_unhandled() -> None:
    raise RuntimeError("boom - simulated unhandled failure")


class _TestBody(BaseModel):
    email: str


def _validate_body(payload: _TestBody) -> dict:
    return {"ok": True}


app.add_api_route("/_test/not-found", _raise_not_found, methods=["GET"])
app.add_api_route("/_test/unhandled", _raise_unhandled, methods=["GET"])
app.add_api_route("/_test/validate", _validate_body, methods=["POST"])


def test_app_error_returns_envelope(client):
    response = client.get("/_test/not-found")
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "CANDIDATE_NOT_FOUND",
            "message": "Candidate not found.",
            "details": {"candidate_id": 42},
        }
    }


def test_unhandled_exception_returns_internal_error(client_allow_server_errors):
    response = client_allow_server_errors.get("/_test/unhandled")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "correlation_id" in body["error"]["details"]
    assert "Traceback" not in response.text
    assert "boom" not in response.text


def test_request_validation_error_returns_envelope(client):
    response = client.post("/_test/validate", json={})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert body["error"]["details"]["errors"][0]["field"] == "email"


def test_unmatched_route_returns_not_found_envelope(client):
    response = client.get("/api/v1/nonexistent")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_wrong_method_returns_method_not_allowed_envelope(client):
    response = client.post("/api/v1/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
