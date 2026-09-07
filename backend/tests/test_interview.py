"""Phase 8 acceptance: interview question generation. Client mocked at the
boundary (Rules.md 6 — no test hits a live LLM provider): interview_service
tests monkeypatch interview_service.llm_client.generate; client.py's own
retry/classification logic is tested separately below with real SDK
exception instances but a monkeypatched network call, so no test ever
opens a socket.

Covers Phases.md's explicit list (valid response, malformed JSON, timeout,
ungrounded question filtered out) plus the guards, persistence, and
regeneration semantics from the same phase.
"""
import json
from pathlib import Path

import pytest

from app.config import settings
from app.core.enums import JobSeniority, ParseStatus
from app.core.exceptions import LLMError
from app.ml.extraction import field_extractor, text_cleaner, text_extractor
from app.ml.llm import client as llm_client
from app.ml.llm.client import LLMResult
from app.ml.skills import skill_matcher
from app.models.candidate import Candidate
from app.models.candidate_skill import CandidateSkill
from app.models.interview_question import InterviewQuestion
from app.models.job import Job
from app.services import interview_service

_FIXTURES_DIR = Path(__file__).parent / "fixtures"

# --- fixtures / helpers ------------------------------------------------------


def _make_job(db_session, **overrides) -> Job:
    defaults = dict(
        title="Backend Engineer",
        description="Build and maintain REST APIs using Python and FastAPI on PostgreSQL.",
        required_skills=["Python", "FastAPI", "SQL", "Kubernetes"],
        min_experience_years=2.0,
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


def _make_candidate(db_session, **overrides) -> Candidate:
    defaults = dict(
        email="c@example.com",
        resume_path="storage/x.pdf",
        resume_filename="x.pdf",
        resume_text=(
            "Jordan Lee built a real-time inventory tracker called StockWatch using "
            "Python and FastAPI, deployed on AWS. Previously maintained a Django "
            "billing service at Acme Corp."
        ),
        parse_status=ParseStatus.PARSED,
        experience_years=4.0,
        education_level=3,
        projects=["StockWatch: a real-time inventory tracker built with FastAPI and AWS"],
        certifications=["AWS Certified Developer"],
    )
    defaults.update(overrides)
    candidate = Candidate(**defaults)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _add_skills(db_session, candidate: Candidate, names: list[str]) -> None:
    for name in names:
        db_session.add(
            CandidateSkill(
                candidate_id=candidate.id, skill_name=name, skill_type="technical", source="dictionary"
            )
        )
    db_session.commit()


def _questions_json(pairs: list[tuple[str, str, str, str]]) -> str:
    """pairs: (question, category, difficulty, rationale)."""
    return json.dumps(
        {
            "questions": [
                {"question": q, "category": c, "difficulty": d, "rationale": r}
                for q, c, d, r in pairs
            ]
        }
    )


def _grounded_pairs(n: int) -> list[tuple[str, str, str, str]]:
    """n questions that all reference real candidate anchors (StockWatch,
    FastAPI, AWS — from the fixture candidate's skills/projects/certs
    above) so they all survive the grounding filter.
    """
    templates = [
        ("Walk me through how StockWatch handles concurrent inventory updates.", "project"),
        ("Why did you choose FastAPI over other frameworks for StockWatch?", "technical"),
        ("What AWS services does StockWatch run on, and why those?", "technical"),
        ("What was the hardest bug you hit building StockWatch?", "project"),
        ("How would you extend StockWatch to support a new region?", "skill_verification"),
        ("Tell me about a disagreement you had while building StockWatch.", "behavioral"),
        ("How did you test the FastAPI endpoints in StockWatch?", "technical"),
        ("What would you change about StockWatch's AWS architecture today?", "project"),
        ("How does StockWatch's Python codebase handle error cases?", "technical"),
        ("What's a StockWatch feature you're proudest of?", "behavioral"),
    ]
    return [(q, cat, "medium", "References StockWatch.") for q, cat in templates[:n]]


def _ungrounded_pairs(n: int) -> list[tuple[str, str, str, str]]:
    templates = [
        "Tell me about a time you led a team.",
        "What are your salary expectations?",
        "Why do you want to work here?",
        "Describe your ideal work environment.",
        "What is your five-year plan?",
        "How do you handle stress?",
        "What are your greatest strengths?",
        "Describe your leadership style.",
        "What motivates you at work?",
        "How do you prioritize tasks?",
    ]
    return [(q, "behavioral", "easy", "Generic.") for q in templates[:n]]


@pytest.fixture
def llm_ready(monkeypatch):
    """Gives client.generate() a configured provider/key without touching
    the real .env, and forces the anthropic path so tests are deterministic
    regardless of local LLM_PROVIDER.
    """
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-test-fake")


def _mock_generate(monkeypatch, *texts: str) -> dict:
    """Replaces interview_service's only call to the LLM. Each call pops
    the next canned text; raises if called more times than texts given, so
    a test can assert exactly how many calls happened via the returned
    counter dict.
    """
    remaining = list(texts)
    calls = {"n": 0}

    def fake(prompt: str, *, system: str) -> LLMResult:
        calls["n"] += 1
        if not remaining:
            raise AssertionError("llm_client.generate called more times than expected")
        text = remaining.pop(0)
        return LLMResult(text=text, model="claude-haiku-4-5", input_tokens=100, output_tokens=200)

    monkeypatch.setattr(interview_service.llm_client, "generate", fake)
    return calls


def _mock_generate_raises(monkeypatch, exc: Exception) -> None:
    def fake(prompt: str, *, system: str) -> LLMResult:
        raise exc

    monkeypatch.setattr(interview_service.llm_client, "generate", fake)


# --- generation: valid response, persistence, regeneration ------------------


def test_generate_valid_response_persists_grounded_questions(client, db_session, auth_headers, llm_ready, monkeypatch):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    calls = _mock_generate(monkeypatch, _questions_json(_grounded_pairs(10)))

    response = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert 5 <= len(body["questions"]) <= 8
    assert calls["n"] == 1
    assert body["requested"] == 8
    assert body["generated"] == 10
    assert body["grounded"] == 10
    assert body["partial"] is False
    for q in body["questions"]:
        assert q["category"] in {"technical", "project", "experience", "skill_verification", "behavioral"}
        assert q["difficulty"] in {"easy", "medium", "hard"}
        assert q["generation_batch"] == body["generation_batch"]

    rows = db_session.query(InterviewQuestion).filter(InterviewQuestion.candidate_id == candidate.id).all()
    assert len(rows) == len(body["questions"])


def test_second_post_without_regenerate_returns_stored_no_llm_call(
    client, db_session, auth_headers, llm_ready, monkeypatch
):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    calls = _mock_generate(monkeypatch, _questions_json(_grounded_pairs(10)))

    first = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert first.status_code == 200
    assert calls["n"] == 1

    second = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert second.status_code == 200
    assert calls["n"] == 1  # no second LLM call
    assert second.json()["generation_batch"] == first.json()["generation_batch"]
    assert second.json()["questions"] == first.json()["questions"]
    # The grounding-filter counts are persisted, not computed only at the
    # moment of generation — a cached return carries the same signal a
    # fresh one would (Phase 8 grounding-filter fix).
    for field in ("requested", "generated", "grounded", "partial"):
        assert second.json()[field] == first.json()[field]


def test_regenerate_true_replaces_stored_set(client, db_session, auth_headers, llm_ready, monkeypatch):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    calls = _mock_generate(
        monkeypatch,
        _questions_json(_grounded_pairs(10)),
        _questions_json(_grounded_pairs(6)),
    )

    first = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id, "regenerate": True},
    )
    assert second.status_code == 200
    assert calls["n"] == 2
    assert second.json()["generation_batch"] != first.json()["generation_batch"]

    rows = db_session.query(InterviewQuestion).filter(InterviewQuestion.candidate_id == candidate.id).all()
    # Replaced, not appended: only the second batch's rows remain.
    assert len(rows) == len(second.json()["questions"])
    assert all(str(row.generation_batch) == second.json()["generation_batch"] for row in rows)


