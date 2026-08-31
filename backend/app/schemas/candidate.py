from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ApplicationStatus, ParseStatus, SkillSource, SkillType


class CandidateSkillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    skill_name: str
    skill_type: SkillType
    source: SkillSource


class GroupedSkills(BaseModel):
    """Skills grouped by SkillType (Phases.md Phase 5 acceptance: "GET
    /candidates/{id} returns skills grouped by type"). All four keys are
    always present, even empty — the frontend can render four fixed
    columns without a conditional per group.
    """

    technical: list[CandidateSkillOut] = Field(default_factory=list)
    tool: list[CandidateSkillOut] = Field(default_factory=list)
    soft: list[CandidateSkillOut] = Field(default_factory=list)
    domain: list[CandidateSkillOut] = Field(default_factory=list)


class CandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None
    # Nullable as of Phase 4 — see models/candidate.py. A parsed or
    # parse_failed candidate created this phase has no email yet; Phase 5's
    # regex extractor is what populates it.
    email: str | None
    phone: str | None
    # resume_text, resume_path, and embedding are deliberately absent: resume text
    # only leaves the system on an explicit question-generation request (Rules.md 7),
    # and the storage path/embedding vector are internal details, not API surface.
    education: str | None
    education_level: int | None
    experience_years: float | None
    projects: list
    certifications: list
    parse_status: ParseStatus
    parse_error: str | None
    created_at: datetime


class CandidateDetailResponse(CandidateResponse):
    skills: GroupedSkills


class CandidateListItem(CandidateResponse):
    """`GET /candidates`'s item shape (Phases.md Phase 12, Architecture.md
    6.2's `min_score`/`sort_by=fit_score` query params) — adds the fit
    score actually used to filter/sort this listing, visible rather than
    an implicit fact a caller would have to reverse-engineer from the
    query. `job_id`-filtered listing -> that job's score. Unfiltered
    listing -> the candidate's best (highest) score across every job
    they've been scored for, since a global candidate list has no single
    job to score against. `None` when the candidate has no score at all
    (or none for the filtered job) yet — never a fabricated zero.
    """

    fit_score: float | None = None


class ApplicationStatusUpdate(BaseModel):
    status: ApplicationStatus


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_id: int
    job_id: int
    status: ApplicationStatus
    created_at: datetime
    updated_at: datetime
