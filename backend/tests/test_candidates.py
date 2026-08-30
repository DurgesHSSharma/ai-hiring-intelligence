"""Phase 3 acceptance: candidate listing/detail/delete, the privacy boundary
on resume_text/resume_path, cascading delete (mirroring the job-side test),
and application status updates.
"""
from app.core.enums import ApplicationStatus, JobSeniority, ParseStatus, ScoringMethod, SkillSource, SkillType
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.candidate_score import CandidateScore
from app.models.candidate_skill import CandidateSkill
from app.models.job import Job


def _make_candidate(db_session, email: str = "c@example.com", **overrides) -> Candidate:
    defaults = dict(
        email=email,
        resume_path="storage/some-uuid.pdf",
        resume_filename="original.pdf",
        resume_text="this is private resume text that must never leave the API",
        parse_status=ParseStatus.PARSED,
    )
    defaults.update(overrides)
    candidate = Candidate(**defaults)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _make_job(db_session, title: str = "X") -> Job:
    job = Job(
        title=title,
        description="Y",
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


# --- list ----------------------------------------------------------------------


def test_list_candidates_pagination(client, db_session, auth_headers):
    for i in range(25):
        _make_candidate(db_session, email=f"c{i}@example.com")

    response = client.get("/api/v1/candidates?page=1&page_size=10", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 25
    assert body["pages"] == 3
    assert len(body["items"]) == 10


def test_list_candidates_excludes_resume_text_and_path(client, db_session, auth_headers):
    _make_candidate(db_session)

    response = client.get("/api/v1/candidates", headers=auth_headers)
    item = response.json()["items"][0]
    assert "resume_text" not in item
    assert "resume_path" not in item
    assert "embedding" not in item


def test_list_candidates_without_token_returns_401(client):
    response = client.get("/api/v1/candidates")
    assert response.status_code == 401


# --- detail ----------------------------------------------------------------------


def test_get_candidate_detail_includes_skills(client, db_session, auth_headers):
    candidate = _make_candidate(db_session)
    db_session.add(
        CandidateSkill(
            candidate_id=candidate.id,
            skill_name="Python",
            skill_type=SkillType.TECHNICAL,
            source=SkillSource.DICTIONARY,
        )
    )
    db_session.add(
        CandidateSkill(
            candidate_id=candidate.id,
            skill_name="Communication",
            skill_type=SkillType.SOFT,
            source=SkillSource.DICTIONARY,
        )
    )
    db_session.commit()

    response = client.get(f"/api/v1/candidates/{candidate.id}", headers=auth_headers)
    assert response.status_code == 200
    # Grouped by type (Phases.md Phase 5 acceptance), not a flat list — all
    # four keys present, an unpopulated group is an empty list, not absent.
    skills = response.json()["skills"]
    assert skills["technical"] == [{"skill_name": "Python", "skill_type": "technical", "source": "dictionary"}]
    assert skills["soft"] == [{"skill_name": "Communication", "skill_type": "soft", "source": "dictionary"}]
    assert skills["tool"] == []
    assert skills["domain"] == []


def test_get_candidate_detail_excludes_resume_text_and_path(client, db_session, auth_headers):
    candidate = _make_candidate(db_session)

    response = client.get(f"/api/v1/candidates/{candidate.id}", headers=auth_headers)
    body = response.json()
    assert "resume_text" not in body
    assert "resume_path" not in body


def test_get_candidate_404(client, auth_headers):
    response = client.get("/api/v1/candidates/999999", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CANDIDATE_NOT_FOUND"


# --- delete ----------------------------------------------------------------------


def test_delete_candidate_removes_row(client, db_session, auth_headers):
    candidate = _make_candidate(db_session)

    response = client.delete(f"/api/v1/candidates/{candidate.id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"id": candidate.id, "deleted": True}
    # A plain query, not db_session.get(): .get() can return a cached,
    # non-expired instance straight from this session's identity map without
    # re-querying — and the delete above happened through the API's own,
    # separate session, which this session's cache has no way to know about.
    assert db_session.query(Candidate).filter_by(id=candidate.id).one_or_none() is None


def test_delete_candidate_404(client, auth_headers):
    response = client.delete("/api/v1/candidates/999999", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CANDIDATE_NOT_FOUND"


def test_delete_candidate_cascades_but_job_survives(client, db_session, auth_headers):
    candidate = _make_candidate(db_session)
    job = _make_job(db_session)
    db_session.add(
        CandidateSkill(
            candidate_id=candidate.id,
            skill_name="Python",
            skill_type=SkillType.TECHNICAL,
            source=SkillSource.DICTIONARY,
        )
    )
    db_session.add(Application(candidate_id=candidate.id, job_id=job.id, status=ApplicationStatus.NEW))
    db_session.commit()
    db_session.add(
        CandidateScore(
            candidate_id=candidate.id,
            job_id=job.id,
            resume_match_score=1,
            skill_match_score=1,
            experience_score=1,
            education_score=1,
            final_fit_score=1,
            scoring_method=ScoringMethod.TFIDF,
        )
    )
    db_session.commit()

    response = client.delete(f"/api/v1/candidates/{candidate.id}", headers=auth_headers)
    assert response.status_code == 200

    assert db_session.query(CandidateSkill).filter_by(candidate_id=candidate.id).count() == 0
    assert db_session.query(Application).filter_by(candidate_id=candidate.id).count() == 0
    assert db_session.query(CandidateScore).filter_by(candidate_id=candidate.id).count() == 0
    assert db_session.get(Job, job.id) is not None


# --- applications ----------------------------------------------------------------


def test_patch_application_status_success(client, db_session, auth_headers):
    candidate = _make_candidate(db_session)
    job = _make_job(db_session)
    application = Application(candidate_id=candidate.id, job_id=job.id, status=ApplicationStatus.NEW)
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)

    response = client.patch(
        f"/api/v1/applications/{application.id}", json={"status": "shortlisted"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "shortlisted"
    db_session.refresh(application)
    assert application.status == ApplicationStatus.SHORTLISTED


def test_patch_application_404(client, auth_headers):
    response = client.patch(
        "/api/v1/applications/999999", json={"status": "shortlisted"}, headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "APPLICATION_NOT_FOUND"


def test_patch_application_invalid_status_value_returns_422(client, db_session, auth_headers):
    candidate = _make_candidate(db_session)
    job = _make_job(db_session)
    application = Application(candidate_id=candidate.id, job_id=job.id, status=ApplicationStatus.NEW)
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)

    response = client.patch(
        f"/api/v1/applications/{application.id}", json={"status": "not-a-real-status"}, headers=auth_headers
    )
    assert response.status_code == 422
