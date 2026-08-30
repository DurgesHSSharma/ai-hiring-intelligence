"""Phase 6/7 acceptance: TF-IDF and embedding ranking, the four sub-scores
and their edge cases, the weighted composite (including the
hand-calculated worked example), guards (JOB_HAS_NO_SKILLS, unusable
resume text, division by zero), staleness/versioning, the embedding
cache and its cross-job reuse, semantic skill-match fallback (opt-in,
F4.4), graceful degradation when the embedding model is unavailable, and
the scoring endpoints.
"""
import hashlib
from functools import lru_cache

import numpy as np
import pytest

from app.config import settings
from app.core.enums import JobSeniority, ParseStatus, ScoreBand, ScoringMethod, SkillSource
from app.core.exceptions import ModelUnavailableError
from app.ml.ranking import embedding_ranker
from app.ml.ranking.embedding_ranker import EmbeddingRanker
from app.ml.ranking.factory import get_ranker
from app.ml.ranking.tfidf_ranker import TFIDFRanker
from app.ml.skills import skill_gap
from app.ml.skills.skill_gap import SkillGapMatch, apply_semantic_fallback, compute_skill_gap
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.candidate_score import CandidateScore
from app.models.candidate_skill import CandidateSkill
from app.models.job import Job
from app.services.scoring_service import (
    _compose_final_score,
    _compute_band,
    _education_score,
    _experience_score,
)

# --- fixtures / helpers -------------------------------------------------------


