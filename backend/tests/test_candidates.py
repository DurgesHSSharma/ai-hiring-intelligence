"""Phase 3 acceptance: candidate listing/detail/delete, the privacy boundary
on resume_text/resume_path, cascading delete (mirroring the job-side test),
and application status updates. Phase 12 acceptance (Phases.md): the full
F12 filter/search/sort surface on GET /candidates, all executed in SQL,
including AND semantics across combined filters and stable two-direction
sorting.
"""
from sqlalchemy import text

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


# --- filter / search / sort (Phase 12, F12) --------------------------------------


def _add_skill(db_session, candidate: Candidate, name: str) -> None:
    db_session.add(
        CandidateSkill(candidate_id=candidate.id, skill_name=name, skill_type=SkillType.TECHNICAL, source=SkillSource.DICTIONARY)
    )
    db_session.commit()


def _score(db_session, candidate: Candidate, job: Job, final_fit_score: float) -> None:
    db_session.add(
        CandidateScore(
            candidate_id=candidate.id,
            job_id=job.id,
            resume_match_score=final_fit_score,
            skill_match_score=final_fit_score,
            experience_score=final_fit_score,
            education_score=100.0,
            final_fit_score=final_fit_score,
            scoring_method=ScoringMethod.TFIDF,
        )
    )
    db_session.commit()


def test_filter_min_score(client, db_session, auth_headers):
    job = _make_job(db_session)
    low = _make_candidate(db_session, email="low-score@example.com")
    high = _make_candidate(db_session, email="high-score@example.com")
    _score(db_session, low, job, 50.0)
    _score(db_session, high, job, 90.0)

    response = client.get("/api/v1/candidates?min_score=80", headers=auth_headers)
    ids = {item["id"] for item in response.json()["items"]}
    assert ids == {high.id}


def test_filter_skills_present(client, db_session, auth_headers):
    with_skill = _make_candidate(db_session, email="has-python@example.com")
    without_skill = _make_candidate(db_session, email="no-python@example.com")
    _add_skill(db_session, with_skill, "Python")

    response = client.get("/api/v1/candidates?skills=Python", headers=auth_headers)
    ids = {item["id"] for item in response.json()["items"]}
    assert with_skill.id in ids
    assert without_skill.id not in ids


def test_filter_min_experience(client, db_session, auth_headers):
    junior = _make_candidate(db_session, email="junior@example.com", experience_years=0.5)
    senior = _make_candidate(db_session, email="senior@example.com", experience_years=5.0)

    response = client.get("/api/v1/candidates?min_experience=2", headers=auth_headers)
    ids = {item["id"] for item in response.json()["items"]}
    assert senior.id in ids
    assert junior.id not in ids


def test_filter_min_experience_excludes_unknown_not_treats_as_passing(client, db_session, auth_headers):
    unknown = _make_candidate(db_session, email="unknown-exp@example.com", experience_years=None)
    response = client.get("/api/v1/candidates?min_experience=0", headers=auth_headers)
    ids = {item["id"] for item in response.json()["items"]}
    assert unknown.id not in ids


