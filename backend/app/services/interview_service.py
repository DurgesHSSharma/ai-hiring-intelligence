"""Interview question generation (PRD F8, Architecture.md 7.3, Phases.md
Phase 8). Raises domain exceptions from core/exceptions.py; never
HTTPException (Rules.md 5.2).
"""
import logging
import re
import time
import uuid as uuid_module
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.enums import ParseStatus
from app.core.exceptions import LLMError, NotFoundError, ValidationError
from app.ml.extraction import field_extractor
from app.ml.llm import client as llm_client
from app.ml.llm.parser import LLMOutputError, LLMQuestionItem, parse_questions
from app.ml.llm.prompts import (
    QUESTION_GENERATION_SYSTEM,
    QUESTION_GENERATION_TEMPLATE,
    REPAIR_INSTRUCTION_TEMPLATE,
)
from app.ml.skills.skill_gap import compute_skill_gap
from app.models.candidate import Candidate
from app.models.interview_question import InterviewQuestion
from app.models.job import Job
from app.schemas.interview import InterviewQuestionOut, InterviewQuestionsResponse
from app.utils.text import compile_boundary_pattern

logger = logging.getLogger(__name__)

# Decision (Phase 8 plan, approved): request more than the final target so
# the grounding filter below has room to drop ungrounded questions without
# starving the 5-8 range F8.1 requires. Default count=8 -> requests 10.
MODEL_REQUEST_BUFFER = 2
MIN_QUESTIONS = 5

# Hard cap on how much resume text enters the prompt — bounds worst-case
# cost on an anomalously long document (cost control). Typical cleaned
# resumes are well under this.
RESUME_TEXT_CHAR_CAP = 8000

# DB column is String(400) (models/interview_question.py) — truncated here
# rather than at the schema layer, since this is an adaptation to how the
# value is persisted, not a validation rule on the LLM's output shape.
RATIONALE_CHAR_CAP = 400

_MIN_ANCHOR_LEN = 3
_ANCHOR_TOKEN_RE = re.compile(r"[A-Za-z0-9+#.]+")

# F8.4 fix — multi-word proper-noun anchors ("Corvid Labs"). A single
# per-token shape rule can never pass either half of an ordinary Title
# Case company name (neither word has a digit, is all-caps, or has an
# internal capital), so this looks for a *run* of 2+ consecutive
# Title-Case words instead. A single sentence-initial capital ("Led the
# migration...") is one word followed by lowercase and never forms a run,
# so ordinary bullet prose is excluded by this shape alone. See
# _experience_section_anchors for the second guard (the line must also
# carry a date range) that keeps this from also catching the job-title
# line sitting next to a "Company | Dates" line.
_PROPER_NOUN_RUN_RE = re.compile(r"(?:[A-Z][\w&'.-]*\s+){1,4}[A-Z][\w&'.-]*")


def _get_candidate_or_404(db: Session, candidate_id: int) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise NotFoundError(
            "Candidate not found.", code="CANDIDATE_NOT_FOUND", details={"candidate_id": candidate_id}
        )
    return candidate