def _make_job(db_session, **overrides) -> Job:
    defaults = dict(
        title="Backend Engineer",
        description="Build and maintain REST APIs using Python and FastAPI on PostgreSQL.",
        required_skills=["Python", "FastAPI", "SQL"],
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


def _make_candidate(db_session, email: str = "c@example.com", **overrides) -> Candidate:
    defaults = dict(
        email=email,
        resume_path="storage/x.pdf",
        resume_filename="x.pdf",
        resume_text="Experienced Python developer who has built REST APIs with FastAPI.",
        parse_status=ParseStatus.PARSED,
        experience_years=4.0,
        education_level=3,
    )
    defaults.update(overrides)
    candidate = Candidate(**defaults)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _apply(db_session, candidate: Candidate, job: Job) -> Application:
    application = Application(candidate_id=candidate.id, job_id=job.id)
    db_session.add(application)
    db_session.commit()
    return application


def _add_skills(db_session, candidate: Candidate, names: list[str]) -> None:
    for name in names:
        db_session.add(CandidateSkill(candidate_id=candidate.id, skill_name=name, skill_type="technical", source="dictionary"))
    db_session.commit()


def _expected_band(score: float) -> str:
    if score >= 85:
        return "strong_match"
    if score >= 70:
        return "good_match"
    if score >= 55:
        return "moderate_match"
    return "weak_match"


# --- test double for the embedding model -----------------------------------
#
# Same boundary-mocking philosophy Rules.md 6 already applies to the LLM
# client ("no test hits a live provider") — no test in this suite downloads
# the real ~90MB model. _FakeEmbeddingModel hashes each word into one of a
# fixed number of buckets and counts occurrences, so cosine similarity
# behaves sensibly for assertions (identical text -> 1.0, disjoint
# vocabulary -> near 0) without any real semantics, and every call is
# tracked for the "batched, not per-candidate" / "reused, not re-encoded"
# assertions below. embedding_ranker._get_model is a module-level function,
# so patching the module attribute (not the class) is what makes every
# EmbeddingRanker instance created during a test pick up the fake.


class _FakeEmbeddingModel:
    _DIM = 64

    def __init__(self) -> None:
        self.encode_call_count = 0
        self.encoded_texts: list[str] = []

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._DIM
        for word in text.lower().split():
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % self._DIM
            vector[bucket] += 1.0
        return vector

    def encode(self, texts):
        self.encode_call_count += 1
        if isinstance(texts, str):
            self.encoded_texts.append(texts)
            return np.array(self._vector(texts))
        text_list = list(texts)
        self.encoded_texts.extend(text_list)
        return np.array([self._vector(t) for t in text_list])


@pytest.fixture
def fake_model(monkeypatch):
    model = _FakeEmbeddingModel()
    monkeypatch.setattr(embedding_ranker, "_get_model", lambda: model)
    return model


@pytest.fixture
def unavailable_model(monkeypatch):
    """Every call to _get_model() raises exactly what the real translation
    logic in embedding_ranker.py raises on a genuine load failure.
    """

    def _raise():
        raise ModelUnavailableError(
            "Embedding model unavailable in test.", code="EMBEDDING_MODEL_UNAVAILABLE"
        )

    monkeypatch.setattr(embedding_ranker, "_get_model", _raise)


# --- unit: weighted composition (F7.1) ----------------------------------------


def test_compose_final_score_worked_example():
    # The exact worked example from Rules.md 6 / Phases.md Phase 6, with
    # the default weights (0.40/0.35/0.15/0.10 in backend/.env).
    assert _compose_final_score(85.0, 90.0, 80.0, 100.0) == 87.5


def test_compose_final_score_excludes_none_experience_and_renormalizes():
    # Weight 0.15 dropped; remaining 0.40/0.35/0.10 renormalized over 0.85.
    result = _compose_final_score(80.0, 80.0, None, 100.0)
    expected = round((0.40 * 80.0 + 0.35 * 80.0 + 0.10 * 100.0) / 0.85, 1)
    assert result == expected


def test_compose_final_score_excludes_none_education_and_renormalizes():
    result = _compose_final_score(80.0, 80.0, 90.0, None)
    expected = round((0.40 * 80.0 + 0.35 * 80.0 + 0.15 * 90.0) / 0.90, 1)
    assert result == expected


def test_compose_final_score_excludes_both_unknowns():
    result = _compose_final_score(80.0, 60.0, None, None)
    expected = round((0.40 * 80.0 + 0.35 * 60.0) / 0.75, 1)
    assert result == expected


def test_compose_final_score_changes_when_weights_change(monkeypatch):
    # Phases.md Phase 6 acceptance: "Changing a weight in .env changes the
    # results." _compose_final_score reads the live settings singleton, so
    # the same four sub-scores must produce a different final score once
    # the weights are retuned.
    before = _compose_final_score(85.0, 90.0, 80.0, 100.0)
    monkeypatch.setattr(settings, "WEIGHT_RESUME", 0.70)
    monkeypatch.setattr(settings, "WEIGHT_SKILL", 0.20)
    monkeypatch.setattr(settings, "WEIGHT_EXPERIENCE", 0.05)
    monkeypatch.setattr(settings, "WEIGHT_EDUCATION", 0.05)
    after = _compose_final_score(85.0, 90.0, 80.0, 100.0)
    assert before != after
    assert after == round(0.70 * 85.0 + 0.20 * 90.0 + 0.05 * 80.0 + 0.05 * 100.0, 1)


# --- unit: band assignment (F7.5) ---------------------------------------------


@pytest.mark.parametrize(
    "score,band",
    [
        (100.0, ScoreBand.STRONG_MATCH),
        (85.0, ScoreBand.STRONG_MATCH),
        (84.9, ScoreBand.GOOD_MATCH),
        (70.0, ScoreBand.GOOD_MATCH),
        (69.9, ScoreBand.MODERATE_MATCH),
        (55.0, ScoreBand.MODERATE_MATCH),
        (54.9, ScoreBand.WEAK_MATCH),
        (0.0, ScoreBand.WEAK_MATCH),
    ],
)
def test_compute_band_thresholds(score, band):
    assert _compute_band(score) == band


# --- unit: experience sub-score (F7.3) ----------------------------------------


def test_experience_score_meeting_requirement_is_100():
    assert _experience_score(2.0, 2.0) == 100.0


def test_experience_score_exceeding_requirement_caps_at_100():
    assert _experience_score(10.0, 2.0) == 100.0


def test_experience_score_below_requirement_is_ratio():
    assert _experience_score(1.0, 2.0) == 50.0


def test_experience_score_zero_required_is_100_not_division_error():
    assert _experience_score(0.0, 0.0) == 100.0
    assert _experience_score(None, 0.0) == 100.0


def test_experience_score_none_years_is_none_not_zero():
    assert _experience_score(None, 2.0) is None


# --- unit: education sub-score (F7.4) -----------------------------------------


def test_education_score_meets_requirement_is_100():
    assert _education_score(candidate_level=3, required_level=3) == 100.0
    assert _education_score(candidate_level=5, required_level=3) == 100.0


def test_education_score_one_level_below_is_70():
    assert _education_score(candidate_level=2, required_level=3) == 70.0


def test_education_score_two_or_more_below_is_40():
    assert _education_score(candidate_level=1, required_level=3) == 40.0
    assert _education_score(candidate_level=1, required_level=5) == 40.0


def test_education_score_none_candidate_level_is_none_not_zero():
    assert _education_score(candidate_level=None, required_level=3) is None


def test_education_score_none_required_level_is_none():
    # The job's own requirement text didn't resolve to any ladder level —
    # nothing to compare against, so this is excluded rather than guessed.
    assert _education_score(candidate_level=3, required_level=None) is None


# --- unit: skill gap (F6.1-F6.4) -----------------------------------------------


def test_compute_skill_gap_matched_missing_additional_percentage():
    result = compute_skill_gap(
        required_skills=["Python", "FastAPI", "SQL"],
        candidate_skills=["Python", "Docker"],
    )
    assert result.matched == [SkillGapMatch(skill="Python", source=SkillSource.DICTIONARY)]
    assert result.missing == ["FastAPI", "SQL"]
    assert result.additional == ["Docker"]
    assert result.percentage == pytest.approx(100 / 3)


def test_compute_skill_gap_is_case_insensitive():
    result = compute_skill_gap(required_skills=["python"], candidate_skills=["Python"])
    assert result.matched == [SkillGapMatch(skill="python", source=SkillSource.DICTIONARY)]
    assert result.missing == []
    assert result.percentage == 100.0


def test_compute_skill_gap_zero_matches_is_a_real_zero():
    result = compute_skill_gap(required_skills=["Rust"], candidate_skills=["Python"])
    assert result.matched == []
    assert result.percentage == 0.0


# --- unit: semantic skill-match fallback (F4.4) ---------------------------------
#
# Uses a plain hand-written embed() stub, not the fake model fixture above —
# these tests are about apply_semantic_fallback's own promotion/percentage
# logic, not about the embedding model, so the vectors are simple enough to
# reason about directly (skills sharing a token score higher than ones that
# don't).


def _stub_embed(text: str) -> list[float]:
    """One-hot-ish: each distinct word gets its own dimension, so two
    skill names sharing a word (e.g. "Kubernetes" and "Container
    Orchestration" sharing nothing — deliberately chosen below) can be
    made to score above or below SEMANTIC_MATCH_THRESHOLD predictably.
    """
    vocab = ["kubernetes", "containers", "docker", "python", "javascript", "unrelated"]
    vector = [1.0 if word in text.lower() else 0.0 for word in vocab]
    return vector


def test_apply_semantic_fallback_promotes_above_threshold():
    gap = compute_skill_gap(required_skills=["Kubernetes"], candidate_skills=["Containers"])
    assert gap.missing == ["Kubernetes"]

    def embed(text: str) -> list[float]:
        # Both "Kubernetes" and "Containers" map to the same single-hot
        # vector here — cosine similarity 1.0, comfortably above the 0.5
        # threshold.
        return [1.0] if text in ("Kubernetes", "Containers") else [0.0]

    result = apply_semantic_fallback(gap, ["Containers"], embed)
    assert result.missing == []
    assert result.matched == [
        SkillGapMatch(skill="Kubernetes", source=SkillSource.SEMANTIC, matched_via="Containers")
    ]


def test_apply_semantic_fallback_leaves_below_threshold_as_missing():
    gap = compute_skill_gap(required_skills=["Kubernetes"], candidate_skills=["Watercolor"])

    def embed(text: str) -> list[float]:
        # Orthogonal vectors -> cosine similarity 0.0, below threshold.
        return [1.0, 0.0] if text == "Kubernetes" else [0.0, 1.0]

    result = apply_semantic_fallback(gap, ["Watercolor"], embed)
    assert result.missing == ["Kubernetes"]
    assert result.matched == []


def test_apply_semantic_fallback_gives_half_credit_not_full():
    # F4.4 calls it a "partial" match; Design.md renders it visually
    # weaker than an exact match — the percentage has to be weaker too.
    gap = compute_skill_gap(required_skills=["Python", "Kubernetes"], candidate_skills=["Python", "Containers"])
    assert gap.percentage == 50.0  # one exact match out of two required

    def embed(text: str) -> list[float]:
        return [1.0] if text in ("Kubernetes", "Containers") else [0.0]

    result = apply_semantic_fallback(gap, ["Python", "Containers"], embed)
    # 1 exact (weight 1.0) + 1 semantic (weight 0.5) over 2 required = 75%,
    # not 100% — a semantic promotion must not read identically to a
    # second exact match.
    assert result.percentage == 75.0


def test_apply_semantic_fallback_picks_the_single_best_candidate_skill():
    gap = compute_skill_gap(required_skills=["Kubernetes"], candidate_skills=["Docker", "Terraform"])

    def embed(text: str) -> list[float]:
        vectors = {"Kubernetes": [1.0, 0.4], "Docker": [1.0, 0.0], "Terraform": [0.0, 1.0]}
        return vectors[text]

    result = apply_semantic_fallback(gap, ["Docker", "Terraform"], embed)
    assert result.matched == [
        SkillGapMatch(skill="Kubernetes", source=SkillSource.SEMANTIC, matched_via="Docker")
    ]


def test_apply_semantic_fallback_noop_when_nothing_missing():
    gap = compute_skill_gap(required_skills=["Python"], candidate_skills=["Python"])
    result = apply_semantic_fallback(gap, ["Python"], _stub_embed)
    assert result is gap  # early return, no embed() calls needed


def test_apply_semantic_fallback_noop_when_candidate_has_no_skills():
    gap = compute_skill_gap(required_skills=["Python"], candidate_skills=[])
    result = apply_semantic_fallback(gap, [], _stub_embed)
    assert result is gap


# --- unit: TF-IDF ranker --------------------------------------------------------


def test_tfidf_ranker_raises_if_scored_before_fit():
    ranker = TFIDFRanker()
    with pytest.raises(RuntimeError):
        ranker.score("some resume", "some job")


def test_tfidf_ranker_closer_text_scores_higher():
    ranker = TFIDFRanker()
    job_text = "Python backend engineer with FastAPI and PostgreSQL experience"
    close_resume = "Senior Python backend engineer, FastAPI, PostgreSQL"
    far_resume = "Watercolor painting instructor and ceramics studio manager"
    ranker.fit([job_text, close_resume, far_resume])

    close_score = ranker.score(close_resume, job_text)
    far_score = ranker.score(far_resume, job_text)
    assert close_score > far_score
    assert far_score == 0.0


def test_tfidf_ranker_identical_text_scores_100():
    ranker = TFIDFRanker()
    text = "Python FastAPI PostgreSQL backend engineer"
    ranker.fit([text, "something unrelated entirely about gardening"])
    assert ranker.score(text, text) == pytest.approx(100.0)


# --- unit: ranker factory -------------------------------------------------------


def test_factory_returns_tfidf_ranker_for_tfidf_method():
    assert isinstance(get_ranker("tfidf"), TFIDFRanker)


def test_factory_returns_embedding_ranker_for_embedding_method():
    # Construction never touches the model — EmbeddingRanker only loads it
    # lazily on the first fit()/score() call — so this needs no mocking.
    assert isinstance(get_ranker("embedding"), EmbeddingRanker)


# --- unit: embedding ranker (F5.2, F5.5) ----------------------------------------


def test_embedding_ranker_identical_text_scores_100(fake_model):
    ranker = EmbeddingRanker()
    text = "Python FastAPI PostgreSQL backend engineer"
    assert ranker.score(text, text) == pytest.approx(100.0)


def test_embedding_ranker_closer_text_scores_higher(fake_model):
    ranker = EmbeddingRanker()
    job_text = "Python backend engineer with FastAPI and PostgreSQL experience"
    close_resume = "Senior Python backend engineer, FastAPI, PostgreSQL"
    far_resume = "Watercolor painting instructor and ceramics studio manager"
    assert ranker.score(close_resume, job_text) > ranker.score(far_resume, job_text)


def test_embedding_ranker_score_is_clamped_to_0_100(fake_model):
    ranker = EmbeddingRanker()
    score = ranker.score("a", "b")
    assert 0.0 <= score <= 100.0


def test_embedding_ranker_fit_batches_into_one_encode_call(fake_model):
    ranker = EmbeddingRanker()
    corpus = ["job description text", "resume one text", "resume two text"]
    ranker.fit(corpus)
    assert fake_model.encode_call_count == 1
    assert set(fake_model.encoded_texts) == set(corpus)


def test_embedding_ranker_fit_skips_text_already_seeded(fake_model):
    # The mechanism behind F5.5: a candidate embedding already read from
    # candidates.embedding and seeded in is never re-encoded by fit().
    ranker = EmbeddingRanker()
    ranker.seed("already cached resume text", [0.1] * 64)
    ranker.fit(["already cached resume text", "new resume text"])
    assert fake_model.encode_call_count == 1
    assert fake_model.encoded_texts == ["new resume text"]


def test_embedding_ranker_score_after_fit_does_not_reencode(fake_model):
    ranker = EmbeddingRanker()
    job_text, resume_text = "job description", "resume text"
    ranker.fit([job_text, resume_text])
    calls_after_fit = fake_model.encode_call_count
    ranker.score(resume_text, job_text)
    assert fake_model.encode_call_count == calls_after_fit  # served entirely from cache


def test_embedding_ranker_embed_without_fit_computes_and_caches(fake_model):
    ranker = EmbeddingRanker()
    ranker.embed("some text")
    ranker.embed("some text")
    assert fake_model.encode_call_count == 1  # second call hits the cache


def test_embedding_ranker_raises_model_unavailable_from_fit(unavailable_model):
    ranker = EmbeddingRanker()
    with pytest.raises(ModelUnavailableError) as exc_info:
        ranker.fit(["some job text", "some resume text"])
    assert exc_info.value.code == "EMBEDDING_MODEL_UNAVAILABLE"


def test_ensure_model_available_raises_when_model_unavailable(unavailable_model):
    with pytest.raises(ModelUnavailableError) as exc_info:
        embedding_ranker.ensure_model_available()
    assert exc_info.value.code == "EMBEDDING_MODEL_UNAVAILABLE"


def test_embedding_model_is_a_process_wide_singleton(monkeypatch):
    # _get_model is a MODULE-level lru_cache, not an instance attribute —
    # every EmbeddingRanker across every request shares the one loaded
    # model (Rules.md 4.6: loaded once, never per request), proven here by
    # two separate instances embedding different text yet the underlying
    # loader firing only once.
    load_count = 0

    def _fake_loader():
        nonlocal load_count
        load_count += 1
        return _FakeEmbeddingModel()

    monkeypatch.setattr(embedding_ranker, "_get_model", lru_cache(maxsize=1)(_fake_loader))

    EmbeddingRanker().embed("first ranker's text")
    EmbeddingRanker().embed("second ranker's text")
    assert load_count == 1


# --- endpoint: POST /jobs/{id}/score --------------------------------------------


def test_score_job_computes_all_four_sub_scores(client, db_session, auth_headers):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _apply(db_session, candidate, job)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])

    response = client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    assert response.status_code == 200
    body = response.json()
    assert body == {"job_id": job.id, "scored": 1, "skipped": 0, "results": body["results"]}
    assert body["results"][0]["status"] == "scored"

    score = client.get(
        f"/api/v1/candidates/{candidate.id}/score", headers=auth_headers, params={"job_id": job.id}
    ).json()
    assert score["skill_match_score"] == pytest.approx(2 / 3 * 100, abs=0.1)
    assert score["experience_score"] == 100.0
    assert score["education_score"] == 100.0
    assert 0.0 <= score["resume_match_score"] <= 100.0
    assert score["excluded_sub_scores"] == []
    assert score["is_stale"] is False
    assert score["scoring_method"] == "tfidf"
    assert score["score_version"] == 2  # bumped in Phase 7 — see scoring_service.py
    assert score["band"] == _expected_band(score["final_fit_score"])

    expected_final = round(
        0.40 * score["resume_match_score"]
        + 0.35 * score["skill_match_score"]
        + 0.15 * score["experience_score"]
        + 0.10 * score["education_score"],
        1,
    )
    assert score["final_fit_score"] == expected_final