def test_combined_filters_are_sql_and_semantics(client, db_session, auth_headers):
    """Phases.md Phase 12's exact acceptance example: min_score=80 AND
    skills=Python AND min_experience=2 returns only candidates satisfying
    ALL THREE, proven both via the API and an independent manual SQL query.
    """
    job = _make_job(db_session)

    only_a = _make_candidate(db_session, email="only-a@example.com", experience_years=1.0)
    _score(db_session, only_a, job, 90.0)
    _add_skill(db_session, only_a, "SQL")

    only_b_and_c = _make_candidate(db_session, email="only-bc@example.com", experience_years=5.0)
    _score(db_session, only_b_and_c, job, 50.0)
    _add_skill(db_session, only_b_and_c, "Python")

    only_a_and_b = _make_candidate(db_session, email="only-ab@example.com", experience_years=1.0)
    _score(db_session, only_a_and_b, job, 85.0)
    _add_skill(db_session, only_a_and_b, "Python")

    only_c = _make_candidate(db_session, email="only-c@example.com", experience_years=4.0)
    _score(db_session, only_c, job, 40.0)
    _add_skill(db_session, only_c, "Java")

    all_three = _make_candidate(db_session, email="all-three@example.com", experience_years=3.0)
    _score(db_session, all_three, job, 88.0)
    _add_skill(db_session, all_three, "Python")
    _add_skill(db_session, all_three, "SQL")

    # Each filter alone returns more than 0 rows.
    count_a = len(client.get("/api/v1/candidates?min_score=80", headers=auth_headers).json()["items"])
    count_b = len(client.get("/api/v1/candidates?skills=Python", headers=auth_headers).json()["items"])
    count_c = len(client.get("/api/v1/candidates?min_experience=2", headers=auth_headers).json()["items"])
    assert count_a > 0 and count_b > 0 and count_c > 0

    combined = client.get(
        "/api/v1/candidates?min_score=80&skills=Python&min_experience=2", headers=auth_headers
    )
    assert combined.status_code == 200
    items = combined.json()["items"]
    ids = {item["id"] for item in items}
    assert ids == {all_three.id}
    assert items[0]["fit_score"] == 88.0

    # Independent manual SQL query over the same three conditions.
    manual_rows = db_session.execute(
        text(
            """
            SELECT DISTINCT c.id
            FROM candidates c
            JOIN candidate_scores cs ON cs.candidate_id = c.id
            JOIN candidate_skills sk ON sk.candidate_id = c.id AND LOWER(sk.skill_name) = LOWER('Python')
            WHERE cs.final_fit_score >= 80
              AND c.experience_years >= 2
            """
        )
    ).all()
    manual_ids = {row[0] for row in manual_rows}
    assert manual_ids == ids == {all_three.id}


def test_search_matches_name_email_or_skill(client, db_session, auth_headers):
    by_name = _make_candidate(db_session, email="zzz1@example.com", name="Aria Nakamura")
    by_email = _make_candidate(db_session, email="findme@example.com", name="Someone Else")
    by_skill = _make_candidate(db_session, email="zzz3@example.com", name="Third Person")
    _add_skill(db_session, by_skill, "Kubernetes")
    unrelated = _make_candidate(db_session, email="zzz4@example.com", name="Unrelated Person")

    name_hit = client.get("/api/v1/candidates?search=Nakamura", headers=auth_headers).json()["items"]
    assert {c["id"] for c in name_hit} == {by_name.id}

    email_hit = client.get("/api/v1/candidates?search=findme", headers=auth_headers).json()["items"]
    assert {c["id"] for c in email_hit} == {by_email.id}

    skill_hit = client.get("/api/v1/candidates?search=Kubernetes", headers=auth_headers).json()["items"]
    assert {c["id"] for c in skill_hit} == {by_skill.id}
    assert unrelated.id not in {c["id"] for c in skill_hit}


def test_sort_by_fit_score_ascending_and_descending(client, db_session, auth_headers):
    job = _make_job(db_session)
    low = _make_candidate(db_session, email="sort-low@example.com")
    mid = _make_candidate(db_session, email="sort-mid@example.com")
    high = _make_candidate(db_session, email="sort-high@example.com")
    _score(db_session, low, job, 20.0)
    _score(db_session, mid, job, 50.0)
    _score(db_session, high, job, 80.0)

    desc = client.get(
        "/api/v1/candidates?sort_by=fit_score&sort_order=desc&page_size=100", headers=auth_headers
    ).json()["items"]
    desc_ids = [item["id"] for item in desc if item["id"] in (low.id, mid.id, high.id)]
    assert desc_ids == [high.id, mid.id, low.id]

    asc = client.get(
        "/api/v1/candidates?sort_by=fit_score&sort_order=asc&page_size=100", headers=auth_headers
    ).json()["items"]
    asc_ids = [item["id"] for item in asc if item["id"] in (low.id, mid.id, high.id)]
    assert asc_ids == [low.id, mid.id, high.id]