def _get_job_or_404(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise NotFoundError("Job not found.", code="JOB_NOT_FOUND", details={"job_id": job_id})
    return job


def _has_usable_resume_text(candidate: Candidate) -> bool:
    return candidate.parse_status == ParseStatus.PARSED and bool(
        candidate.resume_text and candidate.resume_text.strip()
    )


def _stored_questions(db: Session, candidate_id: int, job_id: int) -> list[InterviewQuestion]:
    return (
        db.query(InterviewQuestion)
        .filter(InterviewQuestion.candidate_id == candidate_id, InterviewQuestion.job_id == job_id)
        .order_by(InterviewQuestion.id.asc())
        .all()
    )


def _to_response(candidate_id: int, job_id: int, rows: list[InterviewQuestion]) -> InterviewQuestionsResponse:
    first = rows[0]
    return InterviewQuestionsResponse(
        candidate_id=candidate_id,
        job_id=job_id,
        generation_batch=first.generation_batch,
        requested=first.requested,
        generated=first.generated,
        grounded=first.grounded,
        partial=first.grounded < MIN_QUESTIONS,
        questions=[InterviewQuestionOut.model_validate(row) for row in rows],
    )


def _looks_specific(token: str) -> bool:
    """A free-text word from a projects/certifications entry counts as a
    grounding anchor only if it looks like a proper noun, product, or
    technology name rather than ordinary prose: it contains a digit, is an
    all-caps acronym ("AWS"), or has an internal capital letter
    (camelCase/PascalCase, e.g. "StockWatch"). A plain capitalized English
    word does not qualify.

    Found by testing, not assumed: without this, a project description
    like "a real-time inventory tracker" leaks ordinary words ("Real",
    "Time") into the anchor set, and a fully generic question ("Tell me
    about a time you...") passes only because it happens to contain the
    word "time" — exactly the failure mode docs/EVALUATION.md's Phase 8
    section already warns this filter is weak to. This narrows it further,
    it doesn't eliminate the weakness (a question can still pass by
    naming a real anchor generically).

    Reused unchanged for resume_text-derived anchors below (verified by
    tracing it against a real Experience section — see the Phase 8
    grounding-filter fix plan): the historical leak above came from having
    no shape filter at all, not from this filter being source-specific.
    """
    if any(ch.isdigit() for ch in token):
        return True
    if token.isupper() and len(token) >= 2:
        return True
    return any(ch.isupper() for ch in token[1:])


def _experience_section_anchors(resume_text: str) -> set[str]:
    """F8.4 fix: real resumes that describe everything inside Experience
    bullets (no distinct Projects/Certifications heading) previously left
    the grounding filter with only bare skill names as anchors, rejecting
    the model's best, most specific questions — the ones naming a real
    employer or project that lives only in this prose. Draws two kinds of
    anchor from the Experience section (or the whole resume, only when no
    EXPERIENCE heading is found at all — same fallback precedent
    field_extractor.extract_experience_years() already uses):

    - Single tokens anywhere in the scoped text, via the unchanged
      _looks_specific() shape rule above. Heading words are excluded
      first (field_extractor.is_heading_word) — without this, the
      whole-text fallback can pick up a heading word a layout defect
      welded onto adjacent content (Phase 5 decision 27, e.g. "Wei Chen
      EXPERIENCE") as if it were real content, and "experience" would
      become a permanent free-pass anchor for one of the most common
      words in any interview question.
    - Multi-word Title Case runs (_PROPER_NOUN_RUN_RE), but only on a
      line that also contains an employment date range
      (field_extractor.find_date_ranges) — this is what excludes the
      job-title line sitting next to a "Company | Dates" line ("Senior
      Software Engineer" has the same 2+-word shape but carries no date)
      without needing any title-vs-company vocabulary list.
    """
    section = field_extractor.extract_experience_section_text(resume_text)
    if section is None:
        section = resume_text

    anchors: set[str] = set()
    for line in section.split("\n"):
        for word in _ANCHOR_TOKEN_RE.findall(line):
            if (
                len(word) >= _MIN_ANCHOR_LEN
                and not field_extractor.is_heading_word(word)
                and _looks_specific(word)
            ):
                anchors.add(word.lower())
        if field_extractor.find_date_ranges(line):
            anchors.update(run.lower() for run in _PROPER_NOUN_RUN_RE.findall(line))
    return anchors


def _build_grounding_anchors(candidate: Candidate, candidate_skill_names: list[str]) -> set[str]:
    """F8.4. Anchors come ONLY from the candidate's own extracted data —
    skills, projects, certifications, and (as of the Phase 8 grounding-fix
    session) Experience-section prose — never from the job posting, so a
    question that only names a job requirement the candidate doesn't have
    cannot pass by construction (approved design decision: missing-skill
    questions usually get filtered as a result, and that's accepted —
    a question that survives only by naming the gap itself would be
    generic by construction, which is exactly what F8.4 exists to prevent).

    candidate_skill_names go in unfiltered — they're structured dictionary
    matches, not free text, so there's no ordinary-prose-word risk to guard
    against the way there is for projects/certifications/resume_text below.
    """
    anchors = {skill.lower() for skill in candidate_skill_names}
    for entry in candidate.projects + candidate.certifications:
        for word in _ANCHOR_TOKEN_RE.findall(entry):
            if len(word) >= _MIN_ANCHOR_LEN and _looks_specific(word):
                anchors.add(word.lower())
    anchors |= _experience_section_anchors(candidate.resume_text)
    return anchors


def _compile_anchor_patterns(anchors: set[str]) -> list[re.Pattern[str]]:
    """Word-boundary-safe compilation of each anchor, reusing the same
    matcher skill_matcher.py already relies on (Phase 5) rather than a
    third implementation. A plain substring check would let a short
    anchor like "go" (from the skill "Go") match inside an unrelated word
    ("algorithm") — the same false-positive class already solved once for
    skill matching, and one that matters more now that resume_text-derived
    anchors (above) make anchors the entire mechanism standing between
    "generic" and "grounded" for resumes that used to have almost none.
    Compiled once per generation call, not once per question, since the
    same anchor set is checked against every candidate question.
    """
    return [compile_boundary_pattern(anchor) for anchor in anchors]


def _is_grounded(question_text: str, anchor_patterns: list[re.Pattern[str]]) -> bool:
    """Boundary-safe substring membership, not semantic matching — see
    docs/EVALUATION.md's Phase 8 section for what this does and does not
    catch.
    """
    return any(pattern.search(question_text) for pattern in anchor_patterns)


def _build_prompt(job: Job, candidate: Candidate, gap, *, count: int) -> str:
    return QUESTION_GENERATION_TEMPLATE.format(
        count=count,
        job_title=job.title,
        job_seniority=job.seniority.value,
        required_skills=", ".join(job.required_skills) or "(none listed)",
        min_experience_years=job.min_experience_years,
        job_description=job.description,
        matched_skills=", ".join(match.skill for match in gap.matched) or "(none)",
        missing_skills=", ".join(gap.missing) or "(none)",
        experience_years=candidate.experience_years if candidate.experience_years is not None else "unknown",
        education=candidate.education or "unknown",
        projects="\n".join(f"- {p}" for p in candidate.projects) or "(none listed)",
        certifications="\n".join(f"- {c}" for c in candidate.certifications) or "(none listed)",
        resume_text=candidate.resume_text[:RESUME_TEXT_CHAR_CAP],
    )


def _call_llm_and_log(prompt: str, *, candidate_id: int, job_id: int) -> llm_client.LLMResult:
    """Rules.md 5.5: log every LLM call with model, latency, and outcome —
    never the full prompt or response body. Wraps every actual call to the
    provider (initial and repair), so a generation needing repair produces
    two log lines, not one.
    """
    start = time.monotonic()
    try:
        result = llm_client.generate(prompt, system=QUESTION_GENERATION_SYSTEM)
    except LLMError as exc:
        latency_ms = (time.monotonic() - start) * 1000
        logger.info(
            "llm_generation candidate_id=%s job_id=%s model=%s latency_ms=%.0f outcome=%s",
            candidate_id,
            job_id,
            llm_client.resolve_model(),
            latency_ms,
            exc.code,
        )
        raise
    latency_ms = (time.monotonic() - start) * 1000
    logger.info(
        "llm_generation candidate_id=%s job_id=%s model=%s latency_ms=%.0f "
        "input_tokens=%s output_tokens=%s outcome=success",
        candidate_id,
        job_id,
        result.model,
        latency_ms,
        result.input_tokens,
        result.output_tokens,
    )
    return result


@dataclass
class _GroundedGeneration:
    questions: list[LLMQuestionItem]  # count-truncated, what gets persisted
    generated: int  # what the model returned, before filtering
    grounded: int  # how many survived the filter, before count truncation


def _generate_grounded_questions(
    prompt: str,
    candidate: Candidate,
    candidate_skill_names: list[str],
    *,
    candidate_id: int,
    job_id: int,
    max_questions: int,
) -> _GroundedGeneration:
    result = _call_llm_and_log(prompt, candidate_id=candidate_id, job_id=job_id)
    try:
        parsed = parse_questions(result.text)
    except LLMOutputError as exc:
        repair_prompt = prompt + "\n\n" + REPAIR_INSTRUCTION_TEMPLATE.format(error=exc)
        result = _call_llm_and_log(repair_prompt, candidate_id=candidate_id, job_id=job_id)
        try:
            parsed = parse_questions(result.text)
        except LLMOutputError as exc2:
            raise LLMError(
                f"LLM output failed validation after one repair attempt: {exc2}", code="LLM_INVALID_OUTPUT"
            ) from exc2

    anchors = _build_grounding_anchors(candidate, candidate_skill_names)
    anchor_patterns = _compile_anchor_patterns(anchors)
    grounded_all = [q for q in parsed.questions if _is_grounded(q.question, anchor_patterns)]
    generated_count = len(parsed.questions)
    grounded_count = len(grounded_all)

    # Phase 8 grounding-filter fix: a genuine zero-grounded outcome (the
    # model's output truly had nothing groundable in it) is a distinct
    # failure from LLM_INVALID_OUTPUT above (unparseable/invalid output) —
    # conflating the two as one 503 code hid which one actually happened.
    # Between 1 and MIN_QUESTIONS-1 survivors is no longer a hard failure
    # at all: the shorter set is returned to the caller (generate_questions
    # persists requested/generated/grounded so the response body makes the
    # partial result explicit, never left for a caller to infer from
    # array length — see schemas/interview.py).
    if grounded_count == 0:
        raise LLMError(
            f"None of the {generated_count} generated questions referenced a concrete "
            f"resume detail for this candidate.",
            code="INSUFFICIENT_GROUNDED_QUESTIONS",
            details={"generated": generated_count, "grounded": 0, "minimum_target": MIN_QUESTIONS},
        )
    if grounded_count < MIN_QUESTIONS:
        logger.warning(
            "grounding_filter_below_target candidate_id=%s job_id=%s generated=%s grounded=%s "
            "minimum_target=%s",
            candidate_id,
            job_id,
            generated_count,
            grounded_count,
            MIN_QUESTIONS,
        )

    return _GroundedGeneration(
        questions=grounded_all[:max_questions],
        generated=generated_count,
        grounded=grounded_count,
    )


def generate_questions(
    db: Session, candidate_id: int, job_id: int, *, count: int = 8, regenerate: bool = False
) -> InterviewQuestionsResponse:
    candidate = _get_candidate_or_404(db, candidate_id)
    job = _get_job_or_404(db, job_id)

    existing = _stored_questions(db, candidate_id, job_id)
    if existing and not regenerate:
        # Architecture.md 7.3: "if stored questions exist and
        # regenerate=false -> return them, no LLM call." This is the actual
        # mechanism that stops a second call from spending anything.
        return _to_response(candidate_id, job_id, existing)

    if not job.required_skills:
        raise ValidationError(
            "This job has no required skills; a skill gap cannot be computed.",
            code="JOB_HAS_NO_SKILLS",
            details={"job_id": job_id},
        )
    if not _has_usable_resume_text(candidate):
        raise ValidationError(
            "Candidate has no usable resume text (parse failed).",
            code="RESUME_TEXT_TOO_SHORT",
            details={"candidate_id": candidate_id},
        )

    candidate_skill_names = [skill.skill_name for skill in candidate.candidate_skills]
    gap = compute_skill_gap(job.required_skills, candidate_skill_names)

    prompt = _build_prompt(job, candidate, gap, count=count + MODEL_REQUEST_BUFFER)
    generation = _generate_grounded_questions(
        prompt,
        candidate,
        candidate_skill_names,
        candidate_id=candidate_id,
        job_id=job_id,
        max_questions=count,
    )

    batch_id = uuid_module.uuid4()
    for row in existing:
        db.delete(row)
    for item in generation.questions:
        db.add(
            InterviewQuestion(
                candidate_id=candidate_id,
                job_id=job_id,
                question=item.question,
                category=item.category,
                difficulty=item.difficulty,
                rationale=item.rationale[:RATIONALE_CHAR_CAP] if item.rationale else None,
                generation_batch=batch_id,
                requested=count,
                generated=generation.generated,
                grounded=generation.grounded,
            )
        )
    db.commit()

    return _to_response(candidate_id, job_id, _stored_questions(db, candidate_id, job_id))


def get_questions(db: Session, candidate_id: int, job_id: int) -> InterviewQuestionsResponse:
    _get_candidate_or_404(db, candidate_id)
    _get_job_or_404(db, job_id)

    rows = _stored_questions(db, candidate_id, job_id)
    if not rows:
        raise NotFoundError(
            "No interview questions have been generated for this candidate and job yet.",
            code="INTERVIEW_QUESTIONS_NOT_FOUND",
            details={"candidate_id": candidate_id, "job_id": job_id},
        )
    return _to_response(candidate_id, job_id, rows)
