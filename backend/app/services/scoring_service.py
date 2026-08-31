"""Fit-score composition and batch (re)scoring (PRD F5-F7, Architecture.md
7.2, Phases.md Phase 6/Phase 7). Raises domain exceptions from
core/exceptions.py; never HTTPException (Rules.md 5.2).
"""
import logging
from typing import Callable

from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.core.enums import ParseStatus, ScoreBand, ScoringMethod, SkillSource
from app.core.exceptions import ModelUnavailableError, NotFoundError, ValidationError
from app.ml.extraction.field_extractor import extract_education
from app.ml.ranking.base import Ranker
from app.ml.ranking.embedding_ranker import EmbeddingRanker, ensure_model_available
from app.ml.ranking.factory import get_ranker
from app.ml.skills import skill_gap
from app.ml.skills.skill_gap import apply_semantic_fallback, compute_skill_gap
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.candidate_score import CandidateScore
from app.models.job import Job
from app.schemas.common import Page
from app.schemas.score import (
    CandidateScoreResponse,
    CompareCandidatesResponse,
    ComparisonCandidateDetail,
    ComparisonMetricRow,
    RankingEntry,
    ScoreJobResponse,
    ScoreJobResultItem,
    SkillGapMatchOut,
    SkillGapResponse,
)

logger = logging.getLogger(__name__)

# Hand-maintained: bumped by a person when the scoring FORMULA itself
# changes (a new sub-score, a different composition method) — never
# bumped automatically just because a weight in .env is retuned, since
# that is normal operation within the same formula version, not a new one
# (see Memory.md).
#
# Bumped to 2 in Phase 7, exactly as Phase 6's own version of this comment
# anticipated ("Phase 7's embedding ranker"): skill_match_score's formula
# itself changed (a semantic match now contributes SEMANTIC_MATCH_WEIGHT
# credit, not just an exact dictionary match), and embedding-mode
# resume_match is computed by a structurally different method than TF-IDF
# cosine similarity. A score_version=1 row predates both changes.
SCORE_VERSION = 2

# F7.5 — checked high to low; the first threshold met wins.
_BAND_THRESHOLDS = (
    (85.0, ScoreBand.STRONG_MATCH),
    (70.0, ScoreBand.GOOD_MATCH),
    (55.0, ScoreBand.MODERATE_MATCH),
)

_EDUCATION_MATCH = 100.0
_EDUCATION_ONE_BELOW = 70.0
_EDUCATION_TWO_OR_MORE_BELOW = 40.0


def _compute_band(final_fit_score: float) -> ScoreBand:
    for threshold, band in _BAND_THRESHOLDS:
        if final_fit_score >= threshold:
            return band
    return ScoreBand.WEAK_MATCH