def test_get_without_stored_returns_404(client, db_session, auth_headers):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)

    response = client.get(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        params={"job_id": job.id},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INTERVIEW_QUESTIONS_NOT_FOUND"


def test_get_with_stored_returns_without_llm_call(client, db_session, auth_headers, llm_ready, monkeypatch):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    calls = _mock_generate(monkeypatch, _questions_json(_grounded_pairs(10)))

    client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert calls["n"] == 1

    response = client.get(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        params={"job_id": job.id},
    )
    assert response.status_code == 200
    assert calls["n"] == 1  # GET never calls the LLM
    # GET reconstructs requested/generated/grounded/partial from the
    # persisted rows, not just POST's fresh-generation response.
    body = response.json()
    assert body["requested"] == 8
    assert body["generated"] == 10
    assert body["partial"] is False


# --- failure handling: malformed JSON, repair retry, grounding filter -------


def test_malformed_json_triggers_repair_then_succeeds(client, db_session, auth_headers, llm_ready, monkeypatch):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    calls = _mock_generate(monkeypatch, "not json at all", _questions_json(_grounded_pairs(10)))

    response = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert response.status_code == 200, response.text
    assert calls["n"] == 2  # initial + one repair call


def test_malformed_json_twice_raises_invalid_output(client, db_session, auth_headers, llm_ready, monkeypatch):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    calls = _mock_generate(monkeypatch, "still not json", "still not json either")

    response = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_INVALID_OUTPUT"
    assert calls["n"] == 2  # exactly one repair attempt, not more

    # Nothing partial reached the database.
    rows = db_session.query(InterviewQuestion).filter(InterviewQuestion.candidate_id == candidate.id).all()
    assert rows == []


def test_ungrounded_questions_filtered_out(client, db_session, auth_headers, llm_ready, monkeypatch):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    # 5 grounded + 5 ungrounded: enough grounded ones survive (>= MIN_QUESTIONS).
    mixed = _grounded_pairs(5) + _ungrounded_pairs(5)
    _mock_generate(monkeypatch, _questions_json(mixed))

    response = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    questions = [q["question"] for q in body["questions"]]
    for ungrounded_text, *_ in _ungrounded_pairs(5):
        assert ungrounded_text not in questions
    assert len(questions) == 5
    assert body["generated"] == 10
    assert body["grounded"] == 5
    assert body["partial"] is False  # 5 meets MIN_QUESTIONS exactly


def test_partial_grounded_questions_returns_200_with_partial_flag(
    client, db_session, auth_headers, llm_ready, monkeypatch
):
    """Phase 8 grounding-filter fix: 1-4 grounded questions is no longer a
    hard failure. The shorter set is returned as-is, with `partial: true`
    and the real counts, so a caller can tell "this candidate only
    yielded a few groundable questions" from a genuine full result — see
    Rules.md 5.3's INSUFFICIENT_GROUNDED_QUESTIONS entry and
    schemas/interview.py's requested/generated/grounded/partial fields.
    """
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    # Only 3 grounded out of 10 — below MIN_QUESTIONS=5 but above zero.
    mixed = _grounded_pairs(3) + _ungrounded_pairs(7)
    _mock_generate(monkeypatch, _questions_json(mixed))

    response = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["questions"]) == 3
    assert body["requested"] == 8
    assert body["generated"] == 10
    assert body["grounded"] == 3
    assert body["partial"] is True

    # Persisted, not just present on this response — a later GET sees it too.
    rows = db_session.query(InterviewQuestion).filter(InterviewQuestion.candidate_id == candidate.id).all()
    assert len(rows) == 3
    assert all(row.requested == 8 and row.generated == 10 and row.grounded == 3 for row in rows)


