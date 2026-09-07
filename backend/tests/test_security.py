"""Phase 15 security hardening: targeted verification tests for gaps the
per-phase test files don't already close.

JWT expiry itself and the four TOKEN_*/INVALID_CREDENTIALS codes are
already thoroughly proven against /auth/me in test_auth.py; the error
envelope shape (no traceback, no internals, correlation id on 500s) is
already proven for all four registered handlers in test_error_handlers.py.
This file adds what those don't:

- bcrypt-format verification on the stored password hash, not just that
  login/register happen to work.
- protected-route rejection (missing/invalid/expired token) proven on
  representative non-auth endpoints, not only /auth/me.
- a real executable disguised as a resume, submitted through the actual
  upload endpoint, plus the other three upload-validation tiers not
  already covered in test_resumes.py (MIME/extension mismatch, empty
  file).
- CORS behavior verified against the real middleware, not just read from
  config.
"""
from pathlib import Path

import pytest

from app.core.enums import JobSeniority
from app.core.security import create_access_token, hash_password, verify_password
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.user import User

FIXTURES = Path(__file__).parent / "fixtures"


def _make_job(db_session) -> Job:
    job = Job(
        title="Backend Engineer",
        description="Build and ship backend services.",
        required_skills=["Python"],
        min_experience_years=0.0,
        education_requirement="Bachelor's",
        seniority=JobSeniority.MID,
        location="Remote",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


# --- 4.1 password hashing ---------------------------------------------------


def test_password_hash_is_bcrypt_not_plaintext(client, db_session):
    client.post(
        "/api/v1/auth/register",
        json={"name": "Grace Hopper", "email": "grace@example.com", "password": "correct-horse-battery"},
    )
    user = db_session.query(User).filter(User.email == "grace@example.com").one()
    assert user.password_hash != "correct-horse-battery"
    assert user.password_hash.startswith("$2b$")
    assert verify_password("correct-horse-battery", user.password_hash) is True
    assert verify_password("wrong-password", user.password_hash) is False


def test_hash_password_salts_uniquely():
    # bcrypt salts randomly per call — hashing the same password twice must
    # not produce the same hash, or a leaked table could be matched by
    # comparing hashes directly instead of needing the plaintext.
    first = hash_password("same-password")
    second = hash_password("same-password")
    assert first != second
    assert verify_password("same-password", first)
    assert verify_password("same-password", second)


# --- 4.3 protected routes: consistency beyond /auth/me ----------------------

_REPRESENTATIVE_ENDPOINTS = [
    ("get", "/jobs"),
    ("get", "/candidates"),
    ("get", "/analytics/overview"),
]


@pytest.mark.parametrize("method,path_suffix", _REPRESENTATIVE_ENDPOINTS)
def test_representative_endpoints_reject_missing_token(client, method, path_suffix):
    response = getattr(client, method)(f"/api/v1{path_suffix}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_MISSING"


@pytest.mark.parametrize("method,path_suffix", _REPRESENTATIVE_ENDPOINTS)
def test_representative_endpoints_reject_invalid_token(client, method, path_suffix):
    response = getattr(client, method)(
        f"/api/v1{path_suffix}", headers={"Authorization": "Bearer garbage-not-a-jwt"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


@pytest.mark.parametrize("method,path_suffix", _REPRESENTATIVE_ENDPOINTS)
def test_representative_endpoints_reject_expired_token(client, method, path_suffix):
    expired = create_access_token(subject="1", expires_minutes=-1)
    response = getattr(client, method)(
        f"/api/v1{path_suffix}", headers={"Authorization": f"Bearer {expired}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


# --- 4.4 upload security -----------------------------------------------------


def test_executable_renamed_to_pdf_is_rejected_by_the_real_endpoint(client, db_session, auth_headers):
    """The Phase 15 scripted security check: a Windows PE executable (MZ
    header), renamed to .pdf, with the client also lying about the
    declared Content-Type, submitted through the real batch upload
    endpoint end to end — not just the unit-level validator. Must be
    rejected at the magic-byte check before any text extraction runs.
    """
    job = _make_job(db_session)
    exe_bytes = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 64
    parts = [("files", ("resume.pdf", exe_bytes, "application/pdf"))]

    response = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=parts)

    assert response.status_code == 200
    body = response.json()
    assert body["uploaded"] == 0
    assert body["failed"] == 1
    result = body["results"][0]
    assert result["status"] == "parse_failed"
    assert result["code"] == "UNSUPPORTED_FILE_TYPE"
    assert result["candidate_id"] is None
    assert db_session.query(Candidate).count() == 0


def test_executable_renamed_to_docx_is_rejected(client, db_session, auth_headers):
    job = _make_job(db_session)
    exe_bytes = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 64
    parts = [
        (
            "files",
            (
                "resume.docx",
                exe_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )
    ]

    response = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=parts)

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "parse_failed"
    assert result["code"] == "UNSUPPORTED_FILE_TYPE"


def test_mime_type_mismatch_rejected_even_with_correct_extension_and_bytes(client, db_session, auth_headers):
    """A genuine PDF's bytes, under a .pdf filename, but a Content-Type the
    validator doesn't accept for that extension. The MIME check runs
    before the magic-byte check (Rules.md 5.4: cheapest first) and must
    reject on its own, independent of the file's real content.
    """
    job = _make_job(db_session)
    real_pdf_bytes = (FIXTURES / "sample_resume.pdf").read_bytes()
    parts = [("files", ("resume.pdf", real_pdf_bytes, "text/plain"))]

    response = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=parts)

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["code"] == "UNSUPPORTED_FILE_TYPE"
    assert response.json()["uploaded"] == 0


def test_empty_file_rejected(client, db_session, auth_headers):
    job = _make_job(db_session)
    parts = [("files", ("empty.pdf", b"", "application/pdf"))]

    response = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=parts)

    assert response.status_code == 200
    body = response.json()
    result = body["results"][0]
    assert result["status"] == "parse_failed"
    assert result["code"] == "UNSUPPORTED_FILE_TYPE"  # empty content fails the magic-byte check
    assert body["uploaded"] == 0
    assert db_session.query(Candidate).count() == 0


# --- 4.5 CORS ----------------------------------------------------------------


def test_cors_allows_configured_frontend_origin(client):
    response = client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_rejects_preflight_from_unauthorized_origin(client):
    response = client.options(
        "/api/v1/health",
        headers={"Origin": "http://evil.example.com", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_actual_request_from_unauthorized_origin_carries_no_allow_header(client):
    # The server still answers — CORS is enforced by the browser reading
    # this header, not by the server refusing the request — but omitting
    # it means a script running on an unlisted origin can't read the
    # response even though the HTTP call itself succeeded.
    response = client.get("/api/v1/health", headers={"Origin": "http://evil.example.com"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_configuration_does_not_use_wildcard():
    from app.config import settings

    assert "*" not in settings.cors_origins_list
    assert len(settings.cors_origins_list) > 0