def test_sort_is_stable_on_ties(client, db_session, auth_headers):
    job = _make_job(db_session)
    first = _make_candidate(db_session, email="tie-1@example.com")
    second = _make_candidate(db_session, email="tie-2@example.com")
    _score(db_session, first, job, 50.0)
    _score(db_session, second, job, 50.0)

    response_1 = client.get(
        "/api/v1/candidates?sort_by=fit_score&sort_order=desc&page_size=100", headers=auth_headers
    ).json()["items"]
    response_2 = client.get(
        "/api/v1/candidates?sort_by=fit_score&sort_order=desc&page_size=100", headers=auth_headers
    ).json()["items"]
    ids_1 = [item["id"] for item in response_1 if item["id"] in (first.id, second.id)]
    ids_2 = [item["id"] for item in response_2 if item["id"] in (first.id, second.id)]
    # Deterministic (id ascending) tie-break, identical across repeated calls.
    assert ids_1 == ids_2 == [first.id, second.id]


def test_sort_fit_score_nulls_sort_last(client, db_session, auth_headers):
    job = _make_job(db_session)
    scored = _make_candidate(db_session, email="has-score@example.com")
    unscored = _make_candidate(db_session, email="no-score@example.com")
    _score(db_session, scored, job, 40.0)

    desc = client.get(
        "/api/v1/candidates?sort_by=fit_score&sort_order=desc&page_size=100", headers=auth_headers
    ).json()["items"]
    relevant = [item["id"] for item in desc if item["id"] in (scored.id, unscored.id)]
    assert relevant == [scored.id, unscored.id]


def test_job_id_filter_restricts_to_applicants(client, db_session, auth_headers):
    job = _make_job(db_session)
    other_job = _make_job(db_session, title="Other")
    applicant = _make_candidate(db_session, email="applicant@example.com")
    non_applicant = _make_candidate(db_session, email="non-applicant@example.com")
    db_session.add(Application(candidate_id=applicant.id, job_id=job.id))
    db_session.add(Application(candidate_id=non_applicant.id, job_id=other_job.id))
    db_session.commit()

    response = client.get(f"/api/v1/candidates?job_id={job.id}", headers=auth_headers)
    ids = {item["id"] for item in response.json()["items"]}
    assert ids == {applicant.id}


def test_status_filter(client, db_session, auth_headers):
    job = _make_job(db_session)
    shortlisted = _make_candidate(db_session, email="shortlisted@example.com")
    new_status = _make_candidate(db_session, email="new-status@example.com")
    db_session.add(Application(candidate_id=shortlisted.id, job_id=job.id, status=ApplicationStatus.SHORTLISTED))
    db_session.add(Application(candidate_id=new_status.id, job_id=job.id, status=ApplicationStatus.NEW))
    db_session.commit()

    response = client.get("/api/v1/candidates?status=shortlisted", headers=auth_headers)
    ids = {item["id"] for item in response.json()["items"]}
    assert shortlisted.id in ids
    assert new_status.id not in ids


def test_education_level_filter_exact_match(client, db_session, auth_headers):
    level_3 = _make_candidate(db_session, email="level3@example.com", education_level=3)
    level_1 = _make_candidate(db_session, email="level1@example.com", education_level=1)

    response = client.get("/api/v1/candidates?education_level=3", headers=auth_headers)
    ids = {item["id"] for item in response.json()["items"]}
    assert level_3.id in ids
    assert level_1.id not in ids


def test_filter_empty_result(client, db_session, auth_headers):
    _make_candidate(db_session, email="anyone@example.com")
    response = client.get("/api/v1/candidates?min_score=99.9", headers=auth_headers)
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_filter_and_pagination_together(client, db_session, auth_headers):
    for i in range(15):
        candidate = _make_candidate(db_session, email=f"page{i}@example.com", experience_years=5.0)
    response = client.get("/api/v1/candidates?min_experience=1&page=1&page_size=5", headers=auth_headers)
    body = response.json()
    assert len(body["items"]) == 5
    assert body["total"] == 15
    assert body["pages"] == 3


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