def test_zero_grounded_questions_raises_insufficient_grounded(
    client, db_session, auth_headers, llm_ready, monkeypatch
):
    """The genuine-zero case is the only one that still fails the call —
    and with a code distinct from LLM_INVALID_OUTPUT, since the model's
    output here is well-formed; the grounding filter is what rejected it.
    """
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    _mock_generate(monkeypatch, _questions_json(_ungrounded_pairs(10)))

    response = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "INSUFFICIENT_GROUNDED_QUESTIONS"
    assert body["error"]["details"]["generated"] == 10
    assert body["error"]["details"]["grounded"] == 0

    # Nothing partial reached the database.
    rows = db_session.query(InterviewQuestion).filter(InterviewQuestion.candidate_id == candidate.id).all()
    assert rows == []


def test_code_fence_stripped_without_using_repair_budget(client, db_session, auth_headers, llm_ready, monkeypatch):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    fenced = "```json\n" + _questions_json(_grounded_pairs(10)) + "\n```"
    calls = _mock_generate(monkeypatch, fenced)

    response = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert response.status_code == 200, response.text
    assert calls["n"] == 1  # fence stripping happened without a repair call


def test_go_skill_anchor_does_not_match_inside_algorithm(
    client, db_session, auth_headers, llm_ready, monkeypatch
):
    """Phase 8 grounding-filter fix: _is_grounded is word-boundary-safe
    (app.utils.text.compile_boundary_pattern, the same matcher
    skill_matcher.py already relies on for Phase 5), not a plain substring
    check. A candidate with skill "Go" gets the anchor "go" — a plain
    substring check would let that match inside "al-go-rithm", exactly
    the accidental-pass class this filter exists to prevent, and one that
    matters more now that resume_text-derived anchors (this same fix
    session) make anchors the entire mechanism standing between "generic"
    and "grounded" for resumes that used to have almost none.
    """
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI", "Go"])
    mixed = _grounded_pairs(5) + [
        ("What's your favorite algorithm for solving graph traversal problems?", "technical", "medium", "Generic."),
        ("How do you approach algorithm design in general?", "technical", "medium", "Generic."),
        ("What are your greatest strengths?", "behavioral", "easy", "Generic."),
        ("Why do you want to work here?", "behavioral", "easy", "Generic."),
        ("Describe your ideal work environment.", "behavioral", "easy", "Generic."),
    ]
    _mock_generate(monkeypatch, _questions_json(mixed))

    response = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    questions = [q["question"] for q in body["questions"]]
    assert "What's your favorite algorithm for solving graph traversal problems?" not in questions
    assert "How do you approach algorithm design in general?" not in questions
    assert body["grounded"] == 5