def test_score_job_with_no_required_skills_returns_job_has_no_skills(client, db_session, auth_headers):
    job = _make_job(db_session, required_skills=[])
    candidate = _make_candidate(db_session)
    _apply(db_session, candidate, job)

    response = client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "JOB_HAS_NO_SKILLS"


def test_score_job_missing_returns_404(client, auth_headers):
    response = client.post("/api/v1/jobs/999999/score", headers=auth_headers, json={})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_score_job_requires_auth(client, db_session):
    job = _make_job(db_session)
    response = client.post(f"/api/v1/jobs/{job.id}/score", json={})
    assert response.status_code == 401


def test_score_job_skips_unusable_resume_text_with_reason(client, db_session, auth_headers):
    job = _make_job(db_session)
    candidate = _make_candidate(
        db_session, resume_text="", parse_status=ParseStatus.PARSE_FAILED
    )
    _apply(db_session, candidate, job)

    response = client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    assert response.status_code == 200
    body = response.json()
    assert body["scored"] == 0
    assert body["skipped"] == 1
    assert body["results"][0] == {
        "candidate_id": candidate.id,
        "status": "skipped",
        "final_fit_score": None,
        "code": "RESUME_TEXT_TOO_SHORT",
        "reason": "Candidate has no usable resume text (parse failed).",
    }
    assert db_session.query(CandidateScore).filter(CandidateScore.candidate_id == candidate.id).one_or_none() is None


