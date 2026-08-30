"""Skill gap computation (PRD F6.1-F6.4, F4.4). Pure — no DB, no HTTP
(Rules.md 4.2). Matching is case-insensitive, the same convention
job_service.get_suggested_skills already uses to compare a job's
free-typed required_skills against canonical skill names: a recruiter
typing "python" and a candidate's canonical "Python" are the same skill,
not a miss.
"""
from dataclasses import dataclass
from typing import Callable

from sklearn.metrics.pairwise import cosine_similarity

from app.core.enums import SkillSource

# F4.4 — admitted guess, not a tuned value: there is no labelled skill-match
# evaluation set yet (that's Phase 13's ml/skill_eval/). See Phases.md
# Phase 13 and docs/EVALUATION.md for the paper trail on this constant.
SEMANTIC_MATCH_THRESHOLD = 0.5

# F4.4 calls a semantic hit a "partial" match, and Design.md renders it
# visually weaker than an exact match (hollow dot, dashed border) — the
# percentage credit has to be weaker too, or the visual distinction would
# be misleading. Not a guess in the same sense as the threshold above: this
# is a deliberate formula choice (half credit), not an unmeasured constant.
SEMANTIC_MATCH_WEIGHT = 0.5

# A real-model sanity check (docs/EVALUATION.md's Phase 7 section) found
# SEMANTIC_MATCH_THRESHOLD isn't just unmeasured — it's inverted on the
# cases that matter: "PostgreSQL" vs "MySQL" (two different database
# products) scores 0.547, above threshold, while "AWS" vs "cloud
# infrastructure" (a genuine paraphrase) scores 0.492, below it. That means
# a candidate listing MySQL would get half credit toward a PostgreSQL
# requirement while a genuine paraphrase gets nothing — worse than no
# semantic matching at all. This is a blocking issue, not a limitation:
# semantic matching refuses to run (scoring_service._semantic_embed_fn
# checks this before ever touching the model) regardless of
# settings.SEMANTIC_SKILL_MATCHING, until Phases.md Phase 13 validates a
# real threshold against ml/skill_eval's labelled set and this is flipped
# to True by a person, not a script.
THRESHOLD_VALIDATED = False


@dataclass(frozen=True)
class SkillGapMatch:
    skill: str
    source: SkillSource
    matched_via: str | None = None


@dataclass(frozen=True)
class SkillGapResult:
    matched: list[SkillGapMatch]
    missing: list[str]
    additional: list[str]
    percentage: float


def compute_skill_gap(required_skills: list[str], candidate_skills: list[str]) -> SkillGapResult:
    """`required_skills` is the job's free-typed list; `candidate_skills`
    is the candidate's canonical dictionary matches. Returns matched
    (required skills the candidate has, each tagged source=dictionary —
    F4.4's semantic fallback is a separate, opt-in step, never run from
    inside this function), missing (required skills with no dictionary
    match), additional (candidate skills outside the requirement, in their
    canonical casing), and percentage = matched / total required x 100.

    Assumes at least one required skill — the caller guards an empty
    `required_skills` before this is ever reached (JOB_HAS_NO_SKILLS,
    Rules.md 5.4), so this function does not itself guard the division.
    """
    candidate_by_lower = {skill.lower(): skill for skill in candidate_skills}
    required_lower = {skill.lower() for skill in required_skills}

    matched = [
        SkillGapMatch(skill=skill, source=SkillSource.DICTIONARY)
        for skill in required_skills
        if skill.lower() in candidate_by_lower
    ]
    missing = [skill for skill in required_skills if skill.lower() not in candidate_by_lower]
    additional = [
        original for lower, original in candidate_by_lower.items() if lower not in required_lower
    ]

    percentage = len(matched) / len(required_skills) * 100
    return SkillGapResult(matched=matched, missing=missing, additional=additional, percentage=percentage)


def apply_semantic_fallback(
    gap: SkillGapResult, candidate_skills: list[str], embed: Callable[[str], list[float]]
) -> SkillGapResult:
    """F4.4: for every still-missing required skill, checks its cosine
    similarity against each of the candidate's own matched skills, using
    `embed` — a text -> vector function backed by the embedding singleton
    in embedding_ranker.py (passed in rather than imported here, so this
    module stays independent of which ranker, if any, is active; the
    caller is responsible for only calling this when
    settings.SEMANTIC_SKILL_MATCHING is true and the model is confirmed
    available — see scoring_service.py).

    The single best-scoring candidate skill above SEMANTIC_MATCH_THRESHOLD
    promotes a required skill from `missing` into `matched`, tagged
    source=semantic with matched_via naming which candidate skill it
    matched against. `percentage` is recomputed giving semantic matches
    SEMANTIC_MATCH_WEIGHT credit instead of a full 1.0, so a semantic-only
    result never reads identically to an all-exact one.

    A no-op (returns `gap` unchanged) when there's nothing to promote —
    no missing skills, or the candidate has no matched skills to compare
    against. Propagates whatever `embed` raises otherwise; the caller has
    already confirmed the model loads before this is ever called.
    """
    if not gap.missing or not candidate_skills:
        return gap

    candidate_vectors = {skill: embed(skill) for skill in candidate_skills}

    still_missing: list[str] = []
    promoted: list[SkillGapMatch] = []
    for required in gap.missing:
        required_vector = embed(required)
        best_skill: str | None = None
        best_similarity = 0.0
        for candidate_skill, candidate_vector in candidate_vectors.items():
            similarity = float(cosine_similarity([required_vector], [candidate_vector])[0][0])
            if similarity > best_similarity:
                best_skill, best_similarity = candidate_skill, similarity
        if best_skill is not None and best_similarity >= SEMANTIC_MATCH_THRESHOLD:
            promoted.append(
                SkillGapMatch(skill=required, source=SkillSource.SEMANTIC, matched_via=best_skill)
            )
        else:
            still_missing.append(required)

    matched = gap.matched + promoted
    semantic_count = len(promoted)
    dictionary_count = len(matched) - semantic_count
    total_required = len(matched) + len(still_missing)
    percentage = (
        (dictionary_count + semantic_count * SEMANTIC_MATCH_WEIGHT) / total_required * 100
        if total_required
        else gap.percentage
    )

    return SkillGapResult(
        matched=matched, missing=still_missing, additional=gap.additional, percentage=percentage
    )