def test_real_resume_without_projects_section_grounds_via_experience(
    client, db_session, auth_headers, llm_ready, monkeypatch
):
    """The test that would have caught the original bug: real_eval_set's
    resume_001.pdf (Aaron Whitfield) run through the actual extraction
    pipeline, not the hand-authored StockWatch fixture. Real resumes with
    no distinct Projects/Certifications heading — this one included — used
    to leave the grounding filter with only bare skill names as anchors,
    which is what made the production endpoint return 503 on 7 of 7 real
    attempts (docs/EVALUATION.md's Phase 8 section). Asserted explicitly:
    projects/certifications really are empty for this real resume, so this
    test cannot silently start passing again for the wrong reason if
    someone later gives this fixture a Projects section.
    """
    content = (_FIXTURES_DIR / "real_eval_set" / "resume_001.pdf").read_bytes()
    raw = text_extractor.extract_text(content, ".pdf")
    resume_text = text_cleaner.clean_text(raw)
    fields = field_extractor.extract_all(resume_text)
    assert fields.projects == []
    assert fields.certifications == []

    job = _make_job(
        db_session,
        title="Backend Software Engineer",
        required_skills=["Python", "SQL", "AWS", "PostgreSQL", "Kubernetes"],
        min_experience_years=3.0,
    )
    candidate = _make_candidate(
        db_session,
        email="aaron.whitfield@example.com",
        resume_path="storage/resume_001.pdf",
        resume_filename="resume_001.pdf",
        resume_text=resume_text,
        experience_years=fields.experience_years,
        education_level=fields.education_level,
        projects=fields.projects,
        certifications=fields.certifications,
    )
    for match in skill_matcher.match_skills(resume_text):
        db_session.add(
            CandidateSkill(
                candidate_id=candidate.id,
                skill_name=match.canonical,
                skill_type=match.skill_type,
                source=match.source,
            )
        )
    db_session.commit()

    # Modeled on the real diagnostic transcript in docs/EVALUATION.md's
    # Phase 8 section — questions naming "Corvid Labs"/"Meridian Systems"
    # (real employers from resume_001's Experience bullets) and "p99" (a
    # real metric named in a bullet) had no anchor to pass on before this
    # fix; bare-skill-name questions already passed and still do.
    mixed = [
        (
            "Can you walk me through the p99 checkout latency reduction you achieved at Corvid Labs?",
            "technical", "hard", "References a real metric and employer.",
        ),
        (
            "What made the job-scheduling platform you built at Meridian Systems challenging to maintain?",
            "project", "medium", "References a real employer.",
        ),
        (
            "Tell me about the contract testing work you introduced at Corvid Labs.",
            "behavioral", "medium", "References a real employer.",
        ),
        (
            "How did the ingestion layer you wrote at Meridian Systems handle partner data reliability?",
            "technical", "hard", "References a real employer.",
        ),
        (
            "What Terraform experience do you have migrating Kubernetes workloads to AWS?",
            "skill_verification", "easy", "References real skills.",
        ),
        (
            "How have you used Python and Go together, and where does gRPC fit in your architecture?",
            "technical", "easy", "References real skills.",
        ),
        ("Tell me about a time you led a team.", "behavioral", "easy", "Generic."),
        ("What are your salary expectations?", "behavioral", "easy", "Generic."),
        ("Why do you want to work here?", "behavioral", "easy", "Generic."),
        ("Describe your ideal work environment.", "behavioral", "easy", "Generic."),
    ]
    _mock_generate(monkeypatch, _questions_json(mixed))

    response = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    questions = [q["question"] for q in body["questions"]]
    assert "Can you walk me through the p99 checkout latency reduction you achieved at Corvid Labs?" in questions
    assert (
        "What made the job-scheduling platform you built at Meridian Systems challenging to maintain?"
        in questions
    )
    assert "Tell me about the contract testing work you introduced at Corvid Labs." in questions
    assert "Tell me about a time you led a team." not in questions
    assert "What are your salary expectations?" not in questions
    assert body["generated"] == 10
    assert body["grounded"] == 6
    assert body["partial"] is False


