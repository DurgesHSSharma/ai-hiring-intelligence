"""Phase 12 CSV export acceptance (Phases.md Phase 12, PRD F13):
filter-awareness, exact row/order equality with the equivalently filtered
/candidates result, and empty-result handling.
"""
import csv
import io

from app.core.enums import ApplicationStatus, JobSeniority, ParseStatus, ScoringMethod
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.candidate_score import CandidateScore
from app.models.job import Job


def _make_job(db_session, **overrides) -> Job:
    defaults = dict(
        title="Backend Engineer",
        description="Build APIs with Python and FastAPI.",
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


def _make_candidate(db_session, email: str, **overrides) -> Candidate:
    defaults = dict(
        name=f"Candidate {email}",
        email=email,
        resume_path=f"storage/{email}.pdf",
        resume_filename=f"{email}.pdf",
        resume_text="Experienced Python developer.",
        parse_status=ParseStatus.PARSED,
        experience_years=3.0,
    )
    defaults.update(overrides)
    candidate = Candidate(**defaults)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _apply(db_session, candidate: Candidate, job: Job, status=ApplicationStatus.NEW) -> None:
    db_session.add(Application(candidate_id=candidate.id, job_id=job.id, status=status))
    db_session.commit()


def _score(db_session, candidate: Candidate, job: Job, final_fit_score: float, missing_skills=None) -> None:
    db_session.add(
        CandidateScore(
            candidate_id=candidate.id,
            job_id=job.id,
            resume_match_score=final_fit_score,
            skill_match_score=final_fit_score,
            experience_score=final_fit_score,
            education_score=100.0,
            final_fit_score=final_fit_score,
            missing_skills=missing_skills or [],
            scoring_method=ScoringMethod.TFIDF,
        )
    )
    db_session.commit()


def _seed_five(db_session, job: Job) -> list[Candidate]:
    candidates = []
    for i in range(5):
        candidate = _make_candidate(db_session, email=f"exp{i}@example.com", experience_years=float(i))
        _apply(db_session, candidate, job)
        _score(db_session, candidate, job, final_fit_score=50.0 + i * 10, missing_skills=["SQL"] if i % 2 else [])
        candidates.append(candidate)
    return candidates


def test_export_csv_content_type_and_header(client, db_session, auth_headers):
    job = _make_job(db_session)
    _seed_five(db_session, job)

    response = client.get(f"/api/v1/jobs/{job.id}/export/csv", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]

    reader = csv.reader(io.StringIO(response.text))
    header = next(reader)
    assert header == [
        "candidate_id", "name", "email", "fit_score", "resume_match_score", "skill_match_score",
        "experience_score", "education_score", "missing_skills", "status",
    ]


def test_export_csv_matches_filtered_candidates_api_exactly(client, db_session, auth_headers):
    job = _make_job(db_session)
    _seed_five(db_session, job)

    filters = "min_score=60&sort_by=fit_score&sort_order=asc"
    api_response = client.get(f"/api/v1/candidates?job_id={job.id}&{filters}", headers=auth_headers)
    api_items = api_response.json()["items"]
    api_ids_in_order = [item["id"] for item in api_items]

    csv_response = client.get(f"/api/v1/jobs/{job.id}/export/csv?{filters}", headers=auth_headers)
    reader = csv.DictReader(io.StringIO(csv_response.text))
    csv_rows = list(reader)
    csv_ids_in_order = [int(row["candidate_id"]) for row in csv_rows]

    assert len(csv_rows) == len(api_items) > 0
    assert csv_ids_in_order == api_ids_in_order

    for api_item, csv_row in zip(api_items, csv_rows):
        assert api_item["id"] == int(csv_row["candidate_id"])
        assert api_item["fit_score"] == float(csv_row["fit_score"])


def test_export_csv_honours_skills_and_min_experience_filters(client, db_session, auth_headers):
    job = _make_job(db_session)
    candidates = _seed_five(db_session, job)
    from app.models.candidate_skill import CandidateSkill
    from app.core.enums import SkillSource, SkillType

    db_session.add(
        CandidateSkill(
            candidate_id=candidates[4].id, skill_name="Python", skill_type=SkillType.TECHNICAL, source=SkillSource.DICTIONARY
        )
    )
    db_session.commit()

    filters = "skills=Python&min_experience=2"
    api_ids = {
        item["id"] for item in client.get(f"/api/v1/candidates?job_id={job.id}&{filters}", headers=auth_headers).json()["items"]
    }
    csv_response = client.get(f"/api/v1/jobs/{job.id}/export/csv?{filters}", headers=auth_headers)
    reader = csv.DictReader(io.StringIO(csv_response.text))
    csv_ids = {int(row["candidate_id"]) for row in reader}

    assert api_ids == csv_ids == {candidates[4].id}


def test_export_csv_empty_result(client, db_session, auth_headers):
    job = _make_job(db_session)
    _seed_five(db_session, job)

    response = client.get(f"/api/v1/jobs/{job.id}/export/csv?min_score=99.9", headers=auth_headers)
    assert response.status_code == 200
    reader = csv.reader(io.StringIO(response.text))
    rows = list(reader)
    assert len(rows) == 1  # header only, no data rows


def test_export_csv_missing_job_returns_404(client, auth_headers):
    response = client.get("/api/v1/jobs/999999/export/csv", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_export_csv_without_token_returns_401(client, db_session):
    job = _make_job(db_session)
    response = client.get(f"/api/v1/jobs/{job.id}/export/csv")
    assert response.status_code == 401


def test_export_csv_missing_skills_and_status_columns(client, db_session, auth_headers):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email="withstatus@example.com")
    _apply(db_session, candidate, job, status=ApplicationStatus.SHORTLISTED)
    _score(db_session, candidate, job, final_fit_score=70.0, missing_skills=["SQL", "FastAPI"])

    response = client.get(f"/api/v1/jobs/{job.id}/export/csv", headers=auth_headers)
    reader = csv.DictReader(io.StringIO(response.text))
    row = next(reader)
    assert row["status"] == "shortlisted"
    assert row["missing_skills"] == "SQL; FastAPI"
