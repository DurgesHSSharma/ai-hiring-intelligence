"""Phase 5 integration: field/skill extraction wired into the upload
pipeline, email dedupe (including the NULL-email guard — Memory.md
decision 18's carry-forward), get-or-create Application, and the
"upload the same resume twice" acceptance criterion from Phases.md.
"""
from pathlib import Path

from app.core.enums import JobSeniority, ParseStatus
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.candidate_skill import CandidateSkill
from app.models.job import Job

FIXTURES = Path(__file__).parent / "fixtures"


def _make_job(db_session, title: str = "Design Role") -> Job:
    job = Job(
        title=title,
        description="Looking for a product designer.",
        required_skills=[],
        min_experience_years=0.0,
        education_requirement="Bachelor's",
        seniority=JobSeniority.MID,
        location="Remote",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _part(filename: str, content: bytes, content_type: str):
    return ("files", (filename, content, content_type))


def _priya_docx(as_name: str = "priya.docx"):
    return _part(
        as_name,
        (FIXTURES / "two_column_table_resume.docx").read_bytes(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def _pdf(name: str = "sample_resume.pdf", as_name: str | None = None):
    return _part(as_name or name, (FIXTURES / name).read_bytes(), "application/pdf")


def _docx(name: str = "sample_resume.docx", as_name: str | None = None):
    return _part(
        as_name or name,
        (FIXTURES / name).read_bytes(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# --- fields populated on the success path ----------------------------------


def test_upload_populates_extracted_fields(client, db_session, auth_headers):
    job = _make_job(db_session)
    response = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_priya_docx()])
    candidate_id = response.json()["results"][0]["candidate_id"]

    candidate = db_session.get(Candidate, candidate_id)
    assert candidate.name == "Priya Nair"
    assert candidate.email == "priya.nair@example.com"
    assert candidate.phone == "+91 90000 11111"
    assert candidate.education == "Bachelor's Degree"
    assert candidate.education_level == 3
    assert candidate.experience_years is not None and candidate.experience_years > 0

    skills = db_session.query(CandidateSkill).filter_by(candidate_id=candidate.id).all()
    skill_names = {s.skill_name for s in skills}
    assert "Figma" in skill_names
    assert "Sketch" in skill_names


def test_parse_failed_candidate_has_no_extracted_fields(client, db_session, auth_headers):
    # Architecture.md 7.1's flow: field_extractor never runs on the
    # parse_failed path — verified end to end, not just at the unit level.
    job = _make_job(db_session)
    response = client.post(
        f"/api/v1/jobs/{job.id}/resumes",
        headers=auth_headers,
        files=[_part("scan.pdf", (FIXTURES / "image_only.pdf").read_bytes(), "application/pdf")],
    )
    candidate_id = response.json()["results"][0]["candidate_id"]
    candidate = db_session.get(Candidate, candidate_id)
    assert candidate.parse_status == ParseStatus.PARSE_FAILED
    assert candidate.name is None
    assert candidate.email is None
    assert candidate.experience_years is None
    assert db_session.query(CandidateSkill).filter_by(candidate_id=candidate.id).count() == 0


# --- dedupe by email (F3.6) --------------------------------------------------


def test_same_resume_uploaded_to_two_jobs_makes_one_candidate_two_applications(client, db_session, auth_headers):
    job_a = _make_job(db_session, title="Job A")
    job_b = _make_job(db_session, title="Job B")

    r1 = client.post(f"/api/v1/jobs/{job_a.id}/resumes", headers=auth_headers, files=[_priya_docx()])
    r2 = client.post(f"/api/v1/jobs/{job_b.id}/resumes", headers=auth_headers, files=[_priya_docx()])
    assert r1.status_code == 200 and r2.status_code == 200

    candidate_id_1 = r1.json()["results"][0]["candidate_id"]
    candidate_id_2 = r2.json()["results"][0]["candidate_id"]
    assert candidate_id_1 == candidate_id_2  # same candidate, deduped by email

    assert db_session.query(Candidate).count() == 1
    applications = db_session.query(Application).filter_by(candidate_id=candidate_id_1).all()
    assert len(applications) == 2
    assert {a.job_id for a in applications} == {job_a.id, job_b.id}


def test_same_resume_uploaded_twice_to_same_job_does_not_duplicate_application(client, db_session, auth_headers):
    job = _make_job(db_session)
    r1 = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_priya_docx()])
    r2 = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_priya_docx()])
    assert r1.status_code == 200 and r2.status_code == 200

    candidate_id = r1.json()["results"][0]["candidate_id"]
    assert db_session.query(Candidate).count() == 1
    assert db_session.query(Application).filter_by(candidate_id=candidate_id, job_id=job.id).count() == 1