# --- provider failures --------------------------------------------------


def test_timeout_returns_503_llm_timeout(client, db_session, auth_headers, llm_ready, monkeypatch):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    _mock_generate_raises(monkeypatch, LLMError("timed out", code="LLM_TIMEOUT"))

    response = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_TIMEOUT"


def test_provider_unavailable_returns_503_llm_unavailable(client, db_session, auth_headers, monkeypatch):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    # Phases.md acceptance: "with the provider key removed" — leave
    # ANTHROPIC_API_KEY empty (no llm_ready fixture) so the real client
    # code path (not a mock) raises this itself.
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")

    response = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_UNAVAILABLE"


# --- guards, before any LLM call ----------------------------------------


def test_job_has_no_skills_guard(client, db_session, auth_headers, llm_ready, monkeypatch):
    job = _make_job(db_session, required_skills=[])
    candidate = _make_candidate(db_session)
    calls = _mock_generate(monkeypatch, _questions_json(_grounded_pairs(10)))

    response = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "JOB_HAS_NO_SKILLS"
    assert calls["n"] == 0  # never spent a call on an unusable request


def test_resume_text_too_short_guard(client, db_session, auth_headers, llm_ready, monkeypatch):
    job = _make_job(db_session)
    candidate = _make_candidate(
        db_session, parse_status=ParseStatus.PARSE_FAILED, resume_text="", parse_error="scanned image"
    )
    calls = _mock_generate(monkeypatch, _questions_json(_grounded_pairs(10)))

    response = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "RESUME_TEXT_TOO_SHORT"
    assert calls["n"] == 0