def test_score_job_explicit_candidate_not_applied_is_skipped(client, db_session, auth_headers):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)  # never applied

    response = client.post(
        f"/api/v1/jobs/{job.id}/score",
        headers=auth_headers,
        json={"candidate_ids": [candidate.id]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scored"] == 0
    assert body["results"][0]["code"] == "CANDIDATE_NOT_APPLIED"


def test_score_job_default_run_skips_already_scored_non_stale_candidates(client, db_session, auth_headers):
    job = _make_job(db_session)
    candidate_a = _make_candidate(db_session, email="a@example.com")
    _apply(db_session, candidate_a, job)

    first = client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    assert first.json()["scored"] == 1

    candidate_b = _make_candidate(db_session, email="b@example.com")
    _apply(db_session, candidate_b, job)

    second = client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    body = second.json()
    assert body["scored"] == 1
    assert body["results"][0]["candidate_id"] == candidate_b.id


def test_score_job_force_rescores_everyone(client, db_session, auth_headers):
    job = _make_job(db_session)
    candidate_a = _make_candidate(db_session, email="a@example.com")
    candidate_b = _make_candidate(db_session, email="b@example.com")
    _apply(db_session, candidate_a, job)
    _apply(db_session, candidate_b, job)

    client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    forced = client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={"force": True})
    assert forced.json()["scored"] == 2


def test_score_job_default_run_clears_stale_flag(client, db_session, auth_headers):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _apply(db_session, candidate, job)
    client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})

    score_row = db_session.query(CandidateScore).filter(CandidateScore.candidate_id == candidate.id).one()
    score_row.is_stale = True
    db_session.commit()

    response = client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    assert response.json()["scored"] == 1

    refreshed = client.get(
        f"/api/v1/candidates/{candidate.id}/score", headers=auth_headers, params={"job_id": job.id}
    ).json()
    assert refreshed["is_stale"] is False


