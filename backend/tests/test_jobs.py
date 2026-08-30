"""Phase 3 acceptance: job CRUD, pagination, status-filtered listing, detail
aggregates on empty/populated sets, stale-marking on edit, cascading delete,
and admin-only enforcement on delete.
"""
from app.core.enums import ApplicationStatus, JobSeniority, JobStatus, ParseStatus, ScoringMethod
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.candidate_score import CandidateScore
from app.models.job import Job


def _job_payload(title: str = "Backend Engineer") -> dict:
    return {
        "title": title,
        "description": "Build and maintain REST APIs.",
        "required_skills": ["Python", "FastAPI"],
        "min_experience_years": 2.0,
        "education_requirement": "Bachelor's",
        "seniority": "mid",
        "location": "Remote",
    }


def _make_job(db_session, **overrides) -> Job:
    defaults = dict(
        title="X",
        description="Y",
        required_skills=["Python"],
        min_experience_years=0.0,
        education_requirement="Bachelor's",
        seniority=JobSeniority.MID,
        location="Remote",
    )
    defaults.update(overrides)
    job = Job(**defaults)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session, email: str = "c@example.com") -> Candidate:
    candidate = Candidate(
        email=email,
        resume_path="p",
        resume_filename="f.pdf",
        resume_text="some resume text",
        parse_status=ParseStatus.PARSED,
    )
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _make_score(db_session, candidate_id: int, job_id: int, final_fit_score: float = 50.0) -> CandidateScore:
    score = CandidateScore(
        candidate_id=candidate_id,
        job_id=job_id,
        resume_match_score=final_fit_score,
        skill_match_score=final_fit_score,
        experience_score=final_fit_score,
        education_score=final_fit_score,
        final_fit_score=final_fit_score,
        scoring_method=ScoringMethod.TFIDF,
    )
    db_session.add(score)
    db_session.commit()
    db_session.refresh(score)
    return score


# --- create -----------------------------------------------------------------