def test_requires_auth(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    response = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions", json={"job_id": job.id}
    )
    assert response.status_code == 401


# --- Phase 15: per-user rate limit on generation ----------------------------
#
# The limiter (app/core/rate_limit.py) is a module-level singleton reset by
# conftest.py's autouse _reset_interview_rate_limiter fixture before/after
# every test, so these tests can freely monkeypatch its max_requests down to
# a small number without waiting for a real clock hour or affecting any
# other test in the suite.


def test_rate_limit_allows_requests_within_configured_limit(
    client, db_session, auth_headers, llm_ready, monkeypatch
):
    from app import dependencies

    monkeypatch.setattr(dependencies.interview_question_rate_limiter, "max_requests", 3)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    _mock_generate(monkeypatch, _questions_json(_grounded_pairs(10)))

    # First call generates; the next two are cache hits (regenerate not
    # set) — all three still count against the limit, since it gates the
    # endpoint itself, not just the LLM call inside it.
    for _ in range(3):
        response = client.post(
            f"/api/v1/candidates/{candidate.id}/interview-questions",
            headers=auth_headers,
            json={"job_id": job.id},
        )
        assert response.status_code == 200, response.text


def test_rate_limit_rejects_request_exceeding_limit_with_clean_envelope(
    client, db_session, auth_headers, llm_ready, monkeypatch
):
    from app import dependencies

    monkeypatch.setattr(dependencies.interview_question_rate_limiter, "max_requests", 2)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    _mock_generate(monkeypatch, _questions_json(_grounded_pairs(10)))

    for _ in range(2):
        response = client.post(
            f"/api/v1/candidates/{candidate.id}/interview-questions",
            headers=auth_headers,
            json={"job_id": job.id},
        )
        assert response.status_code == 200

    third = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert third.status_code == 429
    body = third.json()
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert "retry_after_seconds" in body["error"]["details"]
    assert body["error"]["details"]["retry_after_seconds"] > 0
    # Same envelope shape as every other error (Architecture.md 6.1) —
    # no internals, no stack trace, nothing beyond code/message/details.
    assert set(body["error"].keys()) == {"code", "message", "details"}


def test_rate_limit_is_isolated_per_user_and_does_not_block_a_different_user(
    client, db_session, auth_headers, llm_ready, monkeypatch
):
    from app import dependencies

    monkeypatch.setattr(dependencies.interview_question_rate_limiter, "max_requests", 1)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    _mock_generate(monkeypatch, _questions_json(_grounded_pairs(10)))

    first_user_first_call = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert first_user_first_call.status_code == 200

    first_user_second_call = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )
    assert first_user_second_call.status_code == 429

    client.post(
        "/api/v1/auth/register",
        json={"name": "Second Recruiter", "email": "second@example.com", "password": "correct-horse-battery"},
    )
    login = client.post(
        "/api/v1/auth/login", json={"email": "second@example.com", "password": "correct-horse-battery"}
    )
    second_user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    call_from_different_user = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=second_user_headers,
        json={"job_id": job.id},
    )
    # This candidate/job already has a stored set (from the first user's
    # call above) and regenerate isn't set, so this is a cache hit — the
    # point being proven is that a different user id is a fresh limiter
    # key, not blocked by the first user's exhausted quota.
    assert call_from_different_user.status_code == 200


def test_rate_limit_does_not_apply_to_get(client, db_session, auth_headers, llm_ready, monkeypatch):
    """GET never calls the LLM (Architecture.md 7.3) and isn't
    'generation' — only the POST route carries the rate-limit dependency.
    """
    from app import dependencies

    monkeypatch.setattr(dependencies.interview_question_rate_limiter, "max_requests", 1)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    _mock_generate(monkeypatch, _questions_json(_grounded_pairs(10)))

    client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions",
        headers=auth_headers,
        json={"job_id": job.id},
    )

    for _ in range(5):
        response = client.get(
            f"/api/v1/candidates/{candidate.id}/interview-questions",
            headers=auth_headers,
            params={"job_id": job.id},
        )
        assert response.status_code == 200