def test_score_job_unknown_experience_excludes_and_renormalizes(client, db_session, auth_headers):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, experience_years=None)
    _apply(db_session, candidate, job)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])

    client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    score = client.get(
        f"/api/v1/candidates/{candidate.id}/score", headers=auth_headers, params={"job_id": job.id}
    ).json()

    assert score["experience_score"] is None
    assert score["excluded_sub_scores"] == ["experience"]
    expected_final = round(
        (0.40 * score["resume_match_score"] + 0.35 * score["skill_match_score"] + 0.10 * score["education_score"])
        / 0.85,
        1,
    )
    assert score["final_fit_score"] == expected_final


# --- endpoint: GET /candidates/{id}/score ---------------------------------------


def test_get_candidate_score_not_found(client, db_session, auth_headers):
    candidate = _make_candidate(db_session)
    job = _make_job(db_session)
    response = client.get(
        f"/api/v1/candidates/{candidate.id}/score", headers=auth_headers, params={"job_id": job.id}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SCORE_NOT_FOUND"


# --- endpoint: GET /candidates/{id}/skill-gap -----------------------------------


def test_get_skill_gap_matches_stored_score(client, db_session, auth_headers):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _apply(db_session, candidate, job)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])
    client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})

    response = client.get(
        f"/api/v1/candidates/{candidate.id}/skill-gap", headers=auth_headers, params={"job_id": job.id}
    )
    assert response.status_code == 200
    body = response.json()
    matched_skill_names = sorted(m["skill"] for m in body["matched"])
    assert matched_skill_names == ["FastAPI", "Python"]
    assert all(m["source"] == "dictionary" for m in body["matched"])
    assert all(m["matched_via"] is None for m in body["matched"])
    assert body["missing"] == ["SQL"]
    assert body["additional"] == []
    assert body["percentage"] == pytest.approx(2 / 3 * 100, abs=0.1)