def _get_job_or_404(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise NotFoundError("Job not found.", code="JOB_NOT_FOUND", details={"job_id": job_id})
    return job


def _get_score_or_404(db: Session, candidate_id: int, job_id: int) -> CandidateScore:
    score = (
        db.query(CandidateScore)
        .filter(CandidateScore.candidate_id == candidate_id, CandidateScore.job_id == job_id)
        .one_or_none()
    )
    if score is None:
        raise NotFoundError(
            "No score exists for this candidate and job.",
            code="SCORE_NOT_FOUND",
            details={"candidate_id": candidate_id, "job_id": job_id},
        )
    return score


def _has_usable_resume_text(candidate: Candidate) -> bool:
    return candidate.parse_status == ParseStatus.PARSED and bool(
        candidate.resume_text and candidate.resume_text.strip()
    )


def _applied_candidates(db: Session, job_id: int) -> list[Candidate]:
    return (
        db.query(Candidate)
        .options(selectinload(Candidate.candidate_skills))
        .join(Application, Application.candidate_id == Candidate.id)
        .filter(Application.job_id == job_id)
        .all()
    )


def _select_candidates(
    db: Session, job_id: int, *, candidate_ids: list[int] | None, force: bool
) -> tuple[list[Candidate], list[ScoreJobResultItem]]:
    """Architecture.md 7.2: "select candidates (explicit ids, or all
    applied and unscored, or all if force)". Explicit ids always win over
    `force` when both are given — an explicit id is always (re)scored.
    Returns (candidates_to_score, pre-skipped items for anyone excluded at
    selection time, e.g. an explicit id with no application to this job).
    """
    applied = _applied_candidates(db, job_id)
    applied_by_id = {candidate.id: candidate for candidate in applied}
    preskipped: list[ScoreJobResultItem] = []

    if candidate_ids is not None:
        selected = []
        for candidate_id in candidate_ids:
            candidate = applied_by_id.get(candidate_id)
            if candidate is None:
                preskipped.append(
                    ScoreJobResultItem(
                        candidate_id=candidate_id,
                        status="skipped",
                        code="CANDIDATE_NOT_APPLIED",
                        reason="Candidate has not applied to this job.",
                    )
                )
            else:
                selected.append(candidate)
        return selected, preskipped

    if force:
        return applied, preskipped

    # Default: unscored, or scored but flagged stale by a job edit — a
    # scored, non-stale candidate is left untouched. Without picking up
    # stale rows here, a stale flag would never clear short of a full
    # force rescore, defeating F7.7's point.
    existing = {
        score.candidate_id: score
        for score in db.query(CandidateScore).filter(CandidateScore.job_id == job_id).all()
    }
    selected = [
        candidate
        for candidate in applied
        if candidate.id not in existing or existing[candidate.id].is_stale
    ]
    return selected, preskipped


def _warm_embedding_cache(ranker: Ranker, candidates: list[Candidate]) -> None:
    """Seeds any already-persisted candidates.embedding into the ranker's
    own cache before fit() runs, so a candidate scored for a second job
    never re-encodes their resume text — the mechanism behind F5.5's
    "reused across jobs." Duck-typed (no `seed` attribute) rather than an
    isinstance check, so this is a no-op for TFIDFRanker without this
    module needing to import embedding_ranker.py at all — the tfidf path
    is untouched.
    """
    if not hasattr(ranker, "seed"):
        return
    for candidate in candidates:
        if candidate.embedding is not None:
            ranker.seed(candidate.resume_text, candidate.embedding)


def _semantic_embed_fn(job_id: int) -> Callable[[str], list[float]] | None:
    """F4.4, opt-in via settings.SEMANTIC_SKILL_MATCHING — deliberately
    off by default (Memory.md): the shipped SCORING_METHOD=tfidf config
    must never silently depend on the embedding model, and skill-gap
    computation runs for every candidate regardless of ranking method.

    Refuses to run regardless of the flag's value while
    skill_gap.THRESHOLD_VALIDATED is False: a real-model sanity check
    found SEMANTIC_MATCH_THRESHOLD isn't just unmeasured, it's inverted on
    the cases that matter (a different product passes; a genuine
    paraphrase fails — see skill_gap.py and docs/EVALUATION.md's Phase 7
    section). config.py already logs a startup WARNING when the operator
    sets the flag, so this doesn't warn again per scoring run — it just
    quietly never activates, same as the flag being off. Module-qualified
    access (not `from ... import THRESHOLD_VALIDATED`) so a future flip of
    this constant is actually observed here rather than a stale imported
    copy.

    Once validated: checked once per score_job() call, not once per
    candidate — functools.lru_cache doesn't cache a failed model load, so
    retrying per candidate would re-attempt (and re-fail) the same load up
    to once per candidate in the batch and spam the log identically each
    time. Returns None (dictionary-only skill gap for the whole run) when
    the model can't load either; logs a single WARNING in that case only
    (Rules.md 5.5 — recoverable degradation).
    """
    if not settings.SEMANTIC_SKILL_MATCHING:
        return None
    if not skill_gap.THRESHOLD_VALIDATED:
        return None
    try:
        ensure_model_available()
    except ModelUnavailableError:
        logger.warning(
            "SEMANTIC_SKILL_MATCHING is enabled but the embedding model is "
            "unavailable; scoring job %s with dictionary-only skill matching.",
            job_id,
        )
        return None
    return EmbeddingRanker().embed


def _experience_score(years: float | None, required_years: float) -> float | None:
    if required_years <= 0:
        # Zero years required is trivially met by everyone — a defined
        # case, not a division by zero.
        return 100.0
    if years is None:
        return None
    return round(min(years / required_years, 1.0) * 100, 1)


def _education_score(candidate_level: int | None, required_level: int | None) -> float | None:
    if required_level is None:
        # The job's own requirement text doesn't resolve to a ladder level
        # at all — there's nothing to compare any candidate against, so
        # this is excluded and renormalized the same as an unknown
        # candidate value, not guessed either way.
        return None
    if candidate_level is None:
        return None
    gap = required_level - candidate_level
    if gap <= 0:
        return _EDUCATION_MATCH
    if gap == 1:
        return _EDUCATION_ONE_BELOW
    return _EDUCATION_TWO_OR_MORE_BELOW


def _excluded_sub_scores(experience_score: float | None, education_score: float | None) -> list[str]:
    excluded = []
    if experience_score is None:
        excluded.append("experience")
    if education_score is None:
        excluded.append("education")
    return excluded


def _compose_final_score(
    resume_match: float,
    skill_match: float,
    experience_score: float | None,
    education_score: float | None,
) -> float:
    """F7.1's weighted sum, rounded to 1 decimal. Worked example with all
    four known and default weights: 85/90/80/100 -> 87.5.

    resume_match and skill_match are never None, so `known` always has at
    least two entries and `weight_sum` is always > 0 — no division-by-zero
    guard needed. When experience_score/education_score is None (unknown,
    not zero — see schemas/score.py), it's dropped from the sum and the
    remaining weights are renormalized to sum to 1.0 rather than treating
    the missing measurement as a zero.
    """
    weighted = (
        (settings.WEIGHT_RESUME, resume_match),
        (settings.WEIGHT_SKILL, skill_match),
        (settings.WEIGHT_EXPERIENCE, experience_score),
        (settings.WEIGHT_EDUCATION, education_score),
    )
    known = [(weight, sub_score) for weight, sub_score in weighted if sub_score is not None]
    weight_sum = sum(weight for weight, _ in known)
    return round(sum(weight * sub_score for weight, sub_score in known) / weight_sum, 1)


def _score_to_response(score: CandidateScore) -> CandidateScoreResponse:
    return CandidateScoreResponse(
        candidate_id=score.candidate_id,
        job_id=score.job_id,
        resume_match_score=score.resume_match_score,
        skill_match_score=score.skill_match_score,
        experience_score=score.experience_score,
        education_score=score.education_score,
        final_fit_score=score.final_fit_score,
        band=_compute_band(score.final_fit_score),
        scoring_method=score.scoring_method,
        score_version=score.score_version,
        is_stale=score.is_stale,
        excluded_sub_scores=_excluded_sub_scores(score.experience_score, score.education_score),
    )


def _score_one_candidate(
    db: Session,
    job: Job,
    candidate: Candidate,
    ranker: Ranker,
    required_level: int | None,
    semantic_embed: Callable[[str], list[float]] | None,
) -> CandidateScoreResponse:
    resume_match = round(ranker.score(candidate.resume_text, job.description), 1)

    # Embedding mode only (hasattr — TFIDFRanker has no embed()): persist a
    # freshly computed embedding so a later scoring run can reuse it
    # instead of re-encoding (F5.5). The vector was already computed as
    # part of ranker.score() above, so this is a cache lookup, not a
    # second encode call. Cache invalidation on resume re-upload lives in
    # resume_service.py, which resets this column to None when
    # resume_text changes.
    if hasattr(ranker, "embed") and candidate.embedding is None:
        candidate.embedding = ranker.embed(candidate.resume_text)

    candidate_skill_names = [skill.skill_name for skill in candidate.candidate_skills]
    gap = compute_skill_gap(job.required_skills, candidate_skill_names)
    if semantic_embed is not None:
        gap = apply_semantic_fallback(gap, candidate_skill_names, semantic_embed)
    skill_match = round(gap.percentage, 1)

    experience_score = _experience_score(candidate.experience_years, job.min_experience_years)
    education_score = _education_score(candidate.education_level, required_level)
    final_fit_score = _compose_final_score(resume_match, skill_match, experience_score, education_score)

    score_row = (
        db.query(CandidateScore)
        .filter(CandidateScore.candidate_id == candidate.id, CandidateScore.job_id == job.id)
        .one_or_none()
    )
    if score_row is None:
        score_row = CandidateScore(candidate_id=candidate.id, job_id=job.id)
        db.add(score_row)

    score_row.resume_match_score = resume_match
    score_row.skill_match_score = skill_match
    score_row.experience_score = experience_score
    score_row.education_score = education_score
    score_row.final_fit_score = final_fit_score
    # CandidateScore.matched_skills is a schemaless JSON column — dataclasses
    # aren't directly JSON-serializable, so each SkillGapMatch is stored as
    # a plain dict. source.value keeps the stored form the lowercase
    # string Architecture.md 9.6 documents, matching every other enum
    # column in this codebase.
    score_row.matched_skills = [
        {"skill": m.skill, "source": m.source.value, "matched_via": m.matched_via} for m in gap.matched
    ]
    score_row.missing_skills = gap.missing
    score_row.additional_skills = gap.additional
    score_row.scoring_method = ScoringMethod(settings.SCORING_METHOD)
    score_row.score_version = SCORE_VERSION
    score_row.is_stale = False

    db.flush()
    return _score_to_response(score_row)


def score_job(
    db: Session, job_id: int, *, candidate_ids: list[int] | None = None, force: bool = False
) -> ScoreJobResponse:
    job = _get_job_or_404(db, job_id)
    if not job.required_skills:
        raise ValidationError(
            "This job has no required skills; skill match cannot be computed.",
            code="JOB_HAS_NO_SKILLS",
            details={"job_id": job_id},
        )

    candidates, results = _select_candidates(
        db, job_id, candidate_ids=candidate_ids, force=force
    )

    # Corpus is every applicant with usable resume text, regardless of
    # which subset is actually (re)scored this call — see
    # ml/ranking/tfidf_ranker.py's docstring for why a smaller corpus
    # would make IDF meaningless, e.g. when only one candidate_id is
    # being rescored.
    corpus_candidates = [c for c in _applied_candidates(db, job_id) if _has_usable_resume_text(c)]
    ranker = get_ranker()
    if candidates and corpus_candidates:
        # Model-load failure (embedding mode only) surfaces here, outside
        # any per-candidate try/except below — it propagates straight up
        # as ModelUnavailableError -> 503 EMBEDDING_MODEL_UNAVAILABLE,
        # deliberately failing the whole call loudly rather than recording
        # every candidate as an individually "failed" SCORING_FAILED skip.
        # TF-IDF mode never reaches EmbeddingRanker at all.
        _warm_embedding_cache(ranker, corpus_candidates)
        corpus = [job.description] + [c.resume_text for c in corpus_candidates]
        ranker.fit(corpus)

    required_level = extract_education(job.education_requirement)[1]
    semantic_embed = _semantic_embed_fn(job_id)

    scored_count = 0
    for candidate in candidates:
        if not _has_usable_resume_text(candidate):
            results.append(
                ScoreJobResultItem(
                    candidate_id=candidate.id,
                    status="skipped",
                    code="RESUME_TEXT_TOO_SHORT",
                    reason="Candidate has no usable resume text (parse failed).",
                )
            )
            continue

        try:
            response = _score_one_candidate(db, job, candidate, ranker, required_level, semantic_embed)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Scoring failed for candidate %s on job %s", candidate.id, job_id)
            results.append(
                ScoreJobResultItem(
                    candidate_id=candidate.id,
                    status="skipped",
                    code="SCORING_FAILED",
                    reason="An unexpected error occurred while scoring this candidate.",
                )
            )
            continue

        results.append(
            ScoreJobResultItem(
                candidate_id=candidate.id, status="scored", final_fit_score=response.final_fit_score
            )
        )
        scored_count += 1

    return ScoreJobResponse(
        job_id=job_id, scored=scored_count, skipped=len(results) - scored_count, results=results
    )


def get_candidate_score(db: Session, candidate_id: int, job_id: int) -> CandidateScoreResponse:
    score = _get_score_or_404(db, candidate_id, job_id)
    return _score_to_response(score)


def get_skill_gap(db: Session, candidate_id: int, job_id: int) -> SkillGapResponse:
    score = _get_score_or_404(db, candidate_id, job_id)
    return SkillGapResponse(
        candidate_id=candidate_id,
        job_id=job_id,
        matched=score.matched_skills,
        missing=score.missing_skills,
        additional=score.additional_skills,
        percentage=score.skill_match_score,
    )


def get_rankings(db: Session, job_id: int, *, page: int, page_size: int) -> Page[RankingEntry]:
    _get_job_or_404(db, job_id)

    query = (
        db.query(CandidateScore)
        .filter(CandidateScore.job_id == job_id)
        .order_by(CandidateScore.final_fit_score.desc(), CandidateScore.candidate_id.asc())
    )
    total = query.count()
    scores = query.offset((page - 1) * page_size).limit(page_size).all()

    candidate_ids = [score.candidate_id for score in scores]
    candidates_by_id = (
        {c.id: c for c in db.query(Candidate).filter(Candidate.id.in_(candidate_ids)).all()}
        if candidate_ids
        else {}
    )

    items = []
    for score in scores:
        candidate = candidates_by_id.get(score.candidate_id)
        base = _score_to_response(score).model_dump()
        items.append(
            RankingEntry(
                **base,
                candidate_name=candidate.name if candidate else None,
                candidate_email=candidate.email if candidate else None,
            )
        )
    return Page.create(items=items, total=total, page=page, page_size=page_size)


# F11.2's comparison matrix, one row per metric. `direction` is what keeps
# F11.3's "leading value marked" honest per row rather than one hardcoded
# "highest wins" rule (Phases.md Phase 12): every *_score field is a 0-100
# match/fit measure where higher is unambiguously better, matched_skills
# is the same (more matched requirements is better), but missing_skills is
# the one row in this matrix where fewer is the better outcome.
_METRIC_DEFS: tuple[tuple[str, str, str], ...] = (
    ("final_fit_score", "Fit Score", "higher_is_better"),
    ("resume_match_score", "Resume Match", "higher_is_better"),
    ("skill_match_score", "Skill Match", "higher_is_better"),
    ("experience_score", "Experience", "higher_is_better"),
    ("education_score", "Education", "higher_is_better"),
    ("matched_skills_count", "Matched Skills", "higher_is_better"),
    ("missing_skills_count", "Missing Skills", "lower_is_better"),
)


def _metric_value(score: CandidateScore, metric: str) -> float | int | None:
    if metric == "matched_skills_count":
        return len(score.matched_skills)
    if metric == "missing_skills_count":
        return len(score.missing_skills)
    return getattr(score, metric)


def _best_candidate_id(values: dict[int, float | int | None], direction: str) -> int | None:
    known = {candidate_id: value for candidate_id, value in values.items() if value is not None}
    if not known:
        return None
    best_value = max(known.values()) if direction == "higher_is_better" else min(known.values())
    # Deterministic tie-break: lowest candidate_id among those tied for
    # best, the same secondary-key convention get_rankings() already uses
    # (CandidateScore.candidate_id.asc()) — required by Phases.md Phase 12's
    # "deterministic response" acceptance criterion.
    return min(candidate_id for candidate_id, value in known.items() if value == best_value)


def compare_candidates(db: Session, job_id: int, candidate_ids: list[int]) -> CompareCandidatesResponse:
    """`GET /jobs/{id}/compare?candidate_ids=` (Architecture.md 6.2, F11).
    `candidate_ids` is already validated to 2-4 well-formed integers by
    dependencies.compare_candidate_ids before this is ever called.
    """
    _get_job_or_404(db, job_id)

    scores = (
        db.query(CandidateScore)
        .filter(CandidateScore.job_id == job_id, CandidateScore.candidate_id.in_(candidate_ids))
        .all()
    )
    scores_by_id = {score.candidate_id: score for score in scores}
    missing = [candidate_id for candidate_id in candidate_ids if candidate_id not in scores_by_id]
    if missing:
        # Covers both a candidate that doesn't belong to this job (no
        # Application, so never scored for it) and one that applied but
        # hasn't been scored yet — either way, there's nothing to compare,
        # and SCORE_NOT_FOUND is the existing code for exactly that shape
        # (see _get_score_or_404 above).
        raise NotFoundError(
            "One or more candidates have no score for this job.",
            code="SCORE_NOT_FOUND",
            details={"job_id": job_id, "missing_candidate_ids": missing},
        )

    candidates_by_id = {
        candidate.id: candidate
        for candidate in db.query(Candidate).filter(Candidate.id.in_(candidate_ids)).all()
    }

    matrix = [
        ComparisonMetricRow(
            metric=metric,
            label=label,
            direction=direction,
            values=(values := {cid: _metric_value(scores_by_id[cid], metric) for cid in candidate_ids}),
            best_candidate_id=_best_candidate_id(values, direction),
        )
        for metric, label, direction in _METRIC_DEFS
    ]

    candidates_detail = [
        ComparisonCandidateDetail(
            candidate_id=candidate_id,
            candidate_name=(
                candidates_by_id[candidate_id].name if candidate_id in candidates_by_id else None
            ),
            matched_skills=[
                SkillGapMatchOut(
                    skill=match["skill"],
                    source=SkillSource(match["source"]),
                    matched_via=match.get("matched_via"),
                )
                for match in scores_by_id[candidate_id].matched_skills
            ],
            missing_skills=scores_by_id[candidate_id].missing_skills,
        )
        for candidate_id in candidate_ids
    ]

    return CompareCandidatesResponse(
        job_id=job_id, candidate_ids=candidate_ids, candidates=candidates_detail, matrix=matrix
    )
