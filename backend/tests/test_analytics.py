"""Phase 12 analytics acceptance: the four /analytics/* endpoints, job_id
and date-range filtering, and manual-SQL equivalence for every number
returned (Phases.md Phase 12: "every analytics number is verifiable
against a manual database query").
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, text

from app.core.enums import ApplicationStatus, JobSeniority, ParseStatus, RiskLevel, ScoringMethod, SkillSource, SkillType
from app.models.application import Application
from app.models.attrition_prediction import AttritionPrediction
from app.models.candidate import Candidate
from app.models.candidate_score import CandidateScore
from app.models.candidate_skill import CandidateSkill
from app.models.employee import Employee
from app.models.job import Job


def _make_job(db_session, **overrides) -> Job:
    defaults = dict(
        title="Backend Engineer",
        description="Build APIs with Python and FastAPI.",
        required_skills=["Python", "FastAPI"],
        min_experience_years=1.0,
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
    )
    defaults.update(overrides)
    candidate = Candidate(**defaults)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _apply(db_session, candidate: Candidate, job: Job, status=ApplicationStatus.NEW) -> Application:
    application = Application(candidate_id=candidate.id, job_id=job.id, status=status)
    db_session.add(application)
    db_session.commit()
    return application


def _make_score(db_session, candidate: Candidate, job: Job, *, final_fit_score: float, missing_skills=None, **overrides) -> CandidateScore:
    defaults = dict(
        resume_match_score=final_fit_score,
        skill_match_score=final_fit_score,
        experience_score=final_fit_score,
        education_score=100.0,
        final_fit_score=final_fit_score,
        matched_skills=[],
        missing_skills=missing_skills or [],
        scoring_method=ScoringMethod.TFIDF,
    )
    defaults.update(overrides)
    score = CandidateScore(candidate_id=candidate.id, job_id=job.id, **defaults)
    db_session.add(score)
    db_session.commit()
    return score


def _make_skill(db_session, candidate: Candidate, skill_name: str) -> None:
    db_session.add(
        CandidateSkill(
            candidate_id=candidate.id, skill_name=skill_name, skill_type=SkillType.TECHNICAL, source=SkillSource.DICTIONARY
        )
    )
    db_session.commit()


def _make_employee(db_session, *, department: str, **overrides) -> Employee:
    defaults = dict(
        age=30,
        job_level=2,
        monthly_income=5000.0,
        years_at_company=4,
        years_since_last_promotion=1,
        years_with_curr_manager=2,
        total_working_years=8,
        job_satisfaction=3,
        environment_satisfaction=3,
        relationship_satisfaction=3,
        performance_rating=3,
        overtime=False,
        business_travel="Travel_Rarely",
        distance_from_home=5,
        percent_salary_hike=12.0,
        stock_option_level=1,
    )
    defaults.update(overrides)
    employee = Employee(department=department, **defaults)
    db_session.add(employee)
    db_session.commit()
    db_session.refresh(employee)
    return employee


def _make_prediction(db_session, employee: Employee, *, probability: float, risk_level: RiskLevel, **overrides) -> AttritionPrediction:
    defaults = dict(
        top_factors=[],
        model_version="test",
        prediction_date=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    prediction = AttritionPrediction(
        employee_id=employee.id, probability=probability, risk_level=risk_level, **defaults
    )
    db_session.add(prediction)
    db_session.commit()
    return prediction


# --- overview -----------------------------------------------------------------


def test_overview_funnel_counts_by_status(client, db_session, auth_headers):
    job = _make_job(db_session)
    statuses = [
        ApplicationStatus.NEW,
        ApplicationStatus.NEW,
        ApplicationStatus.SHORTLISTED,
        ApplicationStatus.INTERVIEWED,
        ApplicationStatus.SELECTED,
        ApplicationStatus.REJECTED,
    ]
    for i, status in enumerate(statuses):
        candidate = _make_candidate(db_session, f"c{i}@example.com")
        _apply(db_session, candidate, job, status=status)

    response = client.get(f"/api/v1/analytics/overview?job_id={job.id}", headers=auth_headers)
    assert response.status_code == 200
    funnel = response.json()["funnel"]
    assert funnel == {"total": 6, "new": 2, "shortlisted": 1, "interviewed": 1, "selected": 1, "rejected": 1}

    # Manual SQL, independent of the ORM query the service builds.
    manual = dict(
        db_session.execute(
            text("SELECT status, COUNT(*) FROM applications WHERE job_id = :job_id GROUP BY status"),
            {"job_id": job.id},
        ).all()
    )
    assert manual == {"new": 2, "shortlisted": 1, "interviewed": 1, "selected": 1, "rejected": 1}


def test_overview_job_id_filter_excludes_other_jobs(client, db_session, auth_headers):
    job_a = _make_job(db_session, title="Job A")
    job_b = _make_job(db_session, title="Job B")
    for job in (job_a, job_a, job_b):
        candidate = _make_candidate(db_session, f"c{id(job)}{job.id}@example.com")
        _apply(db_session, candidate, job)

    response = client.get(f"/api/v1/analytics/overview?job_id={job_a.id}", headers=auth_headers)
    assert response.json()["funnel"]["total"] == 2


def test_overview_date_range_filter(client, db_session, auth_headers):
    job = _make_job(db_session)
    old_candidate = _make_candidate(db_session, "old@example.com")
    application = _apply(db_session, old_candidate, job)
    application.created_at = datetime.now(timezone.utc) - timedelta(days=30)
    db_session.commit()

    recent_candidate = _make_candidate(db_session, "recent@example.com")
    _apply(db_session, recent_candidate, job)

    date_from = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    response = client.get(
        f"/api/v1/analytics/overview?job_id={job.id}&from={date_from}", headers=auth_headers
    )
    assert response.json()["funnel"]["total"] == 1


def test_analytics_invalid_date_range_rejected(client, auth_headers):
    response = client.get("/api/v1/analytics/overview?from=2026-06-01&to=2026-01-01", headers=auth_headers)
    assert response.status_code == 400


def test_overview_without_token_returns_401(client):
    response = client.get("/api/v1/analytics/overview")
    assert response.status_code == 401


# --- skills ---------------------------------------------------------------------


def test_skills_top_candidate_and_missing_skills(client, db_session, auth_headers):
    job = _make_job(db_session)
    for i in range(3):
        candidate = _make_candidate(db_session, f"skill{i}@example.com")
        _apply(db_session, candidate, job)
        _make_skill(db_session, candidate, "Python")
        if i < 2:
            _make_skill(db_session, candidate, "SQL")
        _make_score(db_session, candidate, job, final_fit_score=70.0, missing_skills=["FastAPI"] if i < 2 else [])

    response = client.get(f"/api/v1/analytics/skills?job_id={job.id}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["top_candidate_skills"][0] == {"skill_name": "Python", "count": 3}
    assert {"skill_name": "SQL", "count": 2} in body["top_candidate_skills"]
    assert body["top_missing_skills"] == [{"skill_name": "FastAPI", "count": 2}]

    manual_candidate_skills = dict(
        db_session.execute(
            text(
                "SELECT cs.skill_name, COUNT(*) FROM candidate_skills cs "
                "JOIN candidates c ON c.id = cs.candidate_id "
                "JOIN applications a ON a.candidate_id = c.id "
                "WHERE a.job_id = :job_id GROUP BY cs.skill_name"
            ),
            {"job_id": job.id},
        ).all()
    )
    assert manual_candidate_skills == {"Python": 3, "SQL": 2}

    manual_missing = dict(
        db_session.execute(
            text(
                "SELECT je.value, COUNT(*) FROM candidate_scores, json_each(candidate_scores.missing_skills) je "
                "WHERE candidate_scores.job_id = :job_id GROUP BY je.value"
            ),
            {"job_id": job.id},
        ).all()
    )
    assert manual_missing == {"FastAPI": 2}


def test_skills_without_job_id_covers_all_jobs(client, db_session, auth_headers):
    job_a = _make_job(db_session, title="A")
    job_b = _make_job(db_session, title="B")
    candidate_a = _make_candidate(db_session, "a@example.com")
    candidate_b = _make_candidate(db_session, "b@example.com")
    _apply(db_session, candidate_a, job_a)
    _apply(db_session, candidate_b, job_b)
    _make_skill(db_session, candidate_a, "Python")
    _make_skill(db_session, candidate_b, "Python")

    response = client.get("/api/v1/analytics/skills", headers=auth_headers)
    assert response.json()["top_candidate_skills"] == [{"skill_name": "Python", "count": 2}]


# --- scores -----------------------------------------------------------------------


def test_scores_average_and_distribution(client, db_session, auth_headers):
    job = _make_job(db_session)
    fit_scores = [15.0, 25.0, 65.0, 68.0, 95.0]
    for i, score_value in enumerate(fit_scores):
        candidate = _make_candidate(db_session, f"score{i}@example.com")
        _apply(db_session, candidate, job)
        _make_score(db_session, candidate, job, final_fit_score=score_value)

    response = client.get(f"/api/v1/analytics/scores?job_id={job.id}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["overall_average_fit_score"] == round(sum(fit_scores) / len(fit_scores), 1)
    assert body["average_by_job"] == [
        {"job_id": job.id, "job_title": job.title, "average_fit_score": round(sum(fit_scores) / len(fit_scores), 1), "candidate_count": 5}
    ]
    counts_by_bucket = {b["range_start"]: b["count"] for b in body["distribution"]}
    assert counts_by_bucket[10.0] == 1  # 15
    assert counts_by_bucket[20.0] == 1  # 25
    assert counts_by_bucket[60.0] == 2  # 65, 68
    assert counts_by_bucket[90.0] == 1  # 95
    assert sum(counts_by_bucket.values()) == 5

    manual_avg = db_session.execute(
        text("SELECT AVG(final_fit_score) FROM candidate_scores WHERE job_id = :job_id"), {"job_id": job.id}
    ).scalar()
    assert round(manual_avg, 1) == body["overall_average_fit_score"]


def test_scores_bucket_100_falls_in_last_bucket(client, db_session, auth_headers):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, "perfect@example.com")
    _apply(db_session, candidate, job)
    _make_score(db_session, candidate, job, final_fit_score=100.0)

    response = client.get(f"/api/v1/analytics/scores?job_id={job.id}", headers=auth_headers)
    counts_by_bucket = {b["range_start"]: b["count"] for b in response.json()["distribution"]}
    assert counts_by_bucket[90.0] == 1


def test_scores_no_data_returns_null_average_not_zero(client, db_session, auth_headers):
    job = _make_job(db_session)
    response = client.get(f"/api/v1/analytics/scores?job_id={job.id}", headers=auth_headers)
    body = response.json()
    assert body["overall_average_fit_score"] is None
    assert body["average_by_job"] == []
    assert all(bucket["count"] == 0 for bucket in body["distribution"])


# --- attrition ----------------------------------------------------------------------


def test_attrition_by_risk_level_and_department(client, db_session, auth_headers):
    sales_1 = _make_employee(db_session, department="Sales")
    sales_2 = _make_employee(db_session, department="Sales")
    rd_1 = _make_employee(db_session, department="Research & Development")
    _make_prediction(db_session, sales_1, probability=0.10, risk_level=RiskLevel.LOW)
    _make_prediction(db_session, sales_2, probability=0.50, risk_level=RiskLevel.MEDIUM)
    _make_prediction(db_session, rd_1, probability=0.90, risk_level=RiskLevel.HIGH)

    response = client.get("/api/v1/analytics/attrition", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total_employees_with_prediction"] == 3
    counts = {row["risk_level"]: row["count"] for row in body["by_risk_level"]}
    assert counts == {"low": 1, "medium": 1, "high": 1}
    by_dept = {row["department"]: row for row in body["by_department"]}
    assert by_dept["Sales"]["average_probability"] == round((0.10 + 0.50) / 2, 4)
    assert by_dept["Sales"]["employee_count"] == 2
    assert by_dept["Research & Development"]["average_probability"] == 0.9

    manual_counts = dict(
        db_session.execute(text("SELECT risk_level, COUNT(*) FROM attrition_predictions GROUP BY risk_level")).all()
    )
    assert manual_counts == {"low": 1, "medium": 1, "high": 1}


def test_attrition_uses_latest_prediction_per_employee_only(client, db_session, auth_headers):
    employee = _make_employee(db_session, department="Sales")
    _make_prediction(
        db_session, employee, probability=0.05, risk_level=RiskLevel.LOW,
        prediction_date=datetime.now(timezone.utc) - timedelta(days=5),
    )
    _make_prediction(db_session, employee, probability=0.95, risk_level=RiskLevel.HIGH)

    response = client.get("/api/v1/analytics/attrition", headers=auth_headers)
    body = response.json()
    assert body["total_employees_with_prediction"] == 1
    counts = {row["risk_level"]: row["count"] for row in body["by_risk_level"]}
    assert counts == {"low": 0, "medium": 0, "high": 1}


def test_attrition_job_id_has_no_matching_relationship_and_is_reported(client, db_session, auth_headers):
    """Employees carry no job_id anywhere in the schema (Architecture.md
    5.1) — job_id is accepted for contract consistency but documented as
    a no-op here, never a silent one. See Memory.md.
    """
    employee = _make_employee(db_session, department="Sales")
    _make_prediction(db_session, employee, probability=0.5, risk_level=RiskLevel.MEDIUM)
    job = _make_job(db_session)

    without_filter = client.get("/api/v1/analytics/attrition", headers=auth_headers).json()
    with_filter = client.get(f"/api/v1/analytics/attrition?job_id={job.id}", headers=auth_headers).json()

    assert without_filter["job_id_filter_applied"] is False
    assert with_filter["job_id_filter_applied"] is True
    assert with_filter["total_employees_with_prediction"] == without_filter["total_employees_with_prediction"] == 1


def test_attrition_date_range_filter(client, db_session, auth_headers):
    employee = _make_employee(db_session, department="Sales")
    _make_prediction(
        db_session, employee, probability=0.5, risk_level=RiskLevel.MEDIUM,
        prediction_date=datetime.now(timezone.utc) - timedelta(days=30),
    )
    date_from = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    response = client.get(f"/api/v1/analytics/attrition?from={date_from}", headers=auth_headers)
    assert response.json()["total_employees_with_prediction"] == 0