# --- endpoint: embedding-mode scoring (F5.2, F5.5) ------------------------------


def test_score_job_embedding_mode_computes_and_caches_embedding(client, db_session, auth_headers, monkeypatch, fake_model):
    monkeypatch.setattr(settings, "SCORING_METHOD", "embedding")
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _apply(db_session, candidate, job)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])

    assert candidate.embedding is None
    response = client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    assert response.status_code == 200

    db_session.refresh(candidate)
    assert candidate.embedding is not None
    assert isinstance(candidate.embedding, list)

    score = client.get(
        f"/api/v1/candidates/{candidate.id}/score", headers=auth_headers, params={"job_id": job.id}
    ).json()
    assert score["scoring_method"] == "embedding"
    assert 0.0 <= score["resume_match_score"] <= 100.0


def test_score_job_embedding_mode_second_job_reuses_cached_embedding(client, db_session, auth_headers, monkeypatch, fake_model):
    # F5.5 / Phases.md Phase 7 acceptance: re-scoring the same candidate for
    # a second job reuses the cached embedding instead of re-encoding.
    monkeypatch.setattr(settings, "SCORING_METHOD", "embedding")
    job_a = _make_job(db_session, title="Job A")
    job_b = _make_job(db_session, title="Job B")
    candidate = _make_candidate(db_session)
    _apply(db_session, candidate, job_a)
    _apply(db_session, candidate, job_b)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])

    client.post(f"/api/v1/jobs/{job_a.id}/score", headers=auth_headers, json={})
    calls_after_first_job = fake_model.encode_call_count
    assert candidate.resume_text in fake_model.encoded_texts

    client.post(f"/api/v1/jobs/{job_b.id}/score", headers=auth_headers, json={})
    # The candidate's resume text must not be sent to encode() again — only
    # job_b's (different) description is new work.
    resume_encode_count = fake_model.encoded_texts.count(candidate.resume_text)
    assert resume_encode_count == 1
    assert fake_model.encode_call_count > calls_after_first_job  # job_b's description still encoded