def test_reupload_does_not_regress_application_status(client, db_session, auth_headers):
    job = _make_job(db_session)
    r1 = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_priya_docx()])
    candidate_id = r1.json()["results"][0]["candidate_id"]

    application = db_session.query(Application).filter_by(candidate_id=candidate_id, job_id=job.id).one()
    application.status = "shortlisted"
    db_session.commit()

    client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_priya_docx()])
    db_session.refresh(application)
    assert application.status.value == "shortlisted"


def test_null_email_candidates_are_never_collapsed_together(client, db_session, auth_headers):
    # sample_resume.pdf and sample_resume.docx (Phase 4 fixtures) have no
    # email address at all — this is exactly the scenario Memory.md
    # decision 18 flagged: without an explicit None-guard before the
    # dedupe query, SQLAlchemy's `Candidate.email == None` becomes an
    # `IS NULL` comparison that would match every NULL-email row and
    # collapse them into one.
    job = _make_job(db_session)
    r1 = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_pdf(as_name="a.pdf")])
    r2 = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_docx(as_name="b.docx")])

    candidate_id_1 = r1.json()["results"][0]["candidate_id"]
    candidate_id_2 = r2.json()["results"][0]["candidate_id"]
    assert candidate_id_1 != candidate_id_2
    assert db_session.query(Candidate).filter(Candidate.email.is_(None)).count() == 2


def test_reupload_replaces_stored_file_and_deletes_old_one(client, db_session, auth_headers, upload_dir):
    job = _make_job(db_session)
    r1 = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_priya_docx(as_name="v1.docx")])
    candidate_id = r1.json()["results"][0]["candidate_id"]
    old_path = db_session.get(Candidate, candidate_id).resume_path
    assert (upload_dir / old_path).exists()

    r2 = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_priya_docx(as_name="v2.docx")])
    db_session.expire_all()
    new_path = db_session.get(Candidate, candidate_id).resume_path

    assert new_path != old_path
    assert not (upload_dir / old_path).exists()
    assert (upload_dir / new_path).exists()


def test_reupload_invalidates_cached_embedding(client, db_session, auth_headers):
    # Phase 7 (F5.5): a cached embedding was computed from the OLD
    # resume_text. Re-upload changes resume_text on the dedupe path
    # without this invalidation, a stale vector would silently score the
    # wrong document once embedding-mode scoring runs.
    job = _make_job(db_session)
    r1 = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_priya_docx()])
    candidate_id = r1.json()["results"][0]["candidate_id"]

    candidate = db_session.get(Candidate, candidate_id)
    candidate.embedding = [0.1, 0.2, 0.3]  # simulates a prior embedding-mode scoring run
    db_session.commit()

    client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_priya_docx()])
    db_session.expire_all()
    assert db_session.get(Candidate, candidate_id).embedding is None


def test_reupload_replaces_skills_rather_than_accumulating(client, db_session, auth_headers):
    job = _make_job(db_session)
    client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_priya_docx()])
    client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_priya_docx()])

    candidate = db_session.query(Candidate).one()
    skills = db_session.query(CandidateSkill).filter_by(candidate_id=candidate.id).all()
    skill_names = [s.skill_name for s in skills]
    # No duplicates from the second pass re-inserting the same matches.
    assert len(skill_names) == len(set(skill_names))