def test_rate_limit_requires_auth_before_counting(client, db_session):
    """An unauthenticated request must fail at the auth dependency
    (401 TOKEN_MISSING), not be counted against — or rejected by — the
    rate limiter, which only ever runs for an already-authenticated user.
    """
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    response = client.post(
        f"/api/v1/candidates/{candidate.id}/interview-questions", json={"job_id": job.id}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_MISSING"


# --- client.py: retry and error classification, real SDK exceptions --------


def _anthropic_timeout():
    import anthropic
    import httpx

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APITimeoutError(request=request)


def _anthropic_status(status_code: int):
    import anthropic
    import httpx

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code, request=request, json={"error": {"message": "boom"}})
    if status_code == 429:
        return anthropic.RateLimitError("rate limited", response=response, body={})
    return anthropic.APIStatusError("boom", response=response, body={})


def test_client_retries_once_on_timeout_then_succeeds(llm_ready, monkeypatch):
    success = LLMResult(text="ok", model="claude-haiku-4-5", input_tokens=1, output_tokens=1)
    calls = {"n": 0}

    def fake_call(prompt, system):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _anthropic_timeout()
        return success

    monkeypatch.setattr(llm_client, "_call_anthropic", fake_call)
    result = llm_client.generate("p", system="s")
    assert result is success
    assert calls["n"] == 2


def test_client_timeout_twice_raises_llm_timeout(llm_ready, monkeypatch):
    calls = {"n": 0}

    def fake_call(prompt, system):
        calls["n"] += 1
        raise _anthropic_timeout()

    monkeypatch.setattr(llm_client, "_call_anthropic", fake_call)
    with pytest.raises(LLMError) as exc_info:
        llm_client.generate("p", system="s")
    assert exc_info.value.code == "LLM_TIMEOUT"
    assert calls["n"] == 2


def test_client_retries_once_on_server_error_then_succeeds(llm_ready, monkeypatch):
    success = LLMResult(text="ok", model="claude-haiku-4-5", input_tokens=1, output_tokens=1)
    calls = {"n": 0}

    def fake_call(prompt, system):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _anthropic_status(500)
        return success

    monkeypatch.setattr(llm_client, "_call_anthropic", fake_call)
    result = llm_client.generate("p", system="s")
    assert result is success
    assert calls["n"] == 2


def test_client_rate_limit_twice_raises_llm_unavailable(llm_ready, monkeypatch):
    calls = {"n": 0}

    def fake_call(prompt, system):
        calls["n"] += 1
        raise _anthropic_status(429)

    monkeypatch.setattr(llm_client, "_call_anthropic", fake_call)
    with pytest.raises(LLMError) as exc_info:
        llm_client.generate("p", system="s")
    assert exc_info.value.code == "LLM_UNAVAILABLE"
    assert calls["n"] == 2


def test_client_bad_request_fails_immediately_no_retry(llm_ready, monkeypatch):
    calls = {"n": 0}

    def fake_call(prompt, system):
        calls["n"] += 1
        raise _anthropic_status(400)

    monkeypatch.setattr(llm_client, "_call_anthropic", fake_call)
    with pytest.raises(LLMError) as exc_info:
        llm_client.generate("p", system="s")
    assert exc_info.value.code == "LLM_UNAVAILABLE"
    assert calls["n"] == 1  # non-retryable: no second attempt