def test_score_job_embedding_mode_missing_model_returns_503(client, db_session, auth_headers, monkeypatch, unavailable_model):
    monkeypatch.setattr(settings, "SCORING_METHOD", "embedding")
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _apply(db_session, candidate, job)
    _add_skills(db_session, candidate, ["Python"])

    response = client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "EMBEDDING_MODEL_UNAVAILABLE"
    # No score row was written — the whole call failed loudly rather than
    # recording the candidate as an individually "failed" skip.
    assert db_session.query(CandidateScore).filter(CandidateScore.candidate_id == candidate.id).one_or_none() is None


def test_score_job_tfidf_mode_unaffected_by_broken_embedding_model(client, db_session, auth_headers, unavailable_model):
    # settings.SCORING_METHOD is untouched (stays "tfidf", the default) —
    # tfidf must keep working even with a broken embedding model, since it
    # never reaches EmbeddingRanker at all.
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _apply(db_session, candidate, job)
    _add_skills(db_session, candidate, ["Python", "FastAPI"])

    response = client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    assert response.status_code == 200
    assert response.json()["scored"] == 1


# --- endpoint: semantic skill-match gate (F4.4) ---------------------------------


def test_semantic_skill_matching_off_by_default_never_touches_model(client, db_session, auth_headers):
    # settings.SEMANTIC_SKILL_MATCHING is untouched (default False). No
    # fake_model/unavailable_model fixture is used here on purpose — if the
    # default path touched the embedding model at all, the real
    # sentence-transformers loader would run and either hang on a network
    # call or (if cached) spend real time, either of which would make this
    # test slow or flaky. It running fast and green is itself the proof.
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _apply(db_session, candidate, job)
    _add_skills(db_session, candidate, ["Python"])  # "FastAPI"/"SQL" stay missing

    response = client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    assert response.status_code == 200

    gap = client.get(
        f"/api/v1/candidates/{candidate.id}/skill-gap", headers=auth_headers, params={"job_id": job.id}
    ).json()
    assert all(m["source"] == "dictionary" for m in gap["matched"])
    assert sorted(gap["missing"]) == ["FastAPI", "SQL"]


def test_semantic_skill_matching_refuses_to_run_even_when_flag_true(client, db_session, auth_headers, monkeypatch):
    # The threshold is confirmed to mis-rank near-synonyms (Memory.md
    # decision 46) — semantic matching must refuse to run regardless of
    # the operator's config, not just default off. skill_gap.THRESHOLD_VALIDATED
    # is untouched here (stays its real False), and no fake_model/
    # unavailable_model fixture is used on purpose: if refusal weren't
    # real, this would hang on/fail against the actual model, since
    # SEMANTIC_SKILL_MATCHING=True is exactly what an operator who ignored
    # the startup warning would have set.
    monkeypatch.setattr(settings, "SEMANTIC_SKILL_MATCHING", True)
    job = _make_job(db_session, required_skills=["Python", "Kubernetes"])
    candidate = _make_candidate(db_session)
    _apply(db_session, candidate, job)
    _add_skills(db_session, candidate, ["Python", "Containers"])  # would promote if active

    response = client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    assert response.status_code == 200

    gap = client.get(
        f"/api/v1/candidates/{candidate.id}/skill-gap", headers=auth_headers, params={"job_id": job.id}
    ).json()
    assert all(m["source"] == "dictionary" for m in gap["matched"])
    assert gap["missing"] == ["Kubernetes"]