def test_create_job_returns_201(client, auth_headers):
    response = client.post("/api/v1/jobs", json=_job_payload(), headers=auth_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Backend Engineer"
    assert body["status"] == "open"
    assert body["created_by"] is not None


def test_create_job_without_token_returns_401(client):
    response = client.post("/api/v1/jobs", json=_job_payload())
    assert response.status_code == 401


# --- list / pagination / status filter --------------------------------------


def test_list_jobs_pagination_total_and_pages(client, db_session, auth_headers):
    for i in range(50):
        _make_job(db_session, title=f"Job {i}")

    response = client.get("/api/v1/jobs?page=1&page_size=20", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 50
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["pages"] == 3
    assert len(body["items"]) == 20


def test_list_jobs_default_hides_closed(client, db_session, auth_headers):
    _make_job(db_session, title="Open Job", status=JobStatus.OPEN)
    _make_job(db_session, title="Closed Job", status=JobStatus.CLOSED)

    response = client.get("/api/v1/jobs", headers=auth_headers)
    titles = [j["title"] for j in response.json()["items"]]
    assert "Open Job" in titles
    assert "Closed Job" not in titles


def test_list_jobs_status_closed_shows_only_closed(client, db_session, auth_headers):
    _make_job(db_session, title="Open Job", status=JobStatus.OPEN)
    _make_job(db_session, title="Closed Job", status=JobStatus.CLOSED)

    response = client.get("/api/v1/jobs?status=closed", headers=auth_headers)
    titles = [j["title"] for j in response.json()["items"]]
    assert titles == ["Closed Job"]


def test_list_jobs_status_all_shows_everything(client, db_session, auth_headers):
    _make_job(db_session, title="Open Job", status=JobStatus.OPEN)
    _make_job(db_session, title="Closed Job", status=JobStatus.CLOSED)

    response = client.get("/api/v1/jobs?status=all", headers=auth_headers)
    titles = {j["title"] for j in response.json()["items"]}
    assert titles == {"Open Job", "Closed Job"}


def test_list_jobs_search_matches_title_case_insensitively(client, db_session, auth_headers):
    _make_job(db_session, title="Senior Backend Engineer")
    _make_job(db_session, title="Data Scientist")

    response = client.get("/api/v1/jobs?search=backend", headers=auth_headers)
    titles = [j["title"] for j in response.json()["items"]]
    assert titles == ["Senior Backend Engineer"]


# --- detail aggregates --------------------------------------------------------


def test_get_job_detail_with_no_candidates_returns_nulls_not_zeros(client, db_session, auth_headers):
    job = _make_job(db_session)

    response = client.get(f"/api/v1/jobs/{job.id}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["candidate_count"] == 0
    assert body["average_fit_score"] is None
    assert body["top_candidate"] is None


def test_get_job_detail_aggregates_with_data(client, db_session, auth_headers):
    job = _make_job(db_session)
    low = _make_candidate(db_session, email="low@example.com")
    high = _make_candidate(db_session, email="high@example.com")
    db_session.add_all(
        [
            Application(candidate_id=low.id, job_id=job.id, status=ApplicationStatus.NEW),
            Application(candidate_id=high.id, job_id=job.id, status=ApplicationStatus.NEW),
        ]
    )
    db_session.commit()
    _make_score(db_session, low.id, job.id, final_fit_score=40.0)
    _make_score(db_session, high.id, job.id, final_fit_score=90.0)

    response = client.get(f"/api/v1/jobs/{job.id}", headers=auth_headers)
    body = response.json()
    assert body["candidate_count"] == 2
    assert body["average_fit_score"] == 65.0
    assert body["top_candidate"]["candidate_id"] == high.id
    assert body["top_candidate"]["final_fit_score"] == 90.0


def test_get_job_404(client, auth_headers):
    response = client.get("/api/v1/jobs/999999", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


# --- patch / stale-marking ----------------------------------------------------


def test_patch_job_description_change_marks_scores_stale(client, db_session, auth_headers):
    job = _make_job(db_session, description="original")
    candidate = _make_candidate(db_session)
    score = _make_score(db_session, candidate.id, job.id)

    response = client.patch(
        f"/api/v1/jobs/{job.id}", json={"description": "a materially different description"}, headers=auth_headers
    )
    assert response.status_code == 200
    db_session.refresh(score)
    assert score.is_stale is True


def test_patch_job_required_skills_content_change_marks_scores_stale(client, db_session, auth_headers):
    job = _make_job(db_session, required_skills=["Python", "SQL"])
    candidate = _make_candidate(db_session)
    score = _make_score(db_session, candidate.id, job.id)

    response = client.patch(
        f"/api/v1/jobs/{job.id}", json={"required_skills": ["Python", "Go"]}, headers=auth_headers
    )
    assert response.status_code == 200
    db_session.refresh(score)
    assert score.is_stale is True


def test_patch_job_required_skills_reordered_only_does_not_mark_stale(client, db_session, auth_headers):
    job = _make_job(db_session, required_skills=["Python", "SQL"])
    candidate = _make_candidate(db_session)
    score = _make_score(db_session, candidate.id, job.id)

    response = client.patch(
        f"/api/v1/jobs/{job.id}", json={"required_skills": ["SQL", "Python"]}, headers=auth_headers
    )
    assert response.status_code == 200
    db_session.refresh(score)
    assert score.is_stale is False


def test_patch_job_location_or_title_only_does_not_mark_stale(client, db_session, auth_headers):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    score = _make_score(db_session, candidate.id, job.id)

    response = client.patch(
        f"/api/v1/jobs/{job.id}",
        json={"location": "Berlin", "title": "Senior X"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    db_session.refresh(score)
    assert score.is_stale is False


def test_patch_job_resending_same_description_does_not_mark_stale(client, db_session, auth_headers):
    job = _make_job(db_session, description="unchanged text")
    candidate = _make_candidate(db_session)
    score = _make_score(db_session, candidate.id, job.id)

    response = client.patch(
        f"/api/v1/jobs/{job.id}", json={"description": "unchanged text"}, headers=auth_headers
    )
    assert response.status_code == 200
    db_session.refresh(score)
    assert score.is_stale is False


def test_patch_job_explicit_null_field_returns_422(client, db_session, auth_headers):
    job = _make_job(db_session)

    response = client.patch(f"/api/v1/jobs/{job.id}", json={"description": None}, headers=auth_headers)
    assert response.status_code == 422


def test_patch_job_404(client, auth_headers):
    response = client.patch("/api/v1/jobs/999999", json={"title": "New"}, headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


# --- delete: cascade + role enforcement ---------------------------------------


def test_delete_job_cascades_but_preserves_candidate(client, db_session, admin_headers):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    db_session.add(Application(candidate_id=candidate.id, job_id=job.id, status=ApplicationStatus.NEW))
    db_session.commit()
    _make_score(db_session, candidate.id, job.id)

    response = client.delete(f"/api/v1/jobs/{job.id}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json() == {"id": job.id, "deleted": True}

    assert db_session.query(Application).filter_by(job_id=job.id).count() == 0
    assert db_session.query(CandidateScore).filter_by(job_id=job.id).count() == 0
    assert db_session.get(Candidate, candidate.id) is not None


def test_delete_job_requires_admin_returns_403(client, db_session, auth_headers):
    job = _make_job(db_session)

    response = client.delete(f"/api/v1/jobs/{job.id}", headers=auth_headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_REQUIRED"


def test_delete_job_without_token_returns_401(client, db_session):
    job = _make_job(db_session)

    response = client.delete(f"/api/v1/jobs/{job.id}")
    assert response.status_code == 401


def test_delete_job_404_for_admin(client, admin_headers):
    response = client.delete("/api/v1/jobs/999999", headers=admin_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


# --- suggested skills (PRD F4.5) --------------------------------------------
# Read-only by design (project owner's explicit correction to the Phase 5
# plan): suggests skills found in the description that aren't already in
# required_skills, but never writes to required_skills itself.


def test_suggested_skills_excludes_already_listed(client, db_session, auth_headers):
    job = _make_job(
        db_session,
        description="Looking for a backend engineer skilled in Python, Docker, and healthcare domain knowledge.",
        required_skills=["Python"],
    )

    response = client.get(f"/api/v1/jobs/{job.id}/suggested-skills", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job.id
    suggested_names = {s["canonical"] for s in body["suggested"]}
    assert "Docker" in suggested_names
    assert "Healthcare" in suggested_names
    assert "Python" not in suggested_names  # already in required_skills


def test_suggested_skills_does_not_mutate_required_skills(client, db_session, auth_headers):
    job = _make_job(
        db_session,
        description="Looking for a backend engineer skilled in Python and Docker.",
        required_skills=["Python"],
    )

    client.get(f"/api/v1/jobs/{job.id}/suggested-skills", headers=auth_headers)

    db_session.expire_all()
    reloaded = db_session.get(Job, job.id)
    assert reloaded.required_skills == ["Python"]


def test_suggested_skills_404_for_missing_job(client, auth_headers):
    response = client.get("/api/v1/jobs/999999/suggested-skills", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"
