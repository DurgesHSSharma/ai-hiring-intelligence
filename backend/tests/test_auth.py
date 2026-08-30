"""Phase 2 acceptance: register, duplicate email, login, wrong password,
protected route without a token, protected route with an expired token.
Plus the other two auth-dependency failure paths (malformed token, valid
token for an unknown user) so all four TOKEN_*/INVALID_CREDENTIALS codes
are proven, not just asserted in code review.
"""
from app.core.security import create_access_token
from app.models.user import User


def _register_payload(email: str = "ada@example.com") -> dict:
    return {"name": "Ada Lovelace", "email": email, "password": "correct-horse-battery"}


def test_register_returns_201_with_no_password_hash(client):
    response = client.post("/api/v1/auth/register", json=_register_payload())
    assert response.status_code == 201
    body = response.json()
    assert "password_hash" not in body
    assert "password" not in body
    assert body["email"] == "ada@example.com"
    assert body["role"] == "recruiter"
    assert "id" in body
    assert "created_at" in body


def test_register_with_role_admin_rejected_as_unknown_field(client, db_session):
    payload = _register_payload("mallory@example.com")
    payload["role"] = "admin"
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert db_session.query(User).filter(User.email == "mallory@example.com").one_or_none() is None


def test_register_duplicate_email_returns_409(client):
    client.post("/api/v1/auth/register", json=_register_payload())
    response = client.post("/api/v1/auth/register", json=_register_payload())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DUPLICATE_EMAIL"


def test_login_success_returns_token_and_user(client):
    client.post("/api/v1/auth/register", json=_register_payload())
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "correct-horse-battery"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert "password_hash" not in body["user"]
    assert body["user"]["email"] == "ada@example.com"


def test_login_wrong_password_returns_401(client):
    client.post("/api/v1/auth/register", json=_register_payload())
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_me_success_with_valid_token(client):
    client.post("/api/v1/auth/register", json=_register_payload())
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "correct-horse-battery"},
    )
    token = login_response.json()["access_token"]
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "ada@example.com"


def test_me_without_token_returns_401_token_missing(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_MISSING"


def test_me_with_malformed_token_returns_401_token_invalid(client):
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


def test_me_with_expired_token_returns_401_token_expired(client):
    expired_token = create_access_token(subject="1", expires_minutes=-1)
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_me_with_valid_token_for_unknown_user_returns_401_invalid_credentials(client):
    token = create_access_token(subject="99999")
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