def test_client_no_api_key_fails_immediately_no_call(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    calls = {"n": 0}

    def fake_call(prompt, system):
        calls["n"] += 1
        raise AssertionError("should never be called with no API key")

    monkeypatch.setattr(llm_client, "_call_anthropic", fake_call)
    with pytest.raises(LLMError) as exc_info:
        llm_client.generate("p", system="s")
    assert exc_info.value.code == "LLM_UNAVAILABLE"
    assert calls["n"] == 0


# --- client.py: the openai provider path (Phase 15) -------------------------
#
# LLM_PROVIDER=openai is the shipped default (.env.example, targeting Groq
# via OPENAI_BASE_URL) — every test above forces the anthropic path via
# llm_ready for determinism, which left generate()'s provider-selection
# branch (client.py: "if settings.LLM_PROVIDER == 'openai': ... call =
# _call_openai") and its retry/classification loop completely unexercised
# against the actual default. That logic is provider-generic (same
# sdk.APITimeoutError/RateLimitError/APIConnectionError/APIStatusError
# pattern, aliased per provider), so these mirror the anthropic tests above
# exactly, with real openai SDK exception types and a monkeypatched network
# call — no real request ever leaves the process, same as every other LLM
# test in this file (Rules.md 6).


@pytest.fixture
def openai_ready(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-fake")


def _openai_timeout():
    import httpx
    import openai

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return openai.APITimeoutError(request=request)


def _openai_status(status_code: int):
    import httpx
    import openai

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request, json={"error": {"message": "boom"}})
    if status_code == 429:
        return openai.RateLimitError("rate limited", response=response, body={})
    return openai.APIStatusError("boom", response=response, body={})


def test_client_openai_path_selected_and_retries_once_on_timeout_then_succeeds(
    openai_ready, monkeypatch
):
    success = LLMResult(text="ok", model="gpt-4o-mini", input_tokens=1, output_tokens=1)
    calls = {"n": 0}

    def fake_call(prompt, system):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _openai_timeout()
        return success

    monkeypatch.setattr(llm_client, "_call_openai", fake_call)
    result = llm_client.generate("p", system="s")
    assert result is success
    assert calls["n"] == 2


def test_client_openai_rate_limit_twice_raises_llm_unavailable(openai_ready, monkeypatch):
    calls = {"n": 0}

    def fake_call(prompt, system):
        calls["n"] += 1
        raise _openai_status(429)

    monkeypatch.setattr(llm_client, "_call_openai", fake_call)
    with pytest.raises(LLMError) as exc_info:
        llm_client.generate("p", system="s")
    assert exc_info.value.code == "LLM_UNAVAILABLE"
    assert calls["n"] == 2


def test_client_openai_bad_request_fails_immediately_no_retry(openai_ready, monkeypatch):
    calls = {"n": 0}

    def fake_call(prompt, system):
        calls["n"] += 1
        raise _openai_status(400)

    monkeypatch.setattr(llm_client, "_call_openai", fake_call)
    with pytest.raises(LLMError) as exc_info:
        llm_client.generate("p", system="s")
    assert exc_info.value.code == "LLM_UNAVAILABLE"
    assert calls["n"] == 1  # non-retryable: no second attempt


def test_client_openai_no_api_key_fails_immediately_no_call(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    calls = {"n": 0}

    def fake_call(prompt, system):
        calls["n"] += 1
        raise AssertionError("should never be called with no API key")

    monkeypatch.setattr(llm_client, "_call_openai", fake_call)
    with pytest.raises(LLMError) as exc_info:
        llm_client.generate("p", system="s")
    assert exc_info.value.code == "LLM_UNAVAILABLE"
    assert calls["n"] == 0


def test_call_openai_builds_llmresult_from_response(openai_ready, monkeypatch):
    """_call_openai itself (client.py:96-111) — the actual response-to-
    LLMResult mapping — has never run under any test, since every test
    above stubs it out entirely. Substituting _get_openai_client (rather
    than calling through its @lru_cache) with a plain fake client keeps
    this deterministic and avoids cross-test cache pollution from the
    real cached singleton.
    """

    class _FakeMessage:
        content = "hello from openai"

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeUsage:
        prompt_tokens = 42
        completion_tokens = 17

    class _FakeResponse:
        choices = [_FakeChoice()]
        model = "gpt-4o-mini"
        usage = _FakeUsage()

    class _FakeCompletions:
        def create(self, **kwargs):
            return _FakeResponse()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr(llm_client, "_get_openai_client", lambda: _FakeClient())

    result = llm_client._call_openai("prompt text", "system text")
    assert result.text == "hello from openai"
    assert result.model == "gpt-4o-mini"
    assert result.input_tokens == 42
    assert result.output_tokens == 17