def test_semantic_skill_matching_promotes_with_half_credit_once_validated(client, db_session, auth_headers, monkeypatch, fake_model):
    # Proves the promotion mechanism itself is still correct — gated
    # behind a deliberate bypass of the real-world refusal above, since
    # that's the only way to exercise this path today. Once Phase 13
    # validates a real threshold and flips THRESHOLD_VALIDATED for real,
    # this monkeypatch becomes redundant, not wrong.
    monkeypatch.setattr(settings, "SEMANTIC_SKILL_MATCHING", True)
    monkeypatch.setattr(skill_gap, "THRESHOLD_VALIDATED", True)
    job = _make_job(db_session, required_skills=["Python", "Kubernetes"])
    candidate = _make_candidate(db_session)
    _apply(db_session, candidate, job)
    # _FakeEmbeddingModel hashes whole words into buckets — "Kubernetes"
    # and "Containers" share no words, so with the real fake encoder they
    # would NOT cross SEMANTIC_MATCH_THRESHOLD. Route apply_semantic_fallback
    # through a controlled embed function instead, the same way the pure
    # unit tests above do, by monkeypatching EmbeddingRanker.embed itself.
    _add_skills(db_session, candidate, ["Python", "Containers"])

    def _controlled_embed(self, text):
        return [1.0] if text in ("Kubernetes", "Containers") else [0.0]

    monkeypatch.setattr(EmbeddingRanker, "embed", _controlled_embed)

    response = client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    assert response.status_code == 200

    gap = client.get(
        f"/api/v1/candidates/{candidate.id}/skill-gap", headers=auth_headers, params={"job_id": job.id}
    ).json()
    semantic_matches = [m for m in gap["matched"] if m["source"] == "semantic"]
    assert semantic_matches == [{"skill": "Kubernetes", "source": "semantic", "matched_via": "Containers"}]
    assert gap["missing"] == []
    # 1 exact (Python) + 1 semantic (Kubernetes, half credit) over 2
    # required = 75%, not 100%.
    assert gap["percentage"] == pytest.approx(75.0, abs=0.1)


def test_semantic_skill_matching_degrades_quietly_when_model_unavailable_once_validated(client, db_session, auth_headers, monkeypatch, unavailable_model, caplog):
    # Same deliberate bypass as above — this test is about the
    # model-unavailable degradation path specifically, which is
    # unreachable today (the refusal gate returns first); still worth
    # keeping correct and tested for when Phase 13 validates the threshold.
    monkeypatch.setattr(settings, "SEMANTIC_SKILL_MATCHING", True)
    monkeypatch.setattr(skill_gap, "THRESHOLD_VALIDATED", True)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _apply(db_session, candidate, job)
    _add_skills(db_session, candidate, ["Python"])

    with caplog.at_level("WARNING"):
        response = client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    # tfidf ranking is unaffected (this test never touches SCORING_METHOD);
    # only the semantic skill-match layer degrades.
    assert response.status_code == 200
    assert response.json()["scored"] == 1
    assert any("SEMANTIC_SKILL_MATCHING" in record.message for record in caplog.records)

    gap = client.get(
        f"/api/v1/candidates/{candidate.id}/skill-gap", headers=auth_headers, params={"job_id": job.id}
    ).json()
    assert all(m["source"] == "dictionary" for m in gap["matched"])


# --- endpoint: GET /jobs/{id}/rankings ------------------------------------------


def test_rankings_ordered_by_final_fit_score_descending(client, db_session, auth_headers):
    job = _make_job(db_session)
    strong = _make_candidate(db_session, email="strong@example.com", experience_years=10.0)
    weak = _make_candidate(
        db_session, email="weak@example.com", experience_years=0.1, education_level=1,
        resume_text="Watercolor painting instructor and ceramics studio manager.",
    )
    _apply(db_session, strong, job)
    _apply(db_session, weak, job)
    _add_skills(db_session, strong, ["Python", "FastAPI", "SQL"])

    client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    response = client.get(f"/api/v1/jobs/{job.id}/rankings", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    scores = [item["final_fit_score"] for item in body["items"]]
    assert scores == sorted(scores, reverse=True)
    assert body["items"][0]["candidate_id"] == strong.id
    assert body["items"][0]["candidate_name"] is not None or body["items"][0]["candidate_email"] == "strong@example.com"


def test_rankings_missing_job_returns_404(client, auth_headers):
    response = client.get("/api/v1/jobs/999999/rankings", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


# --- performance (F5.4) ---------------------------------------------------------


def test_scoring_50_candidates_completes_under_60_seconds(client, db_session, auth_headers):
    import time

    job = _make_job(db_session)
    for i in range(50):
        candidate = _make_candidate(
            db_session,
            email=f"perf{i}@example.com",
            resume_text=f"Candidate {i}: Python developer with FastAPI and SQL experience, {i} years.",
        )
        _apply(db_session, candidate, job)
        _add_skills(db_session, candidate, ["Python", "FastAPI"])

    start = time.monotonic()
    response = client.post(f"/api/v1/jobs/{job.id}/score", headers=auth_headers, json={})
    elapsed = time.monotonic() - start

    assert response.status_code == 200
    assert response.json()["scored"] == 50
    assert elapsed < 60.0
